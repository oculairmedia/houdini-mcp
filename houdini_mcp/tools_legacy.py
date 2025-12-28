"""Houdini MCP Tools - Functions exposed via MCP protocol."""

import logging
import re
import traceback
import signal
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from functools import wraps

from .connection import (
    ensure_connected,
    is_connected,
    HoudiniConnectionError,
    disconnect,
    safe_execute,
    quick_health_check,
    DEFAULT_OPERATION_TIMEOUT,
)

logger = logging.getLogger("houdini_mcp.tools")


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


def _handle_connection_error(e: Exception, operation: str) -> Dict[str, Any]:
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


# Dangerous code patterns for safety scanning
DANGEROUS_PATTERNS: List[Tuple[str, str]] = [
    (r"\bhou\.exit\s*\(", "hou.exit() - will close Houdini"),
    (r"\bos\.remove\s*\(", "os.remove() - file deletion"),
    (r"\bos\.unlink\s*\(", "os.unlink() - file deletion"),
    (r"\bshutil\.rmtree\s*\(", "shutil.rmtree() - directory deletion"),
    (r"\bsubprocess\b", "subprocess - shell execution"),
    (r"\bos\.system\s*\(", "os.system() - shell execution"),
    (r'\bopen\s*\([^)]*["\'][wa]', "open() with write mode - file writing"),
    (r"\bhou\.hipFile\.clear\s*\(", "hou.hipFile.clear() - scene wipe"),
]


def _detect_dangerous_code(code: str) -> List[str]:
    """
    Scan code for potentially dangerous patterns.

    Args:
        code: Python code to scan

    Returns:
        List of detected dangerous pattern descriptions
    """
    detected: List[str] = []
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            detected.append(description)
    return detected


def _truncate_output(output: str, max_size: int) -> Tuple[str, bool]:
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


def _estimate_response_size(data: Any) -> int:
    """
    Estimate the JSON-serialized size of a response.

    Args:
        data: The data structure to estimate size for

    Returns:
        Estimated size in bytes
    """
    import json

    try:
        return len(json.dumps(data))
    except (TypeError, ValueError):
        # Fallback: rough estimate based on str representation
        return len(str(data))


def _add_response_metadata(result: Dict[str, Any], include_size: bool = True) -> Dict[str, Any]:
    """
    Add response metadata including size information.

    Args:
        result: The result dictionary to augment
        include_size: Whether to include size metadata

    Returns:
        The result dictionary with added metadata
    """
    if not include_size:
        return result

    size_bytes = _estimate_response_size(result)
    result["_response_size_bytes"] = size_bytes

    if size_bytes > RESPONSE_SIZE_LARGE_THRESHOLD:
        result["_response_size_warning"] = (
            f"Large response ({size_bytes // 1024}KB). "
            "Consider using compact=True, reducing max_results, or adding filters."
        )
    elif size_bytes > RESPONSE_SIZE_WARNING_THRESHOLD:
        result["_response_size_note"] = f"Response size: {size_bytes // 1024}KB"

    return result


