"""Shared utilities for Houdini MCP tools.

This module contains common utilities used across all tool modules:
- Connection error handling
- Response size management
- JSON serialization helpers
- Dangerous code detection
- Node serialization
"""

import ast
import logging
import re
from typing import Any

from ..connection import (
    DEFAULT_OPERATION_TIMEOUT,
    HoudiniConnectionError,
    disconnect,
    ensure_connected,
    get_connection,
    is_connected,
    quick_health_check,
    safe_execute,
)

# Re-export connection utilities for convenience
__all__ = [
    # Connection utilities
    "ensure_connected",
    "is_connected",
    "get_connection",
    "HoudiniConnectionError",
    "disconnect",
    "safe_execute",
    "quick_health_check",
    "DEFAULT_OPERATION_TIMEOUT",
    # Error handling
    "CONNECTION_ERRORS",
    "_handle_connection_error",
    "handle_connection_errors",  # Decorator for consistent error handling
    # Code safety
    "DANGEROUS_PATTERNS",
    "HEAVY_GEOMETRY_PATTERNS",
    "MUTATION_PATTERNS",
    "_detect_dangerous_code",
    "_detect_heavy_geometry_code",
    "_detect_import_hou",
    "_detect_mutation_code",
    # Output utilities
    "_truncate_output",
    # Response size utilities
    "RESPONSE_SIZE_WARNING_THRESHOLD",
    "RESPONSE_SIZE_LARGE_THRESHOLD",
    "_estimate_response_size",
    "_add_response_metadata",
    # Response pagination and bounds (HDMCP-52 / houdini-mcp-2t6)
    "paginate_list",
    "apply_response_cap",
    "DEFAULT_RESPONSE_CAP_BYTES",
    # Serialization utilities
    "_json_safe_hou_value",
    "_node_to_dict",
    "_serialize_scene_state",
    "_get_scene_diff",
    "_flatten_parm_templates",
    # Parallel execution utilities
    "SEMAPHORE_LIMIT",
    "semaphore_gather",
    "batch_items",
    "run_in_executor",
    # Exceptions
    "ExecutionTimeoutError",
    # Logging
    "logger",
    # Validation helpers
    "validate_resolution",
]

logger = logging.getLogger("houdini_mcp.tools")


# =============================================================================
# Error Handling Decorator
# =============================================================================

import functools
import traceback
from collections.abc import Callable


