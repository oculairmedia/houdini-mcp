"""Code execution tools.

This module provides tools for executing Python code in Houdini
with safety rails, timeout handling, and scene diff tracking.
"""

import logging
import threading
import traceback
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from typing import Any, Dict, List, Optional

from ._common import (
    ensure_connected,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
    _detect_dangerous_code,
    _truncate_output,
    _serialize_scene_state,
    _get_scene_diff,
)

logger = logging.getLogger("houdini_mcp.tools.code")

# Module-level storage for scene diff tracking
_before_scene: List[Dict[str, Any]] = []
_after_scene: List[Dict[str, Any]] = []


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
) -> Dict[str, Any]:
    """
    Execute Python code in Houdini with optional scene diff tracking and safety rails.

    Args:
        code: Python code to execute. The 'hou' module is available.
        capture_diff: If True, captures before/after scene state for comparison
        max_stdout_size: Maximum stdout size in bytes (default: 100000 = 100KB)
        max_stderr_size: Maximum stderr size in bytes (default: 100000 = 100KB)
        max_diff_nodes: Maximum number of nodes in scene diff added_nodes (default: 1000)
        timeout: Execution timeout in seconds (default: 30). Note: May be limited by RPyC.
        allow_dangerous: If True, allows execution of code with dangerous patterns (default: False)

    Returns:
        Dict with execution result including stdout/stderr and scene changes.
        May include truncation flags if output was truncated:
        - stdout_truncated: True if stdout was truncated
        - stderr_truncated: True if stderr was truncated
        - diff_truncated: True if scene diff was truncated
        May include warnings for dangerous patterns even when allowed.
    """
    global _before_scene, _after_scene

    # Handle empty code
    if not code or not code.strip():
        return {
            "status": "success",
            "stdout": "",
            "stderr": "",
            "message": "Empty code - nothing to execute",
        }

    # 1. Scan for dangerous patterns BEFORE execution
    dangerous_patterns = _detect_dangerous_code(code)
    if dangerous_patterns and not allow_dangerous:
        return {
            "status": "error",
            "message": "Dangerous operations detected in code",
            "dangerous_patterns": dangerous_patterns,
            "hint": "Set allow_dangerous=True to proceed with execution",
        }

    try:
        hou = ensure_connected(host, port)

        # Capture scene state before execution (from OpenWebUI pipeline pattern)
        if capture_diff:
            _before_scene = _serialize_scene_state(hou)

        # Capture stdout and stderr
        stdout_capture = StringIO()
        stderr_capture = StringIO()

        # Storage for execution result from thread
        exec_result: Dict[str, Any] = {}
        exec_exception: List[Optional[Exception]] = [None]
        exec_traceback: List[str] = [""]

        def run_code() -> None:
            """Execute code in a separate thread for timeout support."""
            try:
                # Execute in a namespace with hou available
                exec_globals = {"hou": hou, "__builtins__": __builtins__}

                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    exec(code, exec_globals)

            except Exception as e:
                exec_exception[0] = e
                exec_traceback[0] = traceback.format_exc()

        # 2. Execute with timeout using threading
        exec_thread = threading.Thread(target=run_code)
        exec_thread.start()
        exec_thread.join(timeout=timeout)

        if exec_thread.is_alive():
            # Timeout occurred - thread is still running
            # Note: We can't forcefully kill the thread in Python, but we can return
            # an error to the user. The code may continue running in the background.
            logger.warning(f"Code execution exceeded timeout of {timeout}s")
            return {
                "status": "error",
                "message": f"Execution timeout: code did not complete within {timeout} seconds",
                "stdout": stdout_capture.getvalue()[:max_stdout_size]
                if stdout_capture.getvalue()
                else "",
                "stderr": stderr_capture.getvalue()[:max_stderr_size]
                if stderr_capture.getvalue()
                else "",
                "timeout": timeout,
                "warning": "The code may still be running in Houdini. Consider restarting if needed.",
            }

        # Check if there was an exception during execution
        if exec_exception[0] is not None:
            stdout_val = stdout_capture.getvalue()
            stderr_val = stderr_capture.getvalue()
            stdout_val, stdout_truncated = _truncate_output(stdout_val, max_stdout_size)
            stderr_val, stderr_truncated = _truncate_output(stderr_val, max_stderr_size)

            error_result: Dict[str, Any] = {
                "status": "error",
                "message": str(exec_exception[0]),
                "traceback": exec_traceback[0],
                "stdout": stdout_val,
                "stderr": stderr_val,
            }
            if stdout_truncated:
                error_result["stdout_truncated"] = True
            if stderr_truncated:
                error_result["stderr_truncated"] = True
            return error_result

        # 3. Process and truncate outputs if needed
        stdout_val = stdout_capture.getvalue()
        stderr_val = stderr_capture.getvalue()

        stdout_val, stdout_truncated = _truncate_output(stdout_val, max_stdout_size)
        stderr_val, stderr_truncated = _truncate_output(stderr_val, max_stderr_size)

        result: Dict[str, Any] = {"status": "success", "stdout": stdout_val, "stderr": stderr_val}

        # Add truncation flags if applicable
        if stdout_truncated:
            result["stdout_truncated"] = True
            result["stdout_warning"] = f"stdout truncated to {max_stdout_size} bytes"
        if stderr_truncated:
            result["stderr_truncated"] = True
            result["stderr_warning"] = f"stderr truncated to {max_stderr_size} bytes"

        # 4. Capture scene state after execution and compute diff with size limit
        if capture_diff:
            _after_scene = _serialize_scene_state(hou)
            scene_changes = _get_scene_diff(_before_scene, _after_scene)

            # Cap diff size for added_nodes
            diff_truncated = False
            if (
                "added_nodes" in scene_changes
                and len(scene_changes["added_nodes"]) > max_diff_nodes
            ):
                scene_changes["added_nodes"] = scene_changes["added_nodes"][:max_diff_nodes]
                diff_truncated = True

            result["scene_changes"] = scene_changes

            if diff_truncated:
                result["diff_truncated"] = True
                result["diff_warning"] = f"added_nodes truncated to {max_diff_nodes} nodes"

        # Include warnings for dangerous patterns even when allowed
        if dangerous_patterns and allow_dangerous:
            result["dangerous_patterns_executed"] = dangerous_patterns
            result["safety_warning"] = (
                "Code with dangerous patterns was executed with allow_dangerous=True"
            )

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "executing_code")
    except Exception as e:
        logger.error(f"Error executing code: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def get_last_scene_diff() -> Dict[str, Any]:
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