def _json_safe_hou_value(
    hou: Any, value: Any, *, max_depth: int = 10, _seen: Optional[Set[int]] = None
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


# Scene state for before/after comparisons (ported from OpenWebUI pipeline)
_before_scene: List[Dict[str, Any]] = []
_after_scene: List[Dict[str, Any]] = []


def _node_to_dict(
    node: Any, include_params: bool = True, max_params: int = 100, hou: Any = None
) -> Dict[str, Any]:
    """
    Serialize a node to a dictionary (ported from OpenWebUI pipeline).

    Args:
        node: Houdini node object
        include_params: Whether to include parameter values
        max_params: Maximum number of parameters to include

    Returns:
        Dict representation of the node
    """
    result: Dict[str, Any] = {
        "path": node.path(),
        "type": node.type().name(),
        "name": node.name(),
    }

    if hou is None:
        hou = type("_HouSentinel", (), {})()

    if include_params:
        params: Dict[str, Any] = {}
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


def _serialize_scene_state(hou: Any, root_path: str = "/obj") -> List[Dict[str, Any]]:
    """
    Serialize the scene state for comparison (from OpenWebUI pipeline).

    Args:
        hou: The hou module
        root_path: Root node path to serialize from

    Returns:
        List of node dictionaries
    """
    obj = hou.node(root_path)
    if obj is None:
        return []
    return [_node_to_dict(child, hou=hou) for child in obj.children()]


def _get_scene_diff(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compare scene states and return the differences.

    Args:
        before: Scene state before operation
        after: Scene state after operation

    Returns:
        Dict with added, removed, and modified nodes
    """
    before_paths: Set[str] = {node["path"] for node in before}
    after_paths: Set[str] = {node["path"] for node in after}

    added = after_paths - before_paths
    removed = before_paths - after_paths

    # Find modified nodes (same path but different content)
    modified: List[str] = []
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


def get_scene_info(host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
    """
    Get current Houdini scene information.

    Returns:
        Dict with scene information including file path, nodes, and Houdini version.
    """
    try:
        hou = ensure_connected(host, port)

        hip_file = hou.hipFile.path()
        obj_node = hou.node("/obj")

        nodes: List[Dict[str, Any]] = []
        if obj_node:
            for child in obj_node.children():
                nodes.append(
                    {"path": child.path(), "type": child.type().name(), "name": child.name()}
                )

        return {
            "status": "success",
            "hip_file": hip_file if hip_file else "untitled.hip",
            "houdini_version": hou.applicationVersionString(),
            "node_count": len(nodes),
            "nodes": nodes,
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "get_scene_info")
    except Exception as e:
        logger.error(f"Error getting scene info: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def create_node(
    node_type: str,
    parent_path: str = "/obj",
    name: Optional[str] = None,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Create a new node in the Houdini scene.

    Args:
        node_type: The type of node to create (e.g., "geo", "sphere", "box")
        parent_path: The parent node path (default: "/obj")
        name: Optional name for the new node

    Returns:
        Dict with created node information.
    """
    try:
        hou = ensure_connected(host, port)

        parent = hou.node(parent_path)
        if parent is None:
            return {"status": "error", "message": f"Parent node not found: {parent_path}"}

        if name:
            node = parent.createNode(node_type, name)
        else:
            node = parent.createNode(node_type)

        return {
            "status": "success",
            "node_path": node.path(),
            "node_type": node.type().name(),
            "node_name": node.name(),
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "creating_node")
    except Exception as e:
        logger.error(f"Error creating node: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


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

def get_node_info(
    node_path: str,
    include_params: bool = True,
    max_params: int = 50,
    include_input_details: bool = True,
    include_errors: bool = False,
    force_cook: bool = False,
    compact: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Get detailed information about a node.

    Args:
        node_path: Path to the node
        include_params: Whether to include parameter values
        max_params: Maximum number of parameters to return
        include_input_details: When True, expand input connections to show source node,
                              output index, and connection index details
        include_errors: When True, include cook state and error/warning information
        force_cook: When True, force cook the node before checking errors (requires include_errors=True)

    Returns:
        Dict with node information. When include_errors=True, also includes cook_info
        with cook_state, errors, warnings, and last_cook_time.

    Example with include_input_details=True:
        {
          "status": "success",
          "path": "/obj/geo1/noise1",
          "type": "noise",
          "inputs": ["/obj/geo1/grid1"],
          "input_connections": [
            {
              "input_index": 0,
              "source_node": "/obj/geo1/grid1",
              "source_output_index": 0
            }
          ]
        }

    Example with include_errors=True:
        {
          "status": "success",
          "path": "/obj/geo1/sphere1",
          "type": "sphere",
          "cook_info": {
            "cook_state": "cooked",
            "errors": [],
            "warnings": [],
            "last_cook_time": 1234567890.123
          }
        }
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        # Compact mode: minimal response with just essential info
        if compact:
            info: Dict[str, Any] = {
                "status": "success",
                "path": node.path(),
                "type": node.type().name(),
            }
            # Only include non-empty children/inputs/outputs counts
            children_count = len(node.children())
            inputs_count = len([i for i in node.inputs() if i])
            outputs_count = len(node.outputs())
            if children_count:
                info["children_count"] = children_count
            if inputs_count:
                info["inputs_count"] = inputs_count
            if outputs_count:
                info["outputs_count"] = outputs_count
            return info

        info: Dict[str, Any] = {
            "status": "success",
            "path": node.path(),
            "name": node.name(),
            "type": node.type().name(),
            "type_description": node.type().description(),
            "children": [child.name() for child in node.children()],
            "inputs": [inp.path() if inp else None for inp in node.inputs()],
            "outputs": [out.path() for out in node.outputs()],
            "is_displayed": node.isDisplayFlagSet() if hasattr(node, "isDisplayFlagSet") else None,
            "is_rendered": node.isRenderFlagSet() if hasattr(node, "isRenderFlagSet") else None,
        }

        # Add detailed input connection information if requested
        if include_input_details:
            input_connections: List[Dict[str, Any]] = []
            node_inputs = node.inputs()

            for idx, input_node in enumerate(node_inputs):
                if input_node is not None:
                    # Try to get the output index from the source node
                    try:
                        # inputConnectors gives us (input_index, output_index) tuples
                        connectors = node.inputConnectors()
                        if idx < len(connectors):
                            connector = connectors[idx]
                            source_output_idx = connector[1] if len(connector) > 1 else 0
                        else:
                            source_output_idx = 0
                    except Exception:
                        # Fallback if inputConnectors not available
                        source_output_idx = 0

                    input_connections.append(
                        {
                            "input_index": idx,
                            "source_node": input_node.path(),
                            "source_output_index": source_output_idx,
                        }
                    )

            info["input_connections"] = input_connections

        if include_params:
            params: Dict[str, Any] = {}
            for i, parm in enumerate(node.parms()):
                if i >= max_params:
                    params["_truncated"] = True
                    break
                try:
                    params[parm.name()] = _json_safe_hou_value(hou, parm.eval())
                except Exception:
                    params[parm.name()] = "<unable to evaluate>"
            info["parameters"] = params

        # Add cook info if requested
        if include_errors:
            try:
                # Force cook if requested
                if force_cook:
                    node.cook(force=True)

                # Determine cook state using available methods
                # Houdini 20.5+ doesn't have cookState(), use needsToCook() instead
                try:
                    if hasattr(node, "cookState"):
                        cook_state_obj = node.cookState()
                        cook_state_name = (
                            cook_state_obj.name()
                            if hasattr(cook_state_obj, "name")
                            else str(cook_state_obj)
                        )
                        cook_state_map = {
                            "Cooked": "cooked",
                            "CookFailed": "error",
                            "Dirty": "dirty",
                            "Uncooked": "uncooked",
                        }
                        cook_state = cook_state_map.get(cook_state_name, cook_state_name.lower())
                    elif hasattr(node, "needsToCook"):
                        # Fallback for Houdini versions without cookState()
                        needs_cook = node.needsToCook()
                        cook_state = "dirty" if needs_cook else "cooked"
                    else:
                        cook_state = "unknown"
                except Exception:
                    cook_state = "unknown"

                # Get errors and warnings
                errors_list: List[Dict[str, str]] = []
                warnings_list: List[Dict[str, str]] = []

                # Get errors
                try:
                    node_errors = node.errors()
                    for error_msg in node_errors:
                        errors_list.append(
                            {"severity": "error", "message": error_msg, "node_path": node.path()}
                        )
                except Exception:
                    pass

                # Get warnings
                try:
                    node_warnings = node.warnings()
                    for warning_msg in node_warnings:
                        warnings_list.append(
                            {
                                "severity": "warning",
                                "message": warning_msg,
                                "node_path": node.path(),
                            }
                        )
                except Exception:
                    pass

                # Build cook info dict
                cook_info: Dict[str, Any] = {
                    "cook_state": cook_state,
                    "errors": errors_list,
                    "warnings": warnings_list,
                }

                # Try to get last cook time (may not be available on all node types)
                try:
                    # Houdini doesn't have a direct lastCookTime, but we can check if cooked
                    # For now, we'll skip this or use current time if just cooked
                    if force_cook:
                        import time

                        cook_info["last_cook_time"] = time.time()
                except Exception:
                    pass

                info["cook_info"] = cook_info

            except Exception as e:
                # If we can't get cook info, add error but don't fail the whole request
                logger.warning(f"Error getting cook info: {e}")
                info["cook_info"] = {
                    "cook_state": "unknown",
                    "errors": [
                        {"severity": "error", "message": f"Failed to get cook info: {str(e)}"}
                    ],
                    "warnings": [],
                }

        return info
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "getting_node_info")
    except Exception as e:
        logger.error(f"Error getting node info: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def delete_node(node_path: str, host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
    """
    Delete a node from the scene.

    Args:
        node_path: Path to the node to delete

    Returns:
        Dict with result.
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        node_name = node.name()
        node.destroy()

        return {
            "status": "success",
            "message": f"Deleted node: {node_name}",
            "deleted_path": node_path,
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "deleting_node")
    except Exception as e:
        logger.error(f"Error deleting node: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def save_scene(
    file_path: Optional[str] = None, host: str = "localhost", port: int = 18811
) -> Dict[str, Any]:
    """
    Save the current Houdini scene.

    Args:
        file_path: Optional path to save to. If None, saves to current file.

    Returns:
        Dict with result.
    """
    try:
        hou = ensure_connected(host, port)

        if file_path:
            hou.hipFile.save(file_path)
            saved_path = file_path
        else:
            hou.hipFile.save()
            saved_path = hou.hipFile.path()

        return {"status": "success", "message": "Scene saved", "file_path": saved_path}
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "saving_scene")
    except Exception as e:
        logger.error(f"Error saving scene: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def load_scene(file_path: str, host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
    """
    Load a Houdini scene file.

    Args:
        file_path: Path to the .hip file to load

    Returns:
        Dict with result.
    """
    try:
        hou = ensure_connected(host, port)

        hou.hipFile.load(file_path)

        return {"status": "success", "message": "Scene loaded", "file_path": file_path}
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "loading_scene")
    except Exception as e:
        logger.error(f"Error loading scene: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def new_scene(host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
    """
    Create a new empty Houdini scene.

    Returns:
        Dict with result.
    """
    try:
        hou = ensure_connected(host, port)

        hou.hipFile.clear()

        return {"status": "success", "message": "New scene created"}
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "creating_new_scene")
    except Exception as e:
        logger.error(f"Error creating new scene: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def serialize_scene(
    root_path: str = "/obj",
    include_params: bool = False,
    max_depth: int = 10,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Serialize the scene structure to a dictionary (useful for diffs/comparisons).

    This is an enhanced version ported from the OpenWebUI pipeline.

    Args:
        root_path: Root node path to serialize from
        include_params: Whether to include parameter values (can be verbose)
        max_depth: Maximum recursion depth

    Returns:
        Dict with serialized scene structure.
    """
    try:
        hou = ensure_connected(host, port)

        def node_to_dict_recursive(node: Any, depth: int = 0) -> Dict[str, Any]:
            if depth > max_depth:
                return {"path": node.path(), "truncated": True}

            result: Dict[str, Any] = {
                "path": node.path(),
                "type": node.type().name(),
                "name": node.name(),
            }

            if include_params:
                params: Dict[str, Any] = {}
                for parm in node.parms():
                    try:
                        params[parm.name()] = _json_safe_hou_value(hou, parm.eval())
                    except Exception:
                        params[parm.name()] = "<unevaluable>"
                result["parameters"] = params

            result["children"] = [
                node_to_dict_recursive(child, depth + 1) for child in node.children()
            ]

            return result

        root = hou.node(root_path)
        if root is None:
            return {"status": "error", "message": f"Root node not found: {root_path}"}

        return {"status": "success", "root": root_path, "structure": node_to_dict_recursive(root)}
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "serializing_scene")
    except Exception as e:
        logger.error(f"Error serializing scene: {e}")
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


def list_node_types(
    category: Optional[str] = None,
    max_results: int = 100,
    name_filter: Optional[str] = None,
    offset: int = 0,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    List available node types, optionally filtered by category.

    Args:
        category: Optional category filter (e.g., "Object", "Sop", "Cop2", "Vop")
        max_results: Maximum number of results to return (default: 100, max: 500)
        name_filter: Optional substring filter for node type names (case-insensitive)
        offset: Number of results to skip for pagination (default: 0)

    Returns:
        Dict with list of node types and pagination info.

    Note:
        Large categories like "Sop" have thousands of node types.
        Use name_filter to narrow results (e.g., name_filter="noise" for noise-related SOPs).
        Use offset for pagination through large result sets.
    """
    try:
        hou = ensure_connected(host, port)

        # Cap max_results to prevent excessive data transfer
        if max_results > 500:
            max_results = 500
        elif max_results < 1:
            max_results = 100

        node_types: List[Dict[str, str]] = []
        total_scanned = 0
        total_matched = 0
        categories_scanned: List[str] = []

        # Validate offset
        if offset < 0:
            offset = 0

        # Get category info first (lightweight operation)
        all_categories = list(hou.nodeTypeCategories().items())

        for cat_name, cat in all_categories:
            # Filter by category if specified
            if category and cat_name.lower() != category.lower():
                continue

            categories_scanned.append(cat_name)

            # Early termination if we've collected enough results
            if len(node_types) >= max_results:
                break

            try:
                # Get node types for this category
                # Use items() to iterate - don't convert entire dict to list
                for type_name, type_obj in cat.nodeTypes().items():
                    total_scanned += 1

                    # Apply name filter if provided
                    if name_filter:
                        if name_filter.lower() not in type_name.lower():
                            continue

                    # Count matched items for pagination info
                    total_matched += 1

                    # Skip items before offset
                    if total_matched <= offset:
                        continue

                    # Early termination check inside the loop
                    if len(node_types) >= max_results:
                        break

                    try:
                        description = type_obj.description()
                    except Exception:
                        description = ""

                    node_types.append(
                        {"category": cat_name, "name": type_name, "description": description}
                    )

            except Exception as e:
                logger.warning(f"Error iterating node types in category {cat_name}: {e}")
                continue

        result: Dict[str, Any] = {
            "status": "success",
            "count": len(node_types),
            "node_types": node_types,
            "categories_scanned": categories_scanned,
        }

        # Add pagination info
        if offset > 0:
            result["offset"] = offset

        # Calculate if there are more results
        has_more = total_matched > offset + len(node_types)
        if has_more:
            result["has_more"] = True
            result["next_offset"] = offset + len(node_types)

        # Add warning if results were limited
        if len(node_types) >= max_results:
            result["warning"] = (
                f"Results limited to {max_results}. "
                f"Use offset={offset + max_results} for next page, or use name_filter to narrow results."
            )
            result["total_scanned"] = total_scanned

        # Add response size metadata for large responses
        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "listing_node_types")
    except Exception as e:
        logger.error(f"Error listing node types: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def list_children(
    node_path: str,
    recursive: bool = False,
    max_depth: int = 10,
    max_nodes: int = 1000,
    compact: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    List child nodes with paths, types, and current input connections.

    This tool is essential for agents to understand node networks and insert
    nodes without breaking existing connections.

    Args:
        node_path: Path to the parent node
        recursive: If True, recursively traverse child nodes
        max_depth: Maximum recursion depth (prevents infinite loops)
        max_nodes: Maximum number of nodes to return (safety limit)
        compact: If True, return only path/name/type without connection details

    Returns:
        Dict with child nodes including their connection information.
        When compact=True, inputs/outputs are omitted for reduced payload size.

    Example return:
        {
          "status": "success",
          "node_path": "/obj/geo1",
          "children": [
            {
              "path": "/obj/geo1/grid1",
              "name": "grid1",
              "type": "grid",
              "inputs": [],
              "outputs": ["/obj/geo1/noise1"]
            },
            {
              "path": "/obj/geo1/noise1",
              "name": "noise1",
              "type": "noise",
              "inputs": [
                {"index": 0, "source_node": "/obj/geo1/grid1", "output_index": 0}
              ],
              "outputs": []
            }
          ],
          "count": 2
        }
    """
    try:
        hou = ensure_connected(host, port)

        parent = hou.node(node_path)
        if parent is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        children_list: List[Dict[str, Any]] = []
        nodes_collected = 0

        def collect_children(node: Any, depth: int = 0) -> None:
            nonlocal nodes_collected

            if depth > max_depth:
                logger.warning(f"Max depth {max_depth} reached at {node.path()}")
                return

            if nodes_collected >= max_nodes:
                logger.warning(f"Max nodes {max_nodes} limit reached")
                return

            try:
                for child in node.children():
                    if nodes_collected >= max_nodes:
                        break

                    # Compact mode: only path, name, type
                    if compact:
                        child_info: Dict[str, Any] = {
                            "path": child.path(),
                            "name": child.name(),
                            "type": child.type().name(),
                        }
                    else:
                        # Full mode: include input/output connection details
                        # Build input connection details
                        input_connections: List[Dict[str, Any]] = []
                        child_inputs = child.inputs()

                        for idx, input_node in enumerate(child_inputs):
                            if input_node is not None:
                                # Try to get detailed connection info
                                try:
                                    # inputConnectors gives us detailed info about each input
                                    connectors = child.inputConnectors()
                                    if idx < len(connectors):
                                        connector = connectors[idx]
                                        output_idx = connector[1] if len(connector) > 1 else 0
                                    else:
                                        output_idx = 0
                                except Exception:
                                    # Fallback if inputConnectors not available
                                    output_idx = 0

                                input_connections.append(
                                    {
                                        "index": idx,
                                        "source_node": input_node.path(),
                                        "output_index": output_idx,
                                    }
                                )

                        # Build output list
                        output_paths = [out.path() for out in child.outputs()]

                        child_info = {
                            "path": child.path(),
                            "name": child.name(),
                            "type": child.type().name(),
                            "inputs": input_connections,
                            "outputs": output_paths,
                        }

                    children_list.append(child_info)
                    nodes_collected += 1

                    # Recurse if requested
                    if recursive:
                        collect_children(child, depth + 1)

            except Exception as e:
                # Handle locked HDAs or other access issues
                logger.warning(f"Could not access children of {node.path()}: {e}")

        collect_children(parent)

        result: Dict[str, Any] = {
            "status": "success",
            "node_path": node_path,
            "children": children_list,
            "count": len(children_list),
        }

        if nodes_collected >= max_nodes:
            result["warning"] = f"Result limited to {max_nodes} nodes"

        # Add response size metadata for large responses
        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "listing_children")
    except Exception as e:
        logger.error(f"Error listing children: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def find_nodes(
    root_path: str = "/obj",
    pattern: str = "*",
    node_type: Optional[str] = None,
    max_results: int = 100,
    offset: int = 0,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Find nodes by name pattern or type using glob/substring matching.

    Args:
        root_path: Root path to start search from
        pattern: Glob pattern or substring to match against node names (* for wildcard)
        node_type: Optional node type filter (e.g., "sphere", "noise", "geo")
        max_results: Maximum number of results to return
        offset: Number of results to skip for pagination (default: 0)

    Returns:
        Dict with matching nodes and their types.
        Includes pagination info (has_more, next_offset) when applicable.

    Example:
        find_nodes("/obj", "noise*", max_results=50)
        find_nodes("/obj/geo1", "*", node_type="sphere")
        find_nodes("/obj", "*", offset=100)  # Get next page
    """
    try:
        hou = ensure_connected(host, port)

        root = hou.node(root_path)
        if root is None:
            return {"status": "error", "message": f"Root node not found: {root_path}"}

        import fnmatch

        matches: List[Dict[str, str]] = []
        total_matched = 0

        # Validate offset
        if offset < 0:
            offset = 0

        def search_recursive(node: Any) -> None:
            nonlocal total_matched
            if len(matches) >= max_results:
                return

            try:
                for child in node.children():
                    if len(matches) >= max_results:
                        break

                    # Check name pattern match
                    name_match = fnmatch.fnmatch(child.name().lower(), pattern.lower())
                    # Also support substring matching if no wildcards in pattern
                    if "*" not in pattern and "?" not in pattern:
                        name_match = name_match or pattern.lower() in child.name().lower()

                    # Check type filter
                    type_match = True
                    if node_type is not None:
                        type_match = child.type().name().lower() == node_type.lower()

                    if name_match and type_match:
                        total_matched += 1

                        # Skip items before offset
                        if total_matched <= offset:
                            # Still recurse into children
                            search_recursive(child)
                            continue

                        matches.append(
                            {
                                "path": child.path(),
                                "name": child.name(),
                                "type": child.type().name(),
                            }
                        )

                    # Recurse into children
                    search_recursive(child)

            except Exception as e:
                logger.debug(f"Could not search in {node.path()}: {e}")

        search_recursive(root)

        result: Dict[str, Any] = {
            "status": "success",
            "root_path": root_path,
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
        }

        if node_type:
            result["node_type_filter"] = node_type

        # Add pagination info
        if offset > 0:
            result["offset"] = offset

        # Calculate if there are more results
        has_more = total_matched > offset + len(matches)
        if has_more:
            result["has_more"] = True
            result["next_offset"] = offset + len(matches)

        if len(matches) >= max_results:
            result["warning"] = (
                f"Results limited to {max_results} nodes. Use offset={offset + max_results} for next page."
            )

        # Add response size metadata for large responses
        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "finding_nodes")
    except Exception as e:
        logger.error(f"Error finding nodes: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def _flatten_parm_templates(hou: Any, parm_templates: List[Any], max_depth: int = 20) -> List[Any]:
    flattened: List[Any] = []

    def walk(templates: List[Any], depth: int) -> None:
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
    seen_ids: Set[int] = set()
    unique: List[Any] = []
    for template in flattened:
        template_id = id(template)
        if template_id in seen_ids:
            continue
        seen_ids.add(template_id)
        unique.append(template)

    return unique