def handle_connection_errors(operation_name: str) -> Callable:
    """
    Decorator that wraps tool functions with consistent error handling.

    Handles the three-tier error pattern:
    1. HoudiniConnectionError - Returns simple error response
    2. CONNECTION_ERRORS - Calls _handle_connection_error for graceful recovery
    3. Generic Exception - Logs and returns error with traceback

    Args:
        operation_name: Name of the operation (used in error messages)

    Returns:
        Decorated function with error handling

    Example:
        @handle_connection_errors("get_scene_info")
        def get_scene_info(host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
            hou = ensure_connected(host, port)
            # ... actual logic without try/except boilerplate
            return {"status": "success", ...}
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> dict[str, Any]:
            try:
                return func(*args, **kwargs)
            except HoudiniConnectionError as e:
                return {"status": "error", "message": str(e)}
            except CONNECTION_ERRORS as e:
                return _handle_connection_error(e, operation_name)
            except Exception as e:
                logger.error(f"Error during {operation_name}: {e}")
                return {
                    "status": "error",
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                }

        return wrapper

    return decorator


# RPyC and connection-related exceptions that indicate broken/timed-out connections
# These should return graceful error responses, not crash the MCP server
CONNECTION_ERRORS = (
    EOFError,  # Connection closed unexpectedly
    BrokenPipeError,  # Pipe broken
    ConnectionResetError,  # Connection reset by peer
    ConnectionRefusedError,  # Connection refused
    ConnectionAbortedError,  # Connection aborted
    TimeoutError,  # Operation timed out
    OSError,  # Various OS-level connection errors
)


def _handle_connection_error(e: Exception, operation: str) -> dict[str, Any]:
    """
    Handle connection-related errors gracefully.

    Cleans up the broken connection and returns a proper error response.

    Args:
        e: The exception that occurred
        operation: Name of the operation that failed

    Returns:
        Error response dict
    """
    error_type = type(e).__name__
    error_msg = str(e)

    # Clean up the broken connection so next call can reconnect
    try:
        disconnect()
    except Exception:
        pass

    logger.error(f"Connection error during {operation}: {error_type}: {error_msg}")

    # Provide helpful messages based on error type
    if isinstance(e, TimeoutError):
        message = (
            f"Operation '{operation}' timed out. Houdini may be busy with a heavy computation. "
            "The connection has been reset - subsequent calls will reconnect automatically."
        )
    elif isinstance(e, EOFError):
        message = (
            f"Connection to Houdini closed unexpectedly during '{operation}'. "
            "Houdini may have crashed or the RPC server stopped. "
            "The connection has been reset - subsequent calls will attempt to reconnect."
        )
    elif isinstance(e, (BrokenPipeError, ConnectionResetError)):
        message = (
            f"Connection to Houdini was lost during '{operation}'. "
            "The connection has been reset - subsequent calls will reconnect automatically."
        )
    else:
        message = (
            f"Connection error during '{operation}': {error_type}: {error_msg}. "
            "The connection has been reset - subsequent calls will reconnect automatically."
        )

    return {
        "status": "error",
        "error_type": "connection_error",
        "exception": error_type,
        "message": message,
        "operation": operation,
        "recoverable": True,
    }


# =============================================================================
# Validation Helpers
# =============================================================================


def validate_resolution(
    resolution: list[int],
    min_size: int = 64,
    max_size: int = 4096,
) -> dict[str, Any] | None:
    """
    Validate render resolution dimensions.

    Returns an error dict if validation fails, None if valid.

    Args:
        resolution: [width, height] in pixels
        min_size: Minimum dimension size (default: 64)
        max_size: Maximum dimension size (default: 4096)

    Returns:
        None if valid, error dict if invalid

    Example:
        if error := validate_resolution(resolution):
            return error
        # Continue with valid resolution...
    """
    width, height = resolution[0], resolution[1]
    if width < min_size or height < min_size:
        return {"status": "error", "message": f"Resolution must be at least {min_size}x{min_size}"}
    if width > max_size or height > max_size:
        return {"status": "error", "message": f"Resolution cannot exceed {max_size}x{max_size}"}
    return None


# Dangerous code patterns for safety scanning
# Note: patterns tolerate arbitrary whitespace around ``.`` and ``(`` so that
# trivial obfuscation (``hou . exit ( )``) cannot slip past the scanner.
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\bhou\s*\.\s*exit\s*\(", "hou.exit() - will close Houdini"),
    (r"\bos\s*\.\s*remove\s*\(", "os.remove() - file deletion"),
    (r"\bos\s*\.\s*unlink\s*\(", "os.unlink() - file deletion"),
    (r"\bos\s*\.\s*rmdir\s*\(", "os.rmdir() - directory deletion"),
    (r"\bshutil\s*\.\s*rmtree\s*\(", "shutil.rmtree() - directory deletion"),
    (r"\bshutil\s*\.\s*move\s*\(", "shutil.move() - file move/overwrite"),
    (r"\bsubprocess\b", "subprocess - shell execution"),
    (r"\bos\s*\.\s*system\s*\(", "os.system() - shell execution"),
    (r"\bos\s*\.\s*popen\s*\(", "os.popen() - shell execution"),
    (r"\bos\s*\.\s*exec[lv]", "os.exec*() - process replacement"),
    (r"\bos\s*\.\s*kill\s*\(", "os.kill() - signal a process"),
    (r"\bpty\s*\.\s*spawn\s*\(", "pty.spawn() - shell execution"),
    (r'\bopen\s*\([^)]*["\'][wax]', "open() with write mode - file writing"),
    (r"\bhou\s*\.\s*hipFile\s*\.\s*clear\s*\(", "hou.hipFile.clear() - scene wipe"),
    # Dynamic execution primitives (common evasion vectors).
    # Standalone builtin eval only; Houdini's safe parameter read `.eval()` is
    # an ordinary method call and must remain usable under normal policy.
    (r"(?<![.\w])eval\s*\(", "eval() - dynamic code execution"),
    (r"\bexec\s*\(", "exec() - dynamic code execution"),
    (r"\bcompile\s*\(", "compile() - dynamic code compilation"),
    (r"\b__import__\s*\(", "__import__() - dynamic import (evasion vector)"),
    (r"\bgetattr\s*\(\s*__builtins__", "getattr(__builtins__ ...) - builtins evasion"),
    # Network egress: exfiltration / remote control risk.
    (r"\b(?:import\s+socket\b|from\s+socket\s+import\b)", "socket - raw network access"),
    (r"\bsocket\s*\.\s*socket\s*\(", "socket.socket() - raw network access"),
    (
        r"\b(?:import\s+requests\b|from\s+requests\s+import\b)",
        "requests - HTTP network access",
    ),
    (r"\brequests\s*\.\s*(get|post|put|delete|request)\s*\(", "requests.* - HTTP network access"),
    (r"\b(?:import\s+urllib\b|from\s+urllib(?:\.\w+)?\s+import\b)", "urllib - HTTP network access"),
    (r"\burllib\b", "urllib - HTTP network access"),
    (r"\bimport\s+http\b", "http - HTTP network access"),
    (r"\bfrom\s+http\b", "http - HTTP network access"),
    (r"\bhttp\s*\.\s*client\b", "http.client - HTTP network access"),
    (r"\b(?:import\s+ftplib\b|from\s+ftplib\s+import\b)", "ftplib - FTP network access"),
]


HEAVY_GEOMETRY_PATTERNS: list[tuple[str, str]] = [
    (
        r"\.geometry\s*\(",
        "node.geometry() - can force a heavy SOP cook and destabilize Houdini",
    ),
    (
        r"\.points\s*\(",
        "geo.points() - can materialize/iterate large point arrays",
    ),
    (
        r"\.prims\s*\(",
        "geo.prims() - can materialize/iterate large primitive arrays",
    ),
    (
        r"\.vertices\s*\(",
        "geo.vertices() - can materialize/iterate large vertex arrays",
    ),
    (
        r"\.iterPoints\s*\(",
        "geo.iterPoints() - can iterate large point arrays",
    ),
    (
        r"\.iterPrims\s*\(",
        "geo.iterPrims() - can iterate large primitive arrays",
    ),
]


def _detect_dangerous_code(code: str) -> list[str]:
    """Scan code for dangerous operations, including imported aliases."""
    detected: list[str] = []
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            detected.append(description)

    # Regexes are useful for malformed/dynamic source, while AST inspection
    # closes ordinary alias forms such as `from os import remove; remove(...)`.
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return list(dict.fromkeys(detected))

    dangerous_from_imports = {
        "os": {"remove", "unlink", "rmdir", "system", "popen", "kill"},
        "shutil": {"rmtree", "move"},
        "subprocess": {"run", "call", "Popen", "check_call", "check_output"},
        "requests": {"get", "post", "put", "delete", "request"},
        "urllib.request": {"urlopen", "Request"},
        "socket": {"socket", "create_connection"},
        "ftplib": {"FTP", "FTP_TLS"},
    }
    imported_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in dangerous_from_imports:
            for alias in node.names:
                if alias.name in dangerous_from_imports[node.module]:
                    imported_aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in imported_aliases:
                detected.append(
                    f"{imported_aliases[node.func.id]}() - imported dangerous operation"
                )
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "builtins"
                and node.func.attr in {"eval", "exec", "compile", "__import__"}
            ):
                detected.append(f"builtins.{node.func.attr}() - dynamic code execution")
    return list(dict.fromkeys(detected))


def _detect_heavy_geometry_code(code: str) -> list[str]:
    """
    Scan code for geometry access patterns that can cook or iterate very large SOP data.

    These are not inherently destructive, but in production Houdini scenes they can
    block the UI, drop the RPC connection, or crash Houdini. Prefer dedicated
    summary tools that run bounded analysis on the Houdini side.
    """
    detected: list[str] = []
    for pattern, description in HEAVY_GEOMETRY_PATTERNS:
        if re.search(pattern, code):
            detected.append(description)
    return detected


def _detect_import_hou(code: str) -> bool:
    """
    Detect if code tries to import hou module.

    The execute_code tool pre-injects hou as a global via RPyC, so importing
    it as a module will fail with ModuleNotFoundError. This is a common mistake
    for users familiar with running Python inside Houdini.

    Args:
        code: Python code to scan

    Returns:
        True if code contains import hou or from hou import patterns
    """
    # Match "import hou" or "from hou import ..."
    import_patterns = [
        r"^\s*import\s+hou\s*(?:$|#|;|,|\s)",
        r"^\s*from\s+hou\s+import\s+",
    ]
    return any(re.search(pattern, code, re.MULTILINE) for pattern in import_patterns)


# Scene-mutation patterns. These are perfectly legal under the ``normal`` and
# ``privileged`` policies, but forbidden under ``read-only`` where the caller has
# declared they only intend to inspect the scene.
MUTATION_PATTERNS: list[tuple[str, str]] = [
    (r"\.\s*createNode\s*\(", "createNode() - creates a node"),
    (r"\.\s*createOutputNode\s*\(", "createOutputNode() - creates a node"),
    (r"\.copyTo\s*\(", "copyTo() - copies nodes"),
    (r"\.destroy\s*\(", "destroy() - deletes a node"),
    (r"\.deleteItems\s*\(", "deleteItems() - deletes nodes"),
    (r"\.setInput\s*\(", "setInput() - rewires a node"),
    (r"\.setFirstInput\s*\(", "setFirstInput() - rewires a node"),
    (r"\.setNamedInput\s*\(", "setNamedInput() - rewires a node"),
    (r"\.\s*parm\s*\([^)]*\)\s*\.\s*set\s*\(", "parm().set() - mutates a parameter"),
    (
        r"\.\s*parmTuple\s*\([^)]*\)\s*\.\s*set\s*\(",
        "parmTuple().set() - mutates a parameter",
    ),
    (r"\.setParms\s*\(", "setParms() - mutates parameters"),
    (r"\.setName\s*\(", "setName() - renames a node"),
    (r"\.setColor\s*\(", "setColor() - mutates node appearance"),
    (r"\.setDisplayFlag\s*\(", "setDisplayFlag() - mutates node flags"),
    (r"\.setRenderFlag\s*\(", "setRenderFlag() - mutates node flags"),
    (r"\.setBypass\s*\(", "setBypass() - mutates node flags"),
    (r"\bhou\s*\.\s*hipFile\s*\.\s*(save|load|clear|merge|new)\s*\(", "hou.hipFile mutation"),
    (r"\.save\s*\(", "save() - writes to disk"),
]


def _detect_mutation_code(code: str) -> list[str]:
    """Scan scene mutations using regex fallback plus AST call semantics."""
    detected: list[str] = []
    for pattern, description in MUTATION_PATTERNS:
        if re.search(pattern, code):
            detected.append(description)
    detected.extend(_detect_dangerous_code(code))

    # Method names are semantic regardless of whitespace or aliases (`p.set`).
    mutation_methods = {
        "createNode",
        "createOutputNode",
        "copyTo",
        "destroy",
        "deleteItems",
        "setInput",
        "setFirstInput",
        "setNamedInput",
        "set",
        "setParms",
        "setName",
        "setColor",
        "setDisplayFlag",
        "setRenderFlag",
        "setBypass",
        "setPosition",
        "layoutChildren",
        "createNetworkBox",
        "addNode",
        "save",
    }
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return list(dict.fromkeys(detected))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in mutation_methods:
            detected.append(f"{node.func.attr}() - scene mutation")
        if (
            node.func.attr == "hscript"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "hou"
        ):
            # HScript is a command language; read-only fails closed instead of
            # attempting an incomplete allowlist of non-mutating commands.
            detected.append("hou.hscript() - command may mutate scene")
    return list(dict.fromkeys(detected))


def _truncate_output(output: str, max_size: int) -> tuple[str, bool]:
    """
    Truncate output if it exceeds max_size.

    Args:
        output: The output string to potentially truncate
        max_size: Maximum allowed size in bytes

    Returns:
        Tuple of (truncated_output, was_truncated)
    """
    if len(output) > max_size:
        truncated = output[:max_size]
        return truncated, True
    return output, False


# Response size thresholds (in bytes)
RESPONSE_SIZE_WARNING_THRESHOLD = 100 * 1024  # 100KB - warn above this
RESPONSE_SIZE_LARGE_THRESHOLD = 500 * 1024  # 500KB - considered large

# Hard response cap for bounded responses (HDMCP-52 / houdini-mcp-2t6)
DEFAULT_RESPONSE_CAP_BYTES = 16 * 1024  # 16KB default cap


def _estimate_response_size(data: Any, _depth: int = 0) -> int:
    """
    Estimate the JSON-serialized size of a response without full serialization.

    Uses a fast recursive estimation that avoids the overhead of actually
    serializing the entire structure to JSON (which would be done again
    by the MCP framework anyway).

    Args:
        data: The data structure to estimate size for
        _depth: Internal recursion depth counter

    Returns:
        Estimated size in bytes
    """
    # Prevent infinite recursion
    if _depth > 50:
        return 20

    if data is None:
        return 4  # "null"
    if isinstance(data, bool):
        return 5  # "true" or "false"
    if isinstance(data, int):
        return len(str(data))
    if isinstance(data, float):
        return len(str(data)) + 2  # Account for possible scientific notation
    if isinstance(data, str):
        return len(data) + 2  # quotes

    if isinstance(data, dict):
        # {"key": value, ...} - estimate key/value pairs + overhead
        size = 2  # {}
        for k, v in data.items():
            size += len(str(k)) + 4  # "key": + comma
            size += _estimate_response_size(v, _depth + 1)
        return size

    if isinstance(data, (list, tuple)):
        # [item, item, ...] - estimate items + overhead
        size = 2  # []
        for item in data:
            size += _estimate_response_size(item, _depth + 1) + 1  # comma
        return size

    # Fallback for other types
    return len(str(data)) + 2


def _serialized_size(data: Any) -> int:
    """Return the exact UTF-8 byte size used by MCP JSON serialization."""
    import json

    return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _set_final_serialized_size(result: dict[str, Any]) -> None:
    """Set self-referential size metadata to its exact fixed-point value."""
    # The field's decimal digit count can change the size it reports. The value
    # converges in a handful of iterations because only that digit count varies.
    size = 0
    for _ in range(8):
        result["truncated_size_bytes"] = size
        measured = _serialized_size(result)
        if measured == size:
            return
        size = measured
    result["truncated_size_bytes"] = _serialized_size(result)


def _add_response_metadata(
    result: dict[str, Any],
    include_size: bool = True,
    apply_cap: bool = True,
    max_bytes: int = DEFAULT_RESPONSE_CAP_BYTES,
) -> dict[str, Any]:
    """
    Add response metadata including size information and apply hard cap.

    This is the single shared response finalization boundary for all production tools.
    It ensures no response exceeds the configured cap after JSON serialization.

    Args:
        result: The result dictionary to augment
        include_size: Whether to include size metadata
        apply_cap: Whether to apply hard response cap (default: True)
        max_bytes: Maximum bytes after JSON serialization (default: DEFAULT_RESPONSE_CAP_BYTES)

    Returns:
        The result dictionary with added metadata and applied cap
    """
    if not include_size:
        if apply_cap:
            return apply_response_cap(result, max_bytes=max_bytes)
        return result

    # Apply the cap to the payload first so oversized collections retain a
    # useful bounded prefix plus continuation metadata.
    if apply_cap:
        result = apply_response_cap(result, max_bytes=max_bytes)
        if result.get("_truncated"):
            return result

    # Add observability metadata for responses that did not require truncation.
    # This metadata itself consumes bytes, so run the final object through the
    # cap once more; otherwise a payload just below the boundary can become an
    # over-cap response after `_response_size_bytes` is inserted.
    size_bytes = _serialized_size(result)
    result["_response_size_bytes"] = size_bytes

    if size_bytes > RESPONSE_SIZE_LARGE_THRESHOLD:
        result["_response_size_warning"] = (
            f"Large response ({size_bytes // 1024}KB). "
            "Consider using compact=True, reducing max_results, or adding filters."
        )
    elif size_bytes > RESPONSE_SIZE_WARNING_THRESHOLD:
        result["_response_size_note"] = f"Response size: {size_bytes // 1024}KB"

    return apply_response_cap(result, max_bytes=max_bytes) if apply_cap else result


def _json_safe_hou_value(
    hou: Any, value: Any, *, max_depth: int = 10, _seen: set[int] | None = None
) -> Any:
    """Convert Houdini (hou) values into JSON-serializable structures."""
    if max_depth <= 0:
        return str(value)

    if _seen is None:
        _seen = set()

    # Prevent infinite recursion
    try:
        value_id = id(value)
        if value_id in _seen:
            return "<recursion>"
        _seen.add(value_id)
    except Exception:
        pass

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", errors="replace")

    if isinstance(value, (list, tuple, set)):
        return [_json_safe_hou_value(hou, v, max_depth=max_depth - 1, _seen=_seen) for v in value]

    if isinstance(value, dict):
        return {
            str(k): _json_safe_hou_value(hou, v, max_depth=max_depth - 1, _seen=_seen)
            for k, v in value.items()
        }

    # Common hou objects (Node, Parm, etc.)
    path_attr = getattr(value, "path", None)
    if callable(path_attr):
        try:
            path = path_attr()
            if isinstance(path, str):
                return path
        except Exception:
            pass

    # Ramp parameters are a common source of non-serializable values.
    try:
        if hasattr(hou, "Ramp") and isinstance(value, hou.Ramp):
            try:
                basis = list(value.basis())
            except Exception:
                basis = []

            try:
                keys = list(value.keys())
            except Exception:
                keys = []

            try:
                values = list(value.values())
            except Exception:
                values = []

            return {
                "type": "hou.Ramp",
                "basis": [
                    _json_safe_hou_value(hou, b, max_depth=max_depth - 1, _seen=_seen)
                    for b in basis
                ],
                "keys": [
                    _json_safe_hou_value(hou, k, max_depth=max_depth - 1, _seen=_seen) for k in keys
                ],
                "values": [
                    _json_safe_hou_value(hou, v, max_depth=max_depth - 1, _seen=_seen)
                    for v in values
                ],
            }
    except Exception:
        pass

    try:
        module_name = type(value).__module__
        type_name = type(value).__name__

        if module_name.startswith("hou"):
            if type_name in {"Vector2", "Vector3", "Vector4", "Color"}:
                try:
                    return [float(x) for x in value]
                except Exception:
                    pass

            if type_name == "EnumValue":
                try:
                    name = value.name()
                    if isinstance(name, str):
                        return name
                except Exception:
                    pass
    except Exception:
        pass

    # Fallback: represent as string instead of throwing
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


class ExecutionTimeoutError(Exception):
    """Raised when code execution exceeds the timeout."""

    pass


def _node_to_dict(
    node: Any, include_params: bool = True, max_params: int = 100, hou: Any = None
) -> dict[str, Any]:
    """
    Serialize a node to a dictionary.

    Args:
        node: Houdini node object
        include_params: Whether to include parameter values
        max_params: Maximum number of parameters to include
        hou: The hou module (optional, for value conversion)

    Returns:
        Dict representation of the node
    """
    result: dict[str, Any] = {
        "path": node.path(),
        "type": node.type().name(),
        "name": node.name(),
    }

    if hou is None:
        hou = type("_HouSentinel", (), {})()

    if include_params:
        params: dict[str, Any] = {}
        for i, parm in enumerate(node.parms()):
            if i >= max_params:
                break
            try:
                params[parm.name()] = _json_safe_hou_value(hou, parm.eval())
            except Exception:
                params[parm.name()] = "<unevaluable>"
        result["parameters"] = params

    # Recursively serialize children
    result["children"] = [
        _node_to_dict(
            child, include_params=False, hou=hou
        )  # Don't include params for children to reduce size
        for child in node.children()
    ]

    return result


def _serialize_scene_state(hou: Any, root_path: str = "/obj") -> list[dict[str, Any]]:
    """
    Serialize the scene state for comparison.

    Uses hscript commands for fast path enumeration (800x faster than
    per-node RPC calls), falling back to the slow method for mocks.

    Args:
        hou: The hou module
        root_path: Root node path to serialize from

    Returns:
        List of node dictionaries with path, type, name, children
    """
    # Try fast hscript-based approach first (works with real Houdini)
    try:
        if hasattr(hou, "hscript"):
            return _serialize_scene_state_fast(hou, root_path)
    except Exception as e:
        logger.debug(f"Fast serialization failed, using fallback: {e}")

    # Fallback for mocks or if hscript fails
    obj = hou.node(root_path)
    if obj is None:
        return []
    return [_node_to_dict(child, hou=hou) for child in obj.children()]


def _serialize_scene_state_fast(hou: Any, root_path: str = "/obj") -> list[dict[str, Any]]:
    """
    Fast scene serialization using hscript commands.

    This avoids per-node RPC calls by using hscript to get all paths
    and types in bulk operations. ~800x faster than per-node RPC.

    Args:
        hou: The hou module (must have hscript method)
        root_path: Root node path to serialize from

    Returns:
        List of node dictionaries with path, name, type, children
    """
    # Use the dedicated hscript module for fast operations
    from .hscript import HscriptBatch

    batch = HscriptBatch(hou)
    return batch.get_scene_tree(root_path)


def _get_scene_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compare scene states and return the differences.

    Args:
        before: Scene state before operation
        after: Scene state after operation

    Returns:
        Dict with added, removed, and modified nodes
    """
    before_paths: set[str] = {node["path"] for node in before}
    after_paths: set[str] = {node["path"] for node in after}

    added = after_paths - before_paths
    removed = before_paths - after_paths

    # Find modified nodes (same path but different content)
    modified: list[str] = []
    before_by_path = {node["path"]: node for node in before}
    after_by_path = {node["path"]: node for node in after}

    for path in before_paths & after_paths:
        if before_by_path[path] != after_by_path[path]:
            modified.append(path)

    return {
        "added": list(added),
        "removed": list(removed),
        "modified": modified,
        "added_nodes": [n for n in after if n["path"] in added],
        "has_changes": bool(added or removed or modified),
    }


