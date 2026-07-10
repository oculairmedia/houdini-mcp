"""Code execution tools.

This module provides tools for executing Python code in Houdini
with safety rails, policy profiles, timeout handling, rollback-on-timeout,
and scene diff tracking.

Safety model (bead houdini-mcp-9e2)
-----------------------------------
* Policy profiles gate what a request is *allowed* to attempt:
    - ``read-only``  : inspection only; any scene mutation / dangerous op is
                       blocked before execution. Bypass flags are ignored.
    - ``normal``     : default; dangerous + heavy-geometry patterns are blocked
                       unless the caller opts in *and* the server is configured
                       to permit bypass.
    - ``privileged`` : intended for trusted automation; only usable when the
                       server-side bypass configuration gate is enabled.
* Bypass requires BOTH a request flag (``allow_dangerous`` /
  ``allow_heavy_geometry``) AND server configuration
  (``HOUDINI_MCP_ALLOW_BYPASS``). Missing either fails closed.
* Every call returns a structured ``audit`` block and is logged.
* On timeout the run is rolled back via a named Houdini undo group when a usable
  undo primitive is available; otherwise it fails closed and reports that
  mutations may be untracked (the daemon thread cannot be force-killed).
"""

import builtins
import hashlib
import logging
import os
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any

from ._common import (
    _detect_dangerous_code,
    _detect_heavy_geometry_code,
    _detect_import_hou,
    _detect_mutation_code,
    _get_scene_diff,
    _serialize_scene_state,
    _truncate_output,
    ensure_connected,
    handle_connection_errors,
)

logger = logging.getLogger("houdini_mcp.tools.code")

# Re-exported so tests can monkeypatch a builtin-free reference. ``exec`` is a
# builtin; patching a module-level name lets us prove blocked code never runs.
exec = builtins.exec  # noqa: A001 - intentional shadow for testability

# Module-level storage for scene diff tracking
_before_scene: list[dict[str, Any]] = []
_after_scene: list[dict[str, Any]] = []

# Policy profiles, from strictest to most permissive.
VALID_POLICIES = ("read-only", "normal", "privileged")
DEFAULT_POLICY = "normal"

# Named undo group used to wrap execution so a timeout can roll back.
_UNDO_GROUP_LABEL = "houdini-mcp execute_code"


def _bypass_config_enabled() -> bool:
    """Whether the server is configured to permit safety-rail bypass.

    This is the *configuration* half of the config+request opt-in. It is a
    separate function so tests and deployments can override it explicitly.
    """
    return os.getenv("HOUDINI_MCP_ALLOW_BYPASS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_undo_primitive(hou: Any) -> Any | None:
    """Return the ``hou.undos`` namespace if a usable undo primitive exists.

    We require both a ``group`` context factory (to wrap execution) and a
    ``performUndo`` callable (to roll back on timeout). If either is missing we
    return None so callers can fail closed instead of silently leaving
    untracked mutations.
    """
    undos = getattr(hou, "undos", None)
    if undos is None:
        return None
    if not callable(getattr(undos, "group", None)):
        return None
    if not callable(getattr(undos, "performUndo", None)):
        return None
    return undos


def _run_code_thread(
    code: str,
    hou: Any,
    stdout_capture: StringIO,
    stderr_capture: StringIO,
    exec_exception: list[Exception | None],
    exec_traceback: list[str],
) -> None:
    """Execute user code, capturing stdout/stderr and any exception."""
    try:
        exec_globals = {"hou": hou, "__builtins__": builtins.__dict__}
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, exec_globals)
    except Exception as e:  # noqa: BLE001 - surfaced to caller as an error result
        exec_exception[0] = e
        exec_traceback[0] = traceback.format_exc()