def _flatten_parm_templates(hou: Any, parm_templates: list[Any], max_depth: int = 20) -> list[Any]:
    """
    Flatten nested parameter templates into a single list.

    Args:
        hou: The hou module
        parm_templates: List of parameter templates to flatten
        max_depth: Maximum recursion depth

    Returns:
        Flattened list of parameter templates
    """
    flattened: list[Any] = []

    def walk(templates: list[Any], depth: int) -> None:
        if depth > max_depth:
            return

        for template in templates:
            try:
                template_type = template.type()
            except Exception:
                template_type = None

            is_folder_like = False
            try:
                is_folder_like = template_type in (
                    hou.parmTemplateType.Folder,
                    hou.parmTemplateType.FolderSet,
                )
            except Exception:
                is_folder_like = False

            is_multiparm = False
            try:
                is_multiparm = template_type in (
                    hou.parmTemplateType.MultiParmBlock,
                    hou.parmTemplateType.MultiParm,
                )
            except Exception:
                is_multiparm = False

            flattened.append(template)

            if (is_folder_like or is_multiparm) and hasattr(template, "parmTemplates"):
                try:
                    child_templates = list(template.parmTemplates())
                except Exception:
                    child_templates = []
                walk(child_templates, depth + 1)

    walk(parm_templates, 0)

    # De-dup while preserving order (folders can appear in multiple lists)
    seen_ids: set[int] = set()
    unique: list[Any] = []
    for template in flattened:
        template_id = id(template)
        if template_id in seen_ids:
            continue
        seen_ids.add(template_id)
        unique.append(template)

    return unique


# =============================================================================
# Parallel Execution Utilities
# =============================================================================

import asyncio
import os
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")

# Default semaphore limit for bounded parallel execution
# Can be overridden via environment variable
SEMAPHORE_LIMIT = int(os.getenv("HOUDINI_MCP_SEMAPHORE_LIMIT", "10"))


async def semaphore_gather(
    *coroutines: Coroutine[Any, Any, T],
    max_concurrent: int | None = None,
    return_exceptions: bool = False,
) -> list[Any]:
    """
    Execute coroutines with bounded concurrency using a semaphore.

    Prevents overwhelming Houdini with too many concurrent operations.
    This is critical for batch operations like creating many nodes or
    setting many parameters simultaneously.

    Args:
        *coroutines: Variable number of coroutines to execute
        max_concurrent: Maximum concurrent executions (default: SEMAPHORE_LIMIT)
        return_exceptions: If True, exceptions are returned instead of raised

    Returns:
        List of results in the same order as input coroutines

    Example:
        # Create 100 nodes with max 10 concurrent operations
        results = await semaphore_gather(
            *[create_node_async(f"node_{i}") for i in range(100)],
            max_concurrent=10
        )
    """
    limit = max_concurrent or SEMAPHORE_LIMIT
    semaphore = asyncio.Semaphore(limit)

    async def _bounded_execute(coro: Coroutine[Any, Any, T]) -> T:
        async with semaphore:
            return await coro

    results = await asyncio.gather(
        *(_bounded_execute(c) for c in coroutines), return_exceptions=return_exceptions
    )
    return list(results)