def _build_audit(
    *,
    code: str,
    policy: str,
    allow_dangerous: bool,
    allow_heavy_geometry: bool,
    bypass_config_enabled: bool,
    dangerous_patterns: list[str],
    heavy_geometry_patterns: list[str],
    mutation_patterns: list[str] | None = None,
    timed_out: bool = False,
    rollback_attempted: bool = False,
    rollback_succeeded: bool | None = None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    """Assemble the structured audit block returned with every response."""
    return {
        "policy": policy,
        "allow_dangerous_requested": allow_dangerous,
        "allow_heavy_geometry_requested": allow_heavy_geometry,
        "bypass_config_enabled": bypass_config_enabled,
        "dangerous_patterns": dangerous_patterns,
        "heavy_geometry_patterns": heavy_geometry_patterns,
        "mutation_patterns": mutation_patterns or [],
        "timed_out": timed_out,
        "rollback_attempted": rollback_attempted,
        "rollback_succeeded": rollback_succeeded,
        "blocked_reason": blocked_reason,
        "code_length": len(code),
        "code_sha256": hashlib.sha256(code.encode("utf-8", "replace")).hexdigest(),
    }


@handle_connection_errors("execute_code")
def execute_code(
    code: str,
    capture_diff: bool = False,
    max_stdout_size: int = 100000,
    max_stderr_size: int = 100000,
    max_diff_nodes: int = 1000,
    timeout: int = 30,
    allow_dangerous: bool = False,
    host: str = "localhost",
    port: int = 18811,
    allow_heavy_geometry: bool = False,
    policy: str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """
    Execute Python code in Houdini with policy-gated safety rails.

    IMPORTANT: The 'hou' module is pre-injected as a global variable via RPyC.
    Do NOT use 'import hou' or 'from hou import ...' - just use 'hou' directly.

    Args:
        code: Python code to execute. The 'hou' module is pre-injected and available
            as a global variable. Access it directly (e.g., hou.node('/obj')) without importing.
        capture_diff: If True, captures before/after scene state for comparison.
        max_stdout_size: Maximum stdout size in bytes (default: 100000 = 100KB).
        max_stderr_size: Maximum stderr size in bytes (default: 100000 = 100KB).
        max_diff_nodes: Maximum number of nodes in scene diff added_nodes (default: 1000).
        timeout: Execution timeout in seconds (default: 30).
        allow_dangerous: Request-side opt-in to bypass dangerous-pattern blocking.
            Only honored when the server bypass config is also enabled.
        allow_heavy_geometry: Request-side opt-in to allow direct SOP geometry
            access. Only honored when the server bypass config is also enabled.
        policy: Safety profile - one of "read-only", "normal", "privileged".

    Returns:
        Dict with execution result including stdout/stderr, scene changes,
        a structured ``audit`` block, and (on timeout) a ``rollback`` block.
    """
    global _before_scene, _after_scene

    bypass_config = _bypass_config_enabled()

    # --- Validate policy profile (fail closed on unknown values) -------------
    if policy not in VALID_POLICIES:
        logger.warning("execute_code blocked: unknown policy %r", policy)
        return {
            "status": "error",
            "message": (f"Unknown policy {policy!r}. Valid policies: {', '.join(VALID_POLICIES)}."),
            "policy": policy,
            "audit": _build_audit(
                code=code,
                policy=policy,
                allow_dangerous=allow_dangerous,
                allow_heavy_geometry=allow_heavy_geometry,
                bypass_config_enabled=bypass_config,
                dangerous_patterns=[],
                heavy_geometry_patterns=[],
                blocked_reason="unknown_policy",
            ),
        }

    # --- privileged profile requires the server-side config gate -------------
    if policy == "privileged" and not bypass_config:
        logger.warning("execute_code blocked: privileged policy without config gate")
        return {
            "status": "error",
            "message": (
                "Policy 'privileged' requires server configuration "
                "HOUDINI_MCP_ALLOW_BYPASS to be enabled. Failing closed."
            ),
            "policy": policy,
            "audit": _build_audit(
                code=code,
                policy=policy,
                allow_dangerous=allow_dangerous,
                allow_heavy_geometry=allow_heavy_geometry,
                bypass_config_enabled=bypass_config,
                dangerous_patterns=[],
                heavy_geometry_patterns=[],
                blocked_reason="privileged_without_config",
            ),
        }

    # --- Empty code ----------------------------------------------------------
    if not code or not code.strip():
        return {
            "status": "success",
            "stdout": "",
            "stderr": "",
            "message": "Empty code - nothing to execute",
            "policy": policy,
            "audit": _build_audit(
                code=code or "",
                policy=policy,
                allow_dangerous=allow_dangerous,
                allow_heavy_geometry=allow_heavy_geometry,
                bypass_config_enabled=bypass_config,
                dangerous_patterns=[],
                heavy_geometry_patterns=[],
            ),
        }

    # Detect the common mistake of importing hou when it is pre-injected via RPyC.
    # (Preserved from bead houdini-mcp-vzp.1 / PR #9.)
    if _detect_import_hou(code):
        return {
            "status": "error",
            "message": "Code attempts to import hou module, but hou is already available",
            "policy": policy,
            "hint": (
                "The 'hou' module is pre-injected as a global variable by execute_code via RPyC. "
                "You can use 'hou' directly without importing it. Remove 'import hou' or "
                "'from hou import ...' from your code and access hou directly (e.g., hou.node('/obj'))."
            ),
            "suggested_fix": code.replace(
                "import hou", "# import hou  # Not needed - hou is pre-injected"
            ).replace("from hou import ", "# from hou import "),
            "audit": _build_audit(
                code=code,
                policy=policy,
                allow_dangerous=allow_dangerous,
                allow_heavy_geometry=allow_heavy_geometry,
                bypass_config_enabled=bypass_config,
                dangerous_patterns=[],
                heavy_geometry_patterns=[],
                blocked_reason="import_hou",
            ),
        }

    dangerous_patterns = _detect_dangerous_code(code)
    heavy_geometry_patterns = _detect_heavy_geometry_code(code)

    # --- read-only profile: block any mutation before execution --------------
    if policy == "read-only":
        mutation_patterns = _detect_mutation_code(code)
        if mutation_patterns:
            logger.warning("execute_code blocked under read-only policy: %s", mutation_patterns)
            return {
                "status": "error",
                "message": (
                    "Scene mutation blocked under read-only policy. "
                    "Use policy='normal' (default) for changes."
                ),
                "policy": policy,
                "mutation_patterns": mutation_patterns,
                "hint": (
                    "read-only permits inspection only. Re-run with policy='normal' "
                    "to allow scene changes."
                ),
                "audit": _build_audit(
                    code=code,
                    policy=policy,
                    allow_dangerous=allow_dangerous,
                    allow_heavy_geometry=allow_heavy_geometry,
                    bypass_config_enabled=bypass_config,
                    dangerous_patterns=dangerous_patterns,
                    heavy_geometry_patterns=heavy_geometry_patterns,
                    mutation_patterns=mutation_patterns,
                    blocked_reason="read_only_mutation",
                ),
            }

    # --- Effective bypass = request flag AND server config -------------------
    dangerous_bypass = allow_dangerous and bypass_config
    heavy_bypass = (allow_heavy_geometry or allow_dangerous) and bypass_config

    # --- Dangerous-pattern gate ---------------------------------------------
    if dangerous_patterns and not dangerous_bypass:
        if allow_dangerous and not bypass_config:
            logger.warning(
                "execute_code blocked: allow_dangerous requested but bypass config disabled"
            )
            message = (
                "Bypass requested (allow_dangerous=True) but server config "
                "HOUDINI_MCP_ALLOW_BYPASS is disabled. Failing closed."
            )
            blocked_reason = "bypass_config_disabled"
        else:
            logger.warning("execute_code blocked: dangerous patterns %s", dangerous_patterns)
            message = "Dangerous operations detected in code"
            blocked_reason = "dangerous_pattern"
        return {
            "status": "error",
            "message": message,
            "policy": policy,
            "dangerous_patterns": dangerous_patterns,
            "bypass_requested": bool(allow_dangerous),
            "bypass_config_enabled": bypass_config,
            "hint": ("Set allow_dangerous=True AND enable HOUDINI_MCP_ALLOW_BYPASS to proceed."),
            "audit": _build_audit(
                code=code,
                policy=policy,
                allow_dangerous=allow_dangerous,
                allow_heavy_geometry=allow_heavy_geometry,
                bypass_config_enabled=bypass_config,
                dangerous_patterns=dangerous_patterns,
                heavy_geometry_patterns=heavy_geometry_patterns,
                blocked_reason=blocked_reason,
            ),
        }

    # --- Heavy-geometry gate -------------------------------------------------
    if heavy_geometry_patterns and not heavy_bypass:
        if (allow_heavy_geometry or allow_dangerous) and not bypass_config:
            logger.warning(
                "execute_code blocked: heavy-geometry bypass requested but config disabled"
            )
            message = (
                "Heavy geometry bypass requested but server config "
                "HOUDINI_MCP_ALLOW_BYPASS is disabled. Failing closed."
            )
            blocked_reason = "bypass_config_disabled"
        else:
            logger.warning(
                "execute_code blocked: heavy geometry access %s", heavy_geometry_patterns
            )
            message = "Heavy geometry access detected in code"
            blocked_reason = "heavy_geometry"
        return {
            "status": "error",
            "message": message,
            "policy": policy,
            "heavy_geometry_patterns": heavy_geometry_patterns,
            "bypass_requested": bool(allow_heavy_geometry or allow_dangerous),
            "bypass_config_enabled": bypass_config,
            "hint": (
                "Use get_geo_summary() for bounded geometry inspection, or set "
                "allow_heavy_geometry=True AND enable HOUDINI_MCP_ALLOW_BYPASS."
            ),
            "audit": _build_audit(
                code=code,
                policy=policy,
                allow_dangerous=allow_dangerous,
                allow_heavy_geometry=allow_heavy_geometry,
                bypass_config_enabled=bypass_config,
                dangerous_patterns=dangerous_patterns,
                heavy_geometry_patterns=heavy_geometry_patterns,
                blocked_reason=blocked_reason,
            ),
        }

    # --- Connect and prepare execution --------------------------------------
    hou = ensure_connected(host, port)
    undos = _resolve_undo_primitive(hou)

    if capture_diff:
        _before_scene = _serialize_scene_state(hou)

    stdout_capture = StringIO()
    stderr_capture = StringIO()
    exec_exception: list[Exception | None] = [None]
    exec_traceback: list[str] = [""]

    def run_code() -> None:
        # Wrap execution in a named undo group so a timeout can roll it back.
        if undos is not None:
            try:
                with undos.group(_UNDO_GROUP_LABEL):
                    _run_code_thread(
                        code,
                        hou,
                        stdout_capture,
                        stderr_capture,
                        exec_exception,
                        exec_traceback,
                    )
                return
            except Exception:  # noqa: BLE001 - undo group unusable; fall back
                logger.debug("undo group unavailable at runtime; running ungrouped")
        _run_code_thread(
            code,
            hou,
            stdout_capture,
            stderr_capture,
            exec_exception,
            exec_traceback,
        )

    # Daemon thread: if it times out we cannot kill it, but it must not keep the
    # process alive. The undo-group rollback keeps the scene consistent.
    exec_thread = threading.Thread(target=run_code, daemon=True)
    exec_thread.start()
    exec_thread.join(timeout=timeout)

    if exec_thread.is_alive():
        # --- Timeout: roll back if possible, else fail closed ---------------
        logger.warning("execute_code exceeded timeout of %ss; attempting rollback", timeout)
        rollback_attempted = False
        rollback_succeeded: bool | None = None
        rollback_error: str | None = None

        if undos is not None:
            rollback_attempted = True
            try:
                undos.performUndo()
                rollback_succeeded = True
            except Exception as e:  # noqa: BLE001
                rollback_succeeded = False
                rollback_error = str(e)
                logger.error("execute_code rollback failed after timeout: %s", e)

        if rollback_attempted:
            warning = (
                "Execution timed out. A rollback via the Houdini undo stack was "
                "attempted; verify scene state. The code thread may still be running."
            )
        else:
            warning = (
                "Execution timed out and NO undo primitive was available, so any "
                "partial scene mutations are UNTRACKED. Consider restarting Houdini."
            )

        result: dict[str, Any] = {
            "status": "error",
            "message": f"Execution timeout: code did not complete within {timeout} seconds",
            "policy": policy,
            "stdout": stdout_capture.getvalue()[:max_stdout_size],
            "stderr": stderr_capture.getvalue()[:max_stderr_size],
            "timeout": timeout,
            "warning": warning,
            "rollback": {
                "attempted": rollback_attempted,
                "succeeded": rollback_succeeded,
                "error": rollback_error,
            },
            "audit": _build_audit(
                code=code,
                policy=policy,
                allow_dangerous=allow_dangerous,
                allow_heavy_geometry=allow_heavy_geometry,
                bypass_config_enabled=bypass_config,
                dangerous_patterns=dangerous_patterns,
                heavy_geometry_patterns=heavy_geometry_patterns,
                timed_out=True,
                rollback_attempted=rollback_attempted,
                rollback_succeeded=rollback_succeeded,
            ),
        }
        return result

    audit = _build_audit(
        code=code,
        policy=policy,
        allow_dangerous=allow_dangerous,
        allow_heavy_geometry=allow_heavy_geometry,
        bypass_config_enabled=bypass_config,
        dangerous_patterns=dangerous_patterns,
        heavy_geometry_patterns=heavy_geometry_patterns,
    )

    # --- Exception during execution -----------------------------------------
    if exec_exception[0] is not None:
        stdout_val, stdout_truncated = _truncate_output(stdout_capture.getvalue(), max_stdout_size)
        stderr_val, stderr_truncated = _truncate_output(stderr_capture.getvalue(), max_stderr_size)
        error_result: dict[str, Any] = {
            "status": "error",
            "message": str(exec_exception[0]),
            "traceback": exec_traceback[0],
            "stdout": stdout_val,
            "stderr": stderr_val,
            "policy": policy,
            "audit": audit,
        }
        if stdout_truncated:
            error_result["stdout_truncated"] = True
        if stderr_truncated:
            error_result["stderr_truncated"] = True
        return error_result

    # --- Success -------------------------------------------------------------
    stdout_val, stdout_truncated = _truncate_output(stdout_capture.getvalue(), max_stdout_size)
    stderr_val, stderr_truncated = _truncate_output(stderr_capture.getvalue(), max_stderr_size)

    result = {
        "status": "success",
        "stdout": stdout_val,
        "stderr": stderr_val,
        "policy": policy,
        "audit": audit,
    }

    if stdout_truncated:
        result["stdout_truncated"] = True
        result["stdout_warning"] = f"stdout truncated to {max_stdout_size} bytes"
    if stderr_truncated:
        result["stderr_truncated"] = True
        result["stderr_warning"] = f"stderr truncated to {max_stderr_size} bytes"

    if capture_diff:
        _after_scene = _serialize_scene_state(hou)
        scene_changes = _get_scene_diff(_before_scene, _after_scene)
        diff_truncated = False
        if "added_nodes" in scene_changes and len(scene_changes["added_nodes"]) > max_diff_nodes:
            scene_changes["added_nodes"] = scene_changes["added_nodes"][:max_diff_nodes]
            diff_truncated = True
        result["scene_changes"] = scene_changes
        if diff_truncated:
            result["diff_truncated"] = True
            result["diff_warning"] = f"added_nodes truncated to {max_diff_nodes} nodes"

    if dangerous_patterns:
        result["dangerous_patterns_executed"] = dangerous_patterns
        result["safety_warning"] = (
            "Code with dangerous patterns was executed with an approved bypass."
        )

    return result


def get_last_scene_diff() -> dict[str, Any]:
    """
    Get the scene diff from the last execute_code call.

    Returns:
        Dict with scene changes from last code execution.
    """
    global _before_scene, _after_scene

    if not _before_scene and not _after_scene:
        return {
            "status": "warning",
            "message": "No scene diff available. Run execute_code with capture_diff=True first.",
        }

    return {"status": "success", "diff": _get_scene_diff(_before_scene, _after_scene)}