def batch_items(items: list[Any], batch_size: int) -> list[list[Any]]:
    """
    Split a list into batches of specified size.

    Useful for breaking up large operations into manageable chunks
    that can be processed sequentially or in parallel.

    Args:
        items: List of items to batch
        batch_size: Maximum size of each batch

    Returns:
        List of batches (each batch is a list)

    Example:
        nodes = ["node1", "node2", "node3", "node4", "node5"]
        batches = batch_items(nodes, 2)
        # Returns: [["node1", "node2"], ["node3", "node4"], ["node5"]]
    """
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


async def run_in_executor(func: Any, *args: Any, **kwargs: Any) -> Any:
    """
    Run a synchronous function in a thread pool executor.

    Useful for wrapping blocking Houdini RPC calls in async context.

    Args:
        func: Synchronous function to execute
        *args: Positional arguments for the function
        **kwargs: Keyword arguments for the function

    Returns:
        Result of the function

    Example:
        result = await run_in_executor(sync_houdini_operation, param1, param2)
    """
    import functools

    loop = asyncio.get_event_loop()
    partial_func = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(None, partial_func)


# =============================================================================
# Response Pagination and Bounds (HDMCP-52 / houdini-mcp-2t6)
# =============================================================================


def paginate_list(
    items: list[Any],
    limit: int = 20,
    cursor: int | None = None,
) -> dict[str, Any]:
    """
    Paginate a list with limit/cursor controls.

    Args:
        items: List to paginate
        limit: Maximum items per page (default: 20)
        cursor: Start offset for pagination (default: 0)

    Returns:
        Dict with:
        - items: Page of items
        - total: Total number of items
        - returned: Number of items in this page
        - has_more: Whether more pages exist
        - cursor: Next cursor if has_more, otherwise omitted

    Example:
        result = paginate_list(nodes, limit=10, cursor=0)
        # Returns first 10 nodes with cursor=10 if more exist
    """
    # Clamp invalid inputs so callers cannot receive a repeating cursor (for
    # example limit=0, cursor=0 forever) or negative Python-slice semantics.
    limit = max(1, int(limit))
    offset = max(0, int(cursor)) if cursor is not None else 0
    total = len(items)

    # Slice the page
    page = items[offset : offset + limit]
    returned = len(page)

    # Check if more pages exist
    has_more = (offset + returned) < total

    result: dict[str, Any] = {
        "items": page,
        "total": total,
        "returned": returned,
        "has_more": has_more,
    }

    # Add cursor for next page if more exist
    if has_more:
        result["cursor"] = offset + returned

    return result


def apply_response_cap(
    data: dict[str, Any],
    max_bytes: int = DEFAULT_RESPONSE_CAP_BYTES,
) -> dict[str, Any]:
    """
    Apply hard response size cap with JSON-safe truncation.

    Ensures response never exceeds max_bytes after JSON serialization.
    Truncated responses retain a useful bounded prefix/page plus continuation
    and truncation metadata, not just metadata-only.

    Args:
        data: Response dict to cap
        max_bytes: Maximum bytes after JSON serialization

    Returns:
        Dict that serializes to <= max_bytes with truncation metadata if needed

    Example:
        result = apply_response_cap(large_response, max_bytes=16000)
        # Result JSON is guaranteed <= 16KB, preserves useful data
    """
    import json

    # Serialize to measure size
    try:
        json_str = json.dumps(data, ensure_ascii=False)
        json_bytes = json_str.encode("utf-8")
        original_size = len(json_bytes)
    except Exception:
        # If can't serialize, return error metadata
        return {
            "status": "error",
            "message": "Response serialization failed",
            "_truncated": True,
        }

    # If under cap, return as-is
    if original_size <= max_bytes:
        return data

    # Need to truncate - preserve status and essential fields first
    result: dict[str, Any] = {
        "_truncated": True,
        "original_size_bytes": original_size,
    }

    # Preserve status if present
    if "status" in data:
        result["status"] = data["status"]

    # Preserve essential metadata fields (small, informative)
    essential_fields = [
        "node_path",
        "root_path",
        "path",
        "type",
        "name",
        "total",
        "returned",
        "has_more",
        "cursor",
        "count",
        "pattern",
        "category",
        "cook_state",
        "point_count",
        "primitive_count",
        "vertex_count",
        "warning",
        "message",
    ]
    for field in essential_fields:
        if field in data:
            result[field] = data[field]

    # Try to preserve data fields (arrays, nested objects) within budget
    data_fields = [
        ("items", "item"),
        ("children", "child"),
        ("matches", "match"),
        ("node_types", "node_type"),
        ("parameters", "parameter"),
        ("sample_points", "sample_point"),
        ("attributes", "attribute"),
        ("groups", "group"),
    ]

    for field_name, _singular_name in data_fields:
        if field_name not in data:
            continue

        field_value = data[field_name]

        if isinstance(field_value, list) and len(field_value) > 0:
            # Find the longest useful prefix together with ALL truncation/size
            # metadata. Serialized size is monotonic with prefix length, so a
            # binary search avoids the old O(n²) repeated-growing-list cost on
            # responses containing tens of thousands of items.
            def prefix_candidate(
                count: int,
                *,
                name: str = field_name,
                values: list[Any] = field_value,
            ) -> dict[str, Any]:
                candidate = dict(result)
                candidate[name] = values[:count]
                candidate[f"{name}_truncated"] = True
                candidate[f"{name}_original_count"] = len(values)
                candidate[f"{name}_preserved_count"] = count
                _set_final_serialized_size(candidate)
                return candidate

            low, high, best = 1, len(field_value), 0
            while low <= high:
                midpoint = (low + high) // 2
                try:
                    if _serialized_size(prefix_candidate(midpoint)) <= max_bytes:
                        best = midpoint
                        low = midpoint + 1
                    else:
                        high = midpoint - 1
                except Exception:
                    high = midpoint - 1

            if best:
                result[field_name] = field_value[:best]
                result[f"{field_name}_truncated"] = True
                result[f"{field_name}_original_count"] = len(field_value)
                result[f"{field_name}_preserved_count"] = best
        elif isinstance(field_value, dict):
            # Try to include the dict if it fits
            try:
                test_result = dict(result)
                test_result[field_name] = field_value
                test_json = json.dumps(test_result, ensure_ascii=False)
                test_size = len(test_json.encode("utf-8"))
                if test_size <= max_bytes - 50:
                    result[field_name] = field_value
            except Exception:
                pass

    # Add exact final size metadata (including the field itself).
    _set_final_serialized_size(result)

    # Ensure the final object, metadata included, is actually under the cap.
    if _serialized_size(result) > max_bytes:
        # Need to be more aggressive - remove data fields and keep only metadata
        minimal = {
            "_truncated": True,
            "original_size_bytes": original_size,
            "message": f"Response too large ({original_size} bytes), truncated to fit {max_bytes} bytes",
        }
        if "status" in data:
            minimal["status"] = data["status"]

        # Try to preserve essential fields
        for field in essential_fields:
            if field in data:
                try:
                    test_minimal = dict(minimal)
                    test_minimal[field] = data[field]
                    test_json = json.dumps(test_minimal, ensure_ascii=False)
                    if len(test_json.encode("utf-8")) <= max_bytes:
                        minimal[field] = data[field]
                except Exception:
                    pass

        # Add exact final size metadata for the minimal fallback too.
        _set_final_serialized_size(minimal)

        return minimal

    return result


# NOTE: apply_detail_mode was removed as it was not wired to production tools.
# The PR scope is narrowed to focus on hard caps and pagination only.
# Compact mode is available via the compact=True parameter on individual tools
# (e.g., get_node_info, list_children) which directly control response verbosity.
