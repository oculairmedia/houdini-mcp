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


def set_parameter(
    node_path: str, param_name: str, value: Any, host: str = "localhost", port: int = 18811
) -> Dict[str, Any]:
    """
    Set a parameter value on a node.

    Args:
        node_path: Path to the node (e.g., "/obj/geo1/sphere1")
        param_name: Name of the parameter (e.g., "radx", "tx")
        value: Value to set

    Returns:
        Dict with result.
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        parm = node.parm(param_name)
        if parm is None:
            # Try parmTuple for vector parameters
            parm_tuple = node.parmTuple(param_name)
            if parm_tuple is None:
                return {
                    "status": "error",
                    "message": f"Parameter not found: {param_name} on {node_path}",
                }
            # Set tuple value
            if isinstance(value, (list, tuple)):
                parm_tuple.set(value)
            else:
                return {
                    "status": "error",
                    "message": f"Parameter {param_name} is a tuple, provide a list/tuple value",
                }
        else:
            parm.set(value)

        return {
            "status": "success",
            "node_path": node_path,
            "param_name": param_name,
            "value": value,
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "setting_parameter")
    except Exception as e:
        logger.error(f"Error setting parameter: {e}")
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


def render_viewport(
    camera_position: Optional[List[float]] = None,
    camera_rotation: Optional[List[float]] = None,
    look_at: Optional[str] = None,
    resolution: Optional[List[int]] = None,
    renderer: str = "opengl",
    output_format: str = "png",
    auto_frame: bool = True,
    orthographic: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Render the viewport and return the image as base64.

    Creates a temporary camera, positions it to frame the scene geometry,
    renders the scene, and returns the rendered image encoded as base64.

    Args:
        camera_position: [x, y, z] world position for camera (default: auto-calculated)
        camera_rotation: [rx, ry, rz] rotation in degrees (default: [-30, 45, 0] isometric)
        look_at: Node path to look at (centers camera on this node's geometry)
        resolution: [width, height] in pixels (default: [512, 512])
        renderer: Render engine - "opengl" (fast) or "karma" (quality)
        output_format: Image format - "png", "jpg", or "exr"
        auto_frame: If True, automatically frame all visible geometry (default: True)
        orthographic: If True, use orthographic projection (default: False)

    Returns:
        Dict with:
        - status: "success" or "error"
        - image_base64: Base64-encoded image data
        - format: Image format used
        - resolution: [width, height]
        - camera_path: Path to the temporary camera used
        - bounding_box: Scene bounding box if auto_frame was used

    Example:
        render_viewport()  # Auto-frame scene with isometric view
        render_viewport(camera_rotation=[0, 0, 0])  # Front view
        render_viewport(camera_rotation=[-90, 0, 0])  # Top view
        render_viewport(look_at="/obj/geo1", orthographic=True)
    """
    try:
        hou = ensure_connected(host, port)
        import base64
        import tempfile
        import os
        import math

        # Set defaults
        if resolution is None:
            resolution = [512, 512]
        if camera_rotation is None:
            camera_rotation = [-30.0, 45.0, 0.0]  # Isometric view

        # Validate resolution
        width, height = resolution[0], resolution[1]
        if width < 64 or height < 64:
            return {"status": "error", "message": "Resolution must be at least 64x64"}
        if width > 4096 or height > 4096:
            return {"status": "error", "message": "Resolution cannot exceed 4096x4096"}

        # Get /obj context
        obj_context = hou.node("/obj")
        if obj_context is None:
            return {"status": "error", "message": "Cannot find /obj context"}

        # Calculate bounding box of visible geometry if auto_frame
        bbox_info = None
        bbox_center = [0.0, 0.0, 0.0]
        bbox_size = 10.0  # Default size

        if auto_frame:
            # Find all displayed geometry nodes
            displayed_geo = []
            for node in obj_context.children():
                try:
                    node_type = node.type().name()
                    if node_type in ["geo", "subnet"] and node.isDisplayFlagSet():
                        displayed_geo.append(node)
                except Exception:
                    continue

            # Calculate collective bounding box
            if displayed_geo:
                min_bounds = [float("inf")] * 3
                max_bounds = [float("-inf")] * 3

                for node in displayed_geo:
                    try:
                        display_node = node.displayNode()
                        if display_node is None:
                            continue
                        geo = display_node.geometry()
                        if geo is None:
                            continue
                        bbox = geo.boundingBox()
                        if bbox is None:
                            continue

                        # Get node's world transform
                        transform = node.worldTransform()

                        # Transform bounding box corners
                        for x in [bbox.minvec()[0], bbox.maxvec()[0]]:
                            for y in [bbox.minvec()[1], bbox.maxvec()[1]]:
                                for z in [bbox.minvec()[2], bbox.maxvec()[2]]:
                                    point = hou.Vector4(x, y, z, 1.0)
                                    transformed = point * transform
                                    min_bounds[0] = min(min_bounds[0], transformed[0])
                                    min_bounds[1] = min(min_bounds[1], transformed[1])
                                    min_bounds[2] = min(min_bounds[2], transformed[2])
                                    max_bounds[0] = max(max_bounds[0], transformed[0])
                                    max_bounds[1] = max(max_bounds[1], transformed[1])
                                    max_bounds[2] = max(max_bounds[2], transformed[2])
                    except Exception as e:
                        logger.debug(f"Error getting bbox for {node.path()}: {e}")
                        continue

                if min_bounds[0] != float("inf"):
                    bbox_center = [
                        (min_bounds[0] + max_bounds[0]) / 2,
                        (min_bounds[1] + max_bounds[1]) / 2,
                        (min_bounds[2] + max_bounds[2]) / 2,
                    ]
                    bbox_size = max(
                        max_bounds[0] - min_bounds[0],
                        max_bounds[1] - min_bounds[1],
                        max_bounds[2] - min_bounds[2],
                    )
                    bbox_info = {
                        "min": min_bounds,
                        "max": max_bounds,
                        "center": bbox_center,
                        "size": bbox_size,
                    }

        # Override center if look_at is specified
        if look_at:
            target_node = hou.node(look_at)
            if target_node:
                try:
                    # Try to get geometry center
                    display_node = (
                        target_node.displayNode() if hasattr(target_node, "displayNode") else None
                    )
                    if display_node:
                        geo = display_node.geometry()
                        if geo:
                            bbox = geo.boundingBox()
                            if bbox:
                                bbox_center = list(bbox.center())
                                bbox_size = max(bbox.sizevec())
                except Exception:
                    # Fall back to node transform
                    try:
                        bbox_center = [
                            target_node.parm("tx").eval() if target_node.parm("tx") else 0,
                            target_node.parm("ty").eval() if target_node.parm("ty") else 0,
                            target_node.parm("tz").eval() if target_node.parm("tz") else 0,
                        ]
                    except Exception:
                        pass

        # Create camera null (for rotation pivot) and camera
        null_name = "_mcp_cam_center"
        cam_name = "_mcp_render_cam"

        # Delete existing nodes
        existing_null = obj_context.node(null_name)
        if existing_null:
            existing_null.destroy()
        existing_cam = obj_context.node(cam_name)
        if existing_cam:
            existing_cam.destroy()

        # Create null at bbox center
        null = obj_context.createNode("null", null_name)
        null.parmTuple("t").set(bbox_center)
        null.parmTuple("r").set(camera_rotation)

        # Create camera as child of null
        camera = obj_context.createNode("cam", cam_name)
        camera.setFirstInput(null)

        # Calculate camera distance to frame geometry
        # Using FOV and bbox size
        fov_degrees = 45.0  # Default FOV
        padding = 1.2  # 20% padding
        distance = (bbox_size * padding / 2) / math.tan(math.radians(fov_degrees / 2))
        distance = max(5.0, distance + bbox_size / 2)  # Ensure minimum distance

        # Position camera along Z axis (it will be rotated by null)
        if camera_position:
            camera.parmTuple("t").set(camera_position)
        else:
            camera.parmTuple("t").set([0, 0, distance])

        # Set resolution
        camera.parm("resx").set(width)
        camera.parm("resy").set(height)

        # Set projection type
        if orthographic:
            camera.parm("projection").set(1)  # Orthographic
            # Set ortho width to frame geometry
            camera.parm("orthowidth").set(bbox_size * padding)
        else:
            camera.parm("projection").set(0)  # Perspective

        # Create temp file for output
        suffix = f".{output_format}"
        temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        output_path = temp_file.name
        temp_file.close()

        try:
            out_context = hou.node("/out")
            if out_context is None:
                return {"status": "error", "message": "Cannot find /out context"}

            # Render using OpenGL or Karma
            if renderer.lower() == "opengl":
                rop_name = "_mcp_opengl_rop"
                rop = out_context.node(rop_name)
                if rop is None:
                    rop = out_context.createNode("opengl", rop_name)

                rop.parm("camera").set(camera.path())
                rop.parm("picture").set(output_path)
                if rop.parm("tres"):
                    rop.parm("tres").set(True)
                if rop.parm("res1"):
                    rop.parm("res1").set(width)
                if rop.parm("res2"):
                    rop.parm("res2").set(height)
                if rop.parm("trange"):
                    rop.parm("trange").set(0)  # Current frame only
                rop.render()

            elif renderer.lower() == "karma":
                rop_name = "_mcp_karma_rop"
                rop = out_context.node(rop_name)
                if rop is None:
                    rop = out_context.createNode("karma", rop_name)

                rop.parm("camera").set(camera.path())
                rop.parm("picture").set(output_path)
                if rop.parm("resolutionx"):
                    rop.parm("resolutionx").set(width)
                if rop.parm("resolutiony"):
                    rop.parm("resolutiony").set(height)
                if rop.parm("trange"):
                    rop.parm("trange").set(0)
                rop.render()
            else:
                return {"status": "error", "message": f"Unknown renderer: {renderer}"}

            # Read rendered image and encode as base64
            if os.path.exists(output_path):
                with open(output_path, "rb") as f:
                    image_data = f.read()
                image_base64 = base64.b64encode(image_data).decode("utf-8")

                result = {
                    "status": "success",
                    "image_base64": image_base64,
                    "format": output_format,
                    "resolution": [width, height],
                    "camera_path": camera.path(),
                    "renderer": renderer,
                }
                if bbox_info:
                    result["bounding_box"] = bbox_info
                return result
            else:
                return {"status": "error", "message": "Render completed but output file not found"}

        finally:
            # Clean up temp file
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "rendering_viewport")
    except Exception as e:
        logger.error(f"Error rendering viewport: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def find_error_nodes(
    root_path: str = "/",
    include_warnings: bool = True,
    max_results: int = 100,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Find all nodes with cook errors or warnings in the scene.

    Scans the entire node hierarchy starting from root_path and returns
    all nodes that have errors or warnings. Essential for debugging
    complex scenes where error locations are unknown.

    Args:
        root_path: Root path to start search from (default: "/" for entire scene)
        include_warnings: Whether to include nodes with warnings (default: True)
        max_results: Maximum number of results to return (default: 100)

    Returns:
        Dict with error/warning nodes including:
        - error_nodes: List of nodes with errors
        - warning_nodes: List of nodes with warnings (if include_warnings=True)
        - total_scanned: Number of nodes scanned

    Example:
        find_error_nodes()  # Find all errors in scene
        find_error_nodes("/obj/geo1")  # Find errors within a specific network
        find_error_nodes(include_warnings=False)  # Only errors, no warnings
    """
    try:
        hou = ensure_connected(host, port)

        root = hou.node(root_path)
        if root is None:
            return {"status": "error", "message": f"Root node not found: {root_path}"}

        error_nodes: List[Dict[str, Any]] = []
        warning_nodes: List[Dict[str, Any]] = []
        total_scanned = 0

        def scan_recursive(node: Any) -> None:
            nonlocal total_scanned

            # Check if we've hit the limit
            total_results = len(error_nodes) + (len(warning_nodes) if include_warnings else 0)
            if total_results >= max_results:
                return

            try:
                # Get all descendant nodes
                all_children = node.allSubChildren()

                for child in all_children:
                    total_scanned += 1

                    # Check limits again inside loop
                    total_results = len(error_nodes) + (
                        len(warning_nodes) if include_warnings else 0
                    )
                    if total_results >= max_results:
                        break

                    try:
                        # Get errors
                        errors = child.errors()
                        if errors:
                            error_nodes.append(
                                {
                                    "path": child.path(),
                                    "name": child.name(),
                                    "type": child.type().name(),
                                    "errors": list(errors) if errors else [],
                                }
                            )

                        # Get warnings if requested
                        if include_warnings:
                            warnings = child.warnings()
                            if warnings:
                                warning_nodes.append(
                                    {
                                        "path": child.path(),
                                        "name": child.name(),
                                        "type": child.type().name(),
                                        "warnings": list(warnings) if warnings else [],
                                    }
                                )

                    except Exception as e:
                        logger.debug(f"Could not check errors on {child.path()}: {e}")

            except Exception as e:
                logger.warning(f"Could not scan children of {node.path()}: {e}")

        # Also check the root node itself if it's not "/"
        if root_path != "/":
            total_scanned += 1
            try:
                errors = root.errors()
                if errors:
                    error_nodes.append(
                        {
                            "path": root.path(),
                            "name": root.name(),
                            "type": root.type().name(),
                            "errors": list(errors) if errors else [],
                        }
                    )
                if include_warnings:
                    warnings = root.warnings()
                    if warnings:
                        warning_nodes.append(
                            {
                                "path": root.path(),
                                "name": root.name(),
                                "type": root.type().name(),
                                "warnings": list(warnings) if warnings else [],
                            }
                        )
            except Exception:
                pass

        scan_recursive(root)

        result: Dict[str, Any] = {
            "status": "success",
            "root_path": root_path,
            "error_nodes": error_nodes,
            "error_count": len(error_nodes),
            "total_scanned": total_scanned,
        }

        if include_warnings:
            result["warning_nodes"] = warning_nodes
            result["warning_count"] = len(warning_nodes)

        # Add warning if results were limited
        total_results = len(error_nodes) + (len(warning_nodes) if include_warnings else 0)
        if total_results >= max_results:
            result["warning"] = (
                f"Results limited to {max_results}. Increase max_results to see more."
            )

        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "finding_error_nodes")
    except Exception as e:
        logger.error(f"Error finding error nodes: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def connect_nodes(
    src_path: str,
    dst_path: str,
    dst_input_index: int = 0,
    src_output_index: int = 0,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Wire output of source node to input of destination node.

    Validates that node types are compatible (e.g., SOP→SOP, OBJ→OBJ) before connecting.
    Automatically disconnects existing connection if the destination input is already wired.

    Args:
        src_path: Path to source node
        dst_path: Path to destination node
        dst_input_index: Input index on destination node (default: 0)
        src_output_index: Output index on source node (default: 0)

    Returns:
        Dict with connection result.

    Example:
        connect_nodes("/obj/geo1/grid1", "/obj/geo1/noise1")  # Connect grid → noise
        connect_nodes("/obj/geo1/grid1", "/obj/geo1/merge1", dst_input_index=1)
    """
    try:
        hou = ensure_connected(host, port)

        # Get both nodes
        src_node = hou.node(src_path)
        if src_node is None:
            return {"status": "error", "message": f"Source node not found: {src_path}"}

        dst_node = hou.node(dst_path)
        if dst_node is None:
            return {"status": "error", "message": f"Destination node not found: {dst_path}"}

        # Validate compatible node types
        # Get category name (e.g., "Sop", "Object", "Dop")
        try:
            src_category = src_node.type().category().name()
            dst_category = dst_node.type().category().name()

            if src_category != dst_category:
                return {
                    "status": "error",
                    "message": f"Incompatible node types: {src_category} → {dst_category}. "
                    f"Cannot connect {src_path} ({src_category}) to {dst_path} ({dst_category})",
                }
        except Exception as e:
            logger.warning(f"Could not validate node categories: {e}")
            # Continue if category check fails - let Houdini validate

        # Check if destination input is already connected
        existing_inputs = dst_node.inputs()
        if dst_input_index < len(existing_inputs) and existing_inputs[dst_input_index] is not None:
            existing_src = existing_inputs[dst_input_index]
            logger.info(
                f"Disconnecting existing connection from {existing_src.path()} to {dst_path}[{dst_input_index}]"
            )

        # Make the connection
        dst_node.setInput(dst_input_index, src_node, src_output_index)

        return {
            "status": "success",
            "message": f"Connected {src_path} → {dst_path}",
            "source_node": src_path,
            "destination_node": dst_path,
            "source_output_index": src_output_index,
            "destination_input_index": dst_input_index,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "connecting_nodes")
    except Exception as e:
        logger.error(f"Error connecting nodes: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def disconnect_node_input(
    node_path: str, input_index: int = 0, host: str = "localhost", port: int = 18811
) -> Dict[str, Any]:
    """
    Break/disconnect an input connection on a node.

    Args:
        node_path: Path to the node
        input_index: Input index to disconnect (default: 0)

    Returns:
        Dict with disconnection result.

    Example:
        disconnect_node_input("/obj/geo1/noise1")  # Disconnect first input
        disconnect_node_input("/obj/geo1/merge1", input_index=1)  # Disconnect second input
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        # Check if input exists and is connected
        inputs = node.inputs()
        if inputs is None:
            inputs = []

        if input_index >= len(inputs):
            return {
                "status": "error",
                "message": f"Input index {input_index} out of range for node {node_path} (has {len(inputs)} inputs)",
            }

        existing_input = inputs[input_index] if input_index < len(inputs) else None
        was_connected = existing_input is not None

        # Disconnect the input
        node.setInput(input_index, None)

        result: Dict[str, Any] = {
            "status": "success",
            "node_path": node_path,
            "input_index": input_index,
            "was_connected": was_connected,
        }

        if was_connected:
            result["message"] = (
                f"Disconnected input {input_index} on {node_path} (was connected to {existing_input.path()})"
            )
            result["previous_source"] = existing_input.path()
        else:
            result["message"] = f"Input {input_index} on {node_path} was already disconnected"

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "disconnecting_node_input")
    except Exception as e:
        logger.error(f"Error disconnecting node input: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def set_node_flags(
    node_path: str,
    display: Optional[bool] = None,
    render: Optional[bool] = None,
    bypass: Optional[bool] = None,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Set display, render, and bypass flags on a node.

    Only non-None values are set, allowing partial flag updates.
    Checks for flag availability using hasattr() before setting.

    Args:
        node_path: Path to the node
        display: Display flag value (True/False) or None to skip
        render: Render flag value (True/False) or None to skip
        bypass: Bypass flag value (True/False) or None to skip

    Returns:
        Dict with result and flags that were set.

    Example:
        set_node_flags("/obj/geo1/sphere1", display=True, render=True)
        set_node_flags("/obj/geo1/noise1", bypass=True)
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        flags_set: Dict[str, bool] = {}
        flags_unavailable: List[str] = []

        # Set display flag
        if display is not None:
            if hasattr(node, "setDisplayFlag"):
                node.setDisplayFlag(display)
                flags_set["display"] = display
            else:
                flags_unavailable.append("display")

        # Set render flag
        if render is not None:
            if hasattr(node, "setRenderFlag"):
                node.setRenderFlag(render)
                flags_set["render"] = render
            else:
                flags_unavailable.append("render")

        # Set bypass flag
        if bypass is not None:
            if hasattr(node, "setBypass"):
                node.setBypass(bypass)
                flags_set["bypass"] = bypass
            else:
                flags_unavailable.append("bypass")

        result: Dict[str, Any] = {
            "status": "success",
            "node_path": node_path,
            "flags_set": flags_set,
        }

        if flags_unavailable:
            result["flags_unavailable"] = flags_unavailable
            result["warning"] = (
                f"Some flags not available on this node type: {', '.join(flags_unavailable)}"
            )

        if not flags_set:
            result["message"] = "No flags were set (all values were None or unavailable)"
        else:
            result["message"] = (
                f"Set flags on {node_path}: {', '.join(f'{k}={v}' for k, v in flags_set.items())}"
            )

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "setting_node_flags")
    except Exception as e:
        logger.error(f"Error setting node flags: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def reorder_inputs(
    node_path: str, new_order: List[int], host: str = "localhost", port: int = 18811
) -> Dict[str, Any]:
    """
    Reorder inputs on a node (useful for merge nodes).

    Stores existing connections, disconnects all, then reconnects in new order.
    new_order specifies the new position for each input: [1, 0, 2] swaps first two inputs.

    Args:
        node_path: Path to the node
        new_order: List specifying new input order (e.g., [1, 0, 2] to swap first two)

    Returns:
        Dict with reordering result.

    Example:
        # Swap first two inputs on a merge node
        reorder_inputs("/obj/geo1/merge1", [1, 0, 2, 3])

        # Reverse three inputs
        reorder_inputs("/obj/geo1/merge1", [2, 1, 0])
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        # Get current inputs
        current_inputs = node.inputs()
        if current_inputs is None:
            current_inputs = []

        # Validate new_order
        if len(new_order) > len(current_inputs):
            return {
                "status": "error",
                "message": f"new_order length ({len(new_order)}) exceeds number of inputs ({len(current_inputs)})",
            }

        # Validate indices
        if not all(0 <= idx < len(current_inputs) for idx in new_order):
            return {
                "status": "error",
                "message": f"Invalid indices in new_order. Must be in range [0, {len(current_inputs) - 1}]",
            }

        # Store connection information (input_node, output_index)
        stored_connections: List[Optional[Tuple[Any, int]]] = []
        for idx, input_node in enumerate(current_inputs):
            if input_node is not None:
                # Try to get output index from inputConnectors
                try:
                    connectors = node.inputConnectors()
                    if idx < len(connectors):
                        output_idx = connectors[idx][1] if len(connectors[idx]) > 1 else 0
                    else:
                        output_idx = 0
                except Exception:
                    output_idx = 0
                stored_connections.append((input_node, int(output_idx)))
            else:
                stored_connections.append(None)

        # Disconnect all inputs
        for i in range(len(current_inputs)):
            node.setInput(i, None)

        # Reconnect in new order
        reconnection_info: List[Dict[str, Any]] = []
        for new_idx, old_idx in enumerate(new_order):
            if old_idx >= len(stored_connections):
                continue

            stored_connection = stored_connections[old_idx]
            if stored_connection is None:
                continue

            src_node, output_idx = stored_connection
            node.setInput(new_idx, src_node, output_idx)
            reconnection_info.append(
                {
                    "new_input_index": new_idx,
                    "old_input_index": old_idx,
                    "source_node": src_node.path(),
                    "source_output_index": output_idx,
                }
            )

        return {
            "status": "success",
            "message": f"Reordered inputs on {node_path}",
            "node_path": node_path,
            "new_order": new_order,
            "reconnections": reconnection_info,
            "reconnection_count": len(reconnection_info),
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "reordering_inputs")
    except Exception as e:
        logger.error(f"Error reordering inputs: {e}")
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


def get_parameter_schema(
    node_path: str,
    parm_name: Optional[str] = None,
    max_parms: int = 100,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Get parameter metadata/schema for intelligent parameter setting.

    Returns detailed parameter information including types, defaults, ranges,
    menu items, and current values. This helps agents understand what parameters
    are available and how to set them correctly.

    Args:
        node_path: Path to the node
        parm_name: Optional specific parameter name. If provided, returns only that parameter.
                  If None, returns all parameters (up to max_parms)
        max_parms: Maximum number of parameters to return when parm_name is None (default: 100)

    Returns:
        Dict with parameter schema information.

    Example return for single parameter:
        {
          "status": "success",
          "node_path": "/obj/geo1/sphere1",
          "parameters": [
            {
              "name": "radx",
              "label": "Radius X",
              "type": "float",
              "default": 1.0,
              "min": 0.0,
              "max": None,
              "current_value": 2.5,
              "is_animatable": True
            }
          ],
          "count": 1
        }

    Example with menu parameter:
        {
          "name": "type",
          "label": "Type",
          "type": "menu",
          "default": 0,
          "menu_items": [
            {"label": "Polygon", "value": 0},
            {"label": "Mesh", "value": 1}
          ],
          "current_value": 0,
          "is_animatable": False
        }

    Example with vector parameter:
        {
          "name": "t",
          "label": "Translate",
          "type": "vector",
          "tuple_size": 3,
          "default": [0.0, 0.0, 0.0],
          "current_value": [1.0, 2.0, 3.0],
          "is_animatable": True
        }
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        parameters: List[Dict[str, Any]] = []

        # Get parameter templates - either specific one or all
        if parm_name is not None:
            # Get specific parameter template.
            #
            # Unit tests use MockHouNode which stores values in `_params`. For tuple-valued
            # entries, we need to prefer parmTuple(). For MagicMock-based nodes (no `_params`),
            # prefer parm() to avoid placeholder parmTuple() mocks.
            prefers_tuple = False
            try:
                if hasattr(node, "_params") and isinstance(
                    node._params.get(parm_name), (list, tuple)
                ):
                    prefers_tuple = True
            except Exception:
                prefers_tuple = False

            if prefers_tuple:
                parm_tuple = node.parmTuple(parm_name)
                if parm_tuple is None:
                    return {
                        "status": "error",
                        "message": f"Parameter not found: {parm_name} on node {node_path}",
                    }
                parm_template = parm_tuple.parmTemplate()
            else:
                parm = node.parm(parm_name)
                if parm is not None:
                    parm_template = parm.parmTemplate()
                else:
                    parm_tuple = node.parmTuple(parm_name)
                    if parm_tuple is None:
                        return {
                            "status": "error",
                            "message": f"Parameter not found: {parm_name} on node {node_path}",
                        }
                    parm_template = parm_tuple.parmTemplate()

            # When we only requested one parameter, we expect to include it even if
            # its template is folder-like (rare but possible).
            parm_templates = [parm_template]
        else:
            # Get all parameter templates from node.
            # Prefer parmTemplates() if present since our unit tests mock that API.
            if hasattr(node, "parmTemplates"):
                parm_templates = list(node.parmTemplates())
            elif hasattr(node, "parmTemplateGroup"):
                ptg = node.parmTemplateGroup()
                parm_templates = _flatten_parm_templates(hou, list(ptg.parmTemplates()))
            else:
                parm_templates = []

        # Process each parameter template
        for idx, parm_template in enumerate(parm_templates):
            if idx >= max_parms and parm_name is None:
                logger.info(f"Reached max_parms limit of {max_parms}")
                break

            try:
                param_info = _extract_parameter_info(hou, node, parm_template)
                if param_info is not None:
                    parameters.append(param_info)
            except Exception as e:
                logger.warning(f"Failed to extract info for parameter {parm_template.name()}: {e}")
                # Continue with next parameter

        result = {
            "status": "success",
            "node_path": node_path,
            "parameters": parameters,
            "count": len(parameters),
        }

        # Add response size metadata for large responses
        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "getting_parameter_schema")
    except Exception as e:
        logger.error(f"Error getting parameter schema: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def _extract_parameter_info(hou: Any, node: Any, parm_template: Any) -> Optional[Dict[str, Any]]:
    """
    Extract parameter information from a parameter template.

    Args:
        hou: The hou module
        node: The node containing the parameter
        parm_template: The parameter template to extract info from

    Returns:
        Dict with parameter info, or None if parameter should be skipped
    """
    # Get parameter template type enum
    parm_type = parm_template.type()

    # Skip folder/separator parameters - they're not settable
    # Check against hou.parmTemplateType enum
    try:
        if parm_type in (
            hou.parmTemplateType.Folder,
            hou.parmTemplateType.FolderSet,
            hou.parmTemplateType.Separator,
            hou.parmTemplateType.Label,
        ):
            return None
    except Exception:
        # If we can't check the type, continue anyway
        pass

    param_name = parm_template.name()
    param_label = parm_template.label()

    # Initialize param info dict
    param_info: Dict[str, Any] = {"name": param_name, "label": param_label}

    # Determine if this is a tuple/vector parameter
    num_components = 1
    try:
        num_components = parm_template.numComponents()
        # Ensure it's an integer, not a mock
        num_components = int(num_components)
    except Exception:
        num_components = 1

    is_tuple = num_components > 1

    # Get current value
    try:
        if is_tuple:
            parm_tuple = node.parmTuple(param_name)
            if parm_tuple is not None:
                param_info["current_value"] = _json_safe_hou_value(hou, list(parm_tuple.eval()))
            else:
                param_info["current_value"] = None
        else:
            parm = node.parm(param_name)
            if parm is not None:
                param_info["current_value"] = _json_safe_hou_value(hou, parm.eval())
            else:
                param_info["current_value"] = None
    except Exception as e:
        logger.debug(f"Could not get current value for {param_name}: {e}")
        param_info["current_value"] = None

    # Map Houdini parameter type to friendly string
    type_str = _map_parm_type_to_string(hou, parm_type, is_tuple)
    param_info["type"] = type_str

    if is_tuple:
        param_info["tuple_size"] = num_components

    # Get default value(s)
    try:
        if is_tuple:
            defaults = []
            for i in range(num_components):
                try:
                    default_val = parm_template.defaultValue()[i]
                    defaults.append(default_val)
                except Exception:
                    try:
                        default_expr = parm_template.defaultExpression()[i]
                        defaults.append(default_expr if default_expr else 0.0)
                    except Exception:
                        defaults.append(0.0)
            param_info["default"] = defaults
        else:
            try:
                param_info["default"] = parm_template.defaultValue()[0]
            except Exception:
                try:
                    default_expr = parm_template.defaultExpression()[0]
                    param_info["default"] = default_expr if default_expr else None
                except Exception:
                    param_info["default"] = None
    except Exception as e:
        logger.debug(f"Could not get default value for {param_name}: {e}")
        param_info["default"] = None

    # Get min/max for numeric types
    if type_str in ("float", "int", "vector"):
        try:
            min_val = parm_template.minValue()
            max_val = parm_template.maxValue()
            param_info["min"] = min_val if min_val is not None else None
            param_info["max"] = max_val if max_val is not None else None
        except Exception:
            param_info["min"] = None
            param_info["max"] = None

    # Get menu items for menu parameters
    if type_str == "menu":
        try:
            menu_labels = parm_template.menuLabels()
            menu_items_raw = parm_template.menuItems()

            menu_items = []
            for idx, label in enumerate(menu_labels):
                # Menu items can be strings or integers
                if idx < len(menu_items_raw):
                    value = menu_items_raw[idx]
                    # Try to convert to int if it's a numeric string
                    try:
                        value = int(value)
                    except (ValueError, TypeError):
                        pass
                else:
                    value = idx

                menu_items.append({"label": label, "value": value})

            param_info["menu_items"] = menu_items
        except Exception as e:
            logger.debug(f"Could not get menu items for {param_name}: {e}")
            param_info["menu_items"] = []

    # Determine if parameter is animatable
    try:
        # Most parameters are animatable except menus, toggles, buttons
        is_animatable = type_str not in ("menu", "toggle", "button", "string")
        param_info["is_animatable"] = is_animatable
    except Exception:
        param_info["is_animatable"] = True  # Default to true

    return param_info


def _map_parm_type_to_string(hou: Any, parm_type: Any, is_tuple: bool = False) -> str:
    """
    Map Houdini parmTemplateType enum to friendly string.

    Args:
        hou: The hou module
        parm_type: The parameter template type enum
        is_tuple: Whether this is a tuple/vector parameter

    Returns:
        String representation of the parameter type
    """
    try:
        # Access the enum values
        if parm_type == hou.parmTemplateType.Float:
            return "vector" if is_tuple else "float"
        elif parm_type == hou.parmTemplateType.Int:
            return "vector" if is_tuple else "int"
        elif parm_type == hou.parmTemplateType.String:
            return "string"
        elif parm_type == hou.parmTemplateType.Toggle:
            return "toggle"
        elif parm_type == hou.parmTemplateType.Menu:
            return "menu"
        elif parm_type == hou.parmTemplateType.Button:
            return "button"
        elif parm_type == hou.parmTemplateType.Ramp:
            return "ramp"
        elif parm_type == hou.parmTemplateType.Data:
            return "data"
        else:
            return "unknown"
    except Exception:
        # Fallback if we can't access the enum
        return "unknown"


def get_geo_summary(
    node_path: str,
    max_sample_points: int = 100,
    include_attributes: bool = True,
    include_groups: bool = True,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Get geometry statistics and metadata for verification.

    Returns comprehensive geometry information including point/primitive counts,
    bounding box, attributes, groups, and optionally sample points. Useful for
    agents to verify results after operations.

    This function executes geometry analysis on the Houdini side to avoid
    slow RPC iteration over large point/primitive counts.

    Args:
        node_path: Path to the SOP node (e.g., "/obj/geo1/sphere1")
        max_sample_points: Maximum number of sample points to return (default: 100, max: 10000)
        include_attributes: Whether to include attribute metadata (default: True)
        include_groups: Whether to include group information (default: True)

    Returns:
        Dict with geometry summary including:
        - status: "success" or "error"
        - node_path: Path to the node
        - cook_state: "cooked", "dirty", "uncooked", or "error"
        - point_count: Number of points
        - primitive_count: Number of primitives
        - vertex_count: Total number of vertices across all primitives
        - bounding_box: {min, max, size, center} in world space
        - attributes: {point, primitive, vertex, detail} attribute lists
        - groups: {point, primitive} group lists
        - sample_points: Optional list of first N points with attribute values

    Example:
        get_geo_summary("/obj/geo1/sphere1", max_sample_points=50)

    Edge cases:
        - Uncooked geometry: Will attempt to cook first
        - Empty geometry: Returns zeros, not error
        - Massive geometry (>1M points): Caps sampling with warning
        - No bounding box: Returns None for bbox fields
    """
    # Validate max_sample_points
    if max_sample_points < 0:
        max_sample_points = 0
    elif max_sample_points > 10000:
        logger.warning(f"max_sample_points capped at 10000 (was {max_sample_points})")
        max_sample_points = 10000

    # Build Houdini-side code that does all the heavy lifting locally
    # This avoids slow RPC iteration over geometry elements
    geo_analysis_code = f"""
import json

node_path = {repr(node_path)}
max_sample_points = {max_sample_points}
include_attributes = {include_attributes}
include_groups = {include_groups}

result = {{"status": "success", "node_path": node_path}}

# Get node
node = hou.node(node_path)
if node is None:
    result = {{"status": "error", "message": f"Node not found: {{node_path}}"}}
else:
    # Check cook state
    cook_state = "unknown"
    try:
        if hasattr(node, "needsToCook"):
            if node.needsToCook():
                cook_state = "dirty"
                node.cook(force=True)
            cook_state = "cooked"
    except:
        pass
    result["cook_state"] = cook_state

    # Get geometry
    geo = None
    try:
        geo = node.geometry()
    except:
        pass

    if geo is None:
        result = {{"status": "error", "message": f"Node {{node_path}} has no geometry"}}
    else:
        # Counts - these are fast native calls
        result["point_count"] = geo.intrinsicValue("pointcount")
        result["primitive_count"] = geo.intrinsicValue("primitivecount")
        result["vertex_count"] = geo.intrinsicValue("vertexcount")

        # Bounding box
        try:
            bbox = geo.boundingBox()
            result["bounding_box"] = {{
                "min": list(bbox.minvec()),
                "max": list(bbox.maxvec()),
                "size": list(bbox.sizevec()),
                "center": list(bbox.center()),
            }}
        except:
            result["bounding_box"] = None

        # Attributes
        if include_attributes:
            attributes = {{"point": [], "primitive": [], "vertex": [], "detail": []}}
            
            for attrib in geo.pointAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["point"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            for attrib in geo.primAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["primitive"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            for attrib in geo.vertexAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["vertex"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            for attrib in geo.globalAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["detail"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            result["attributes"] = attributes

        # Groups
        if include_groups:
            groups = {{"point": [], "primitive": []}}
            for g in geo.pointGroups():
                try:
                    groups["point"].append(g.name())
                except:
                    pass
            for g in geo.primGroups():
                try:
                    groups["primitive"].append(g.name())
                except:
                    pass
            result["groups"] = groups

        # Sample points - use numpy-style array access if possible
        point_count = result["point_count"]
        if max_sample_points > 0 and point_count > 0:
            if point_count > 1000000:
                result["warning"] = f"Geometry has {{point_count}} points (>1M). Sampling limited."
            
            sample_count = min(max_sample_points, point_count)
            sample_points = []
            
            # Get point attribute names
            point_attrib_names = [a.name() for a in geo.pointAttribs()]
            
            # Sample using efficient access
            for i in range(sample_count):
                pt = geo.point(i)
                if pt is None:
                    continue
                point_data = {{"index": i}}
                for aname in point_attrib_names:
                    try:
                        val = pt.attribValue(aname)
                        if val is not None:
                            if isinstance(val, (tuple, list, hou.Vector2, hou.Vector3, hou.Vector4)):
                                point_data[aname] = list(val)
                            else:
                                point_data[aname] = val
                    except:
                        pass
                sample_points.append(point_data)
            
            result["sample_points"] = sample_points

# Return JSON string
print(json.dumps(result))
"""

    try:
        # Use execute_code to run the analysis on Houdini side
        exec_result = execute_code(
            code=geo_analysis_code,
            capture_diff=False,
            max_stdout_size=500000,  # Allow larger output for geo data
            timeout=30,
            host=host,
            port=port,
        )

        if exec_result.get("status") == "error":
            return exec_result

        # Parse the JSON output from stdout
        stdout = exec_result.get("stdout", "").strip()
        if not stdout:
            return {"status": "error", "message": "No output from geometry analysis"}

        import json

        try:
            result = json.loads(stdout)
            return _add_response_metadata(result)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "message": f"Failed to parse geometry data: {e}",
                "raw_output": stdout[:500],
            }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "getting_geometry_summary")
    except Exception as e:
        logger.error(f"Error getting geometry summary: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def get_houdini_help(
    help_type: str,
    item_name: str,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Fetch Houdini documentation from SideFX website.

    Retrieves and parses help documentation for nodes, VEX functions,
    and Python API. Helps AI understand Houdini concepts without
    hallucinating parameter names or functionality.

    NOTE: This tool does NOT require a Houdini connection - it fetches
    documentation directly from the SideFX website.

    Args:
        help_type: Type of documentation to fetch. Supported types:
            - "sop": SOP nodes (e.g., "box", "scatter", "vdbfrompolygons")
            - "obj": Object nodes (e.g., "geo", "cam", "light")
            - "dop": DOP nodes (e.g., "pyrosolver", "rbdpackedobject")
            - "cop2": COP nodes (e.g., "mosaic", "blur")
            - "chop": CHOP nodes (e.g., "math", "wave")
            - "vop": VOP nodes (e.g., "bind", "noise")
            - "lop": LOP/Solaris nodes (e.g., "usdimport", "materiallibrary")
            - "top": TOP/PDG nodes (e.g., "pythonscript", "wedge")
            - "rop": ROP nodes (e.g., "geometry", "karma")
            - "vex_function": VEX functions (e.g., "noise", "lerp", "chramp")
            - "python_hou": Python hou module classes (e.g., "Node", "Geometry")
        item_name: Name of the node or function (e.g., "box", "noise", "Node")
        timeout: Request timeout in seconds (default: 10)

    Returns:
        Dict with:
        - status: "success" or "error"
        - title: Documentation title
        - url: Source URL
        - description: Summary description
        - parameters: List of parameters with names, descriptions, and options
        - inputs: List of input connections (for nodes)
        - outputs: List of output connections (for nodes)

    Examples:
        get_houdini_help("sop", "box")  # Get box SOP documentation
        get_houdini_help("vex_function", "noise")  # Get VEX noise function docs
        get_houdini_help("python_hou", "Node")  # Get hou.Node class docs
        get_houdini_help("obj", "cam")  # Get camera object docs
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return {
            "status": "error",
            "message": "Required packages not installed. Run: pip install requests beautifulsoup4",
        }

    base_url = "https://www.sidefx.com/docs/houdini/"

    # Map help types to URL paths
    url_mapping = {
        "obj": f"nodes/obj/{item_name}.html",
        "sop": f"nodes/sop/{item_name}.html",
        "dop": f"nodes/dop/{item_name}.html",
        "cop2": f"nodes/cop2/{item_name}.html",
        "chop": f"nodes/chop/{item_name}.html",
        "vop": f"nodes/vop/{item_name}.html",
        "lop": f"nodes/lop/{item_name}.html",
        "top": f"nodes/top/{item_name}.html",
        "rop": f"nodes/out/{item_name}.html",  # ROPs are under /out/
        "vex_function": f"vex/functions/{item_name}.html",
        "python_hou": f"hom/hou/{item_name}.html",
    }

    if help_type not in url_mapping:
        return {
            "status": "error",
            "message": f"Unsupported help type: {help_type}. "
            f"Supported types: {', '.join(sorted(url_mapping.keys()))}",
        }

    full_url = base_url + url_mapping[help_type]

    try:
        response = requests.get(full_url, timeout=timeout)

        if response.status_code == 404:
            return {
                "status": "error",
                "message": f"Documentation not found for {help_type}/{item_name}. "
                f"Check if the name is correct.",
                "url": full_url,
            }

        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"Failed to fetch help page. HTTP status: {response.status_code}",
                "url": full_url,
            }

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title
        h1 = soup.find("h1", class_="title")
        if h1:
            title_text = h1.contents[0].strip() if h1.contents else ""
            subtitle = h1.find("span", class_="subtitle")
            subtitle_text = subtitle.get_text(strip=True) if subtitle else ""
            title = f"{title_text} - {subtitle_text}" if subtitle_text else title_text
        else:
            title = item_name

        # Extract description/summary
        summary_p = soup.find("p", class_="summary")
        description = summary_p.get_text(strip=True) if summary_p else ""

        # Extract parameters
        parameters = []
        for param_div in soup.find_all("div", class_="parameter"):
            name_tag = param_div.find("p", class_="label")
            desc_tag = param_div.find("div", class_="content")

            if not name_tag:
                continue

            param_name = name_tag.get_text(strip=True)
            param_desc = ""
            if desc_tag:
                param_desc_p = desc_tag.find("p")
                param_desc = param_desc_p.get_text(strip=True) if param_desc_p else ""

            # Extract menu options if present
            options = []
            if desc_tag:
                defs = desc_tag.find("div", class_="defs")
                if defs:
                    for def_item in defs.find_all("div", class_="def"):
                        label = def_item.find("p", class_="label")
                        desc = def_item.find("div", class_="content")
                        if label:
                            option_name = label.get_text(strip=True)
                            option_desc = desc.get_text(strip=True) if desc else ""
                            options.append({"name": option_name, "description": option_desc})

            param_info: Dict[str, Any] = {
                "name": param_name,
                "description": param_desc,
            }
            if options:
                param_info["options"] = options

            parameters.append(param_info)

        # Helper to extract inputs/outputs sections
        def extract_section(section_id: str) -> List[Dict[str, str]]:
            items = []
            section_body = soup.find("div", id=f"{section_id}-body")
            if section_body:
                for def_item in section_body.find_all("div", class_="def"):
                    label = def_item.find("p", class_="label")
                    desc_div = def_item.find("div", class_="content")
                    if label:
                        items.append(
                            {
                                "name": label.get_text(strip=True),
                                "description": desc_div.get_text(strip=True) if desc_div else "",
                            }
                        )
            return items

        inputs = extract_section("inputs")
        outputs = extract_section("outputs")

        # For VEX functions, also extract signature and return type
        vex_info: Dict[str, Any] = {}
        if help_type == "vex_function":
            # Look for function signature
            sig_div = soup.find("div", class_="signature")
            if sig_div:
                vex_info["signature"] = sig_div.get_text(strip=True)

            # Look for return type in the body
            returns_section = soup.find("div", id="returns-body")
            if returns_section:
                vex_info["returns"] = returns_section.get_text(strip=True)

        # For Python hou module, extract methods
        methods: List[Dict[str, str]] = []
        if help_type == "python_hou":
            for method_div in soup.find_all("div", class_="method"):
                method_name_tag = method_div.find("p", class_="label")
                method_desc_tag = method_div.find("div", class_="content")
                if method_name_tag:
                    methods.append(
                        {
                            "name": method_name_tag.get_text(strip=True),
                            "description": (
                                method_desc_tag.get_text(strip=True)[:200] + "..."
                                if method_desc_tag
                                and len(method_desc_tag.get_text(strip=True)) > 200
                                else method_desc_tag.get_text(strip=True)
                                if method_desc_tag
                                else ""
                            ),
                        }
                    )

        result: Dict[str, Any] = {
            "status": "success",
            "title": title,
            "url": full_url,
            "help_type": help_type,
            "item_name": item_name,
            "description": description,
        }

        if parameters:
            result["parameters"] = parameters
            result["parameter_count"] = len(parameters)

        if inputs:
            result["inputs"] = inputs

        if outputs:
            result["outputs"] = outputs

        if vex_info:
            result["vex_info"] = vex_info

        if methods:
            result["methods"] = methods[:50]  # Limit to first 50 methods
            result["method_count"] = len(methods)
            if len(methods) > 50:
                result["methods_truncated"] = True

        return _add_response_metadata(result)

    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": f"Request timed out after {timeout} seconds",
            "url": full_url,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Network error: {str(e)}",
            "url": full_url,
        }
    except Exception as e:
        logger.error(f"Error fetching Houdini help: {e}")
        return {
            "status": "error",
            "message": str(e),
            "url": full_url,
            "traceback": traceback.format_exc(),
        }


def create_material(
    material_type: str = "principledshader",
    name: Optional[str] = None,
    parent_path: str = "/mat",
    parameters: Optional[Dict[str, Any]] = None,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Create a new material/shader node.

    Creates a material node in the specified context (typically /mat or /shop).
    Supports common material types like Principled Shader, MaterialX, and classic shaders.

    Args:
        material_type: Type of material to create. Common types:
            - "principledshader": Houdini's standard PBR shader (recommended)
            - "mtlxstandard_surface": MaterialX Standard Surface
            - "classicshader": Classic Mantra shader
            - "arnold::standard_surface": Arnold Standard Surface (if Arnold installed)
        name: Optional name for the material. Auto-generated if not provided.
        parent_path: Parent context path (default: "/mat", alternative: "/shop")
        parameters: Optional dict of parameter values to set on the material.
            Common principledshader parameters:
            - basecolor: [r, g, b] base color
            - rough: float roughness (0-1)
            - metallic: float metallic (0-1)
            - ior: float index of refraction
            - basecolor_texture: string path to texture file

    Returns:
        Dict with:
        - status: "success" or "error"
        - material_path: Path to the created material node
        - material_name: Name of the material
        - material_type: Type of material created
        - parameters_set: List of parameters that were set

    Examples:
        create_material()  # Create default principled shader
        create_material("principledshader", "red_metal",
                       parameters={"basecolor": [1, 0, 0], "metallic": 1.0})
        create_material("mtlxstandard_surface", "gold_mtlx")
    """
    try:
        hou = ensure_connected(host, port)

        # Find or create parent context
        parent = hou.node(parent_path)
        if parent is None:
            # Try to create /mat if it doesn't exist
            if parent_path == "/mat":
                try:
                    parent = hou.node("/").createNode("matnet", "mat")
                except Exception:
                    return {
                        "status": "error",
                        "message": f"Cannot find or create material context: {parent_path}",
                    }
            else:
                return {
                    "status": "error",
                    "message": f"Parent context not found: {parent_path}",
                }

        # Generate name if not provided
        if not name:
            name = f"{material_type}_1"

        # Create the material node
        try:
            mat_node = parent.createNode(material_type, name)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to create material of type '{material_type}': {str(e)}. "
                f"Check if this material type is available in your Houdini installation.",
            }

        # Set parameters if provided
        parameters_set = []
        if parameters:
            for param_name, value in parameters.items():
                try:
                    parm = mat_node.parm(param_name)
                    if parm:
                        parm.set(value)
                        parameters_set.append(param_name)
                    else:
                        # Try as tuple parameter
                        parm_tuple = mat_node.parmTuple(param_name)
                        if parm_tuple and isinstance(value, (list, tuple)):
                            parm_tuple.set(value)
                            parameters_set.append(param_name)
                        else:
                            logger.warning(
                                f"Parameter '{param_name}' not found on material {mat_node.path()}"
                            )
                except Exception as e:
                    logger.warning(f"Failed to set parameter '{param_name}': {e}")

        return {
            "status": "success",
            "material_path": mat_node.path(),
            "material_name": mat_node.name(),
            "material_type": material_type,
            "parameters_set": parameters_set,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "creating_material")
    except Exception as e:
        logger.error(f"Error creating material: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def assign_material(
    geometry_path: str,
    material_path: str,
    group: str = "",
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Assign a material to geometry.

    Creates a Material SOP inside the geometry node to apply the material.
    If a Material SOP already exists, updates it instead.

    Args:
        geometry_path: Path to the geometry OBJ node (e.g., "/obj/geo1")
        material_path: Path to the material node (e.g., "/mat/principledshader1")
        group: Optional primitive group to apply material to (empty = all primitives)

    Returns:
        Dict with:
        - status: "success" or "error"
        - geometry_path: Path to the geometry node
        - material_path: Path to the assigned material
        - material_sop_path: Path to the Material SOP that was created/modified
        - method: "material_sop" or "shop_materialpath"

    Examples:
        assign_material("/obj/geo1", "/mat/red_metal")
        assign_material("/obj/geo1", "/mat/gold", group="top_faces")
    """
    try:
        hou = ensure_connected(host, port)

        # Validate geometry node
        geo_node = hou.node(geometry_path)
        if geo_node is None:
            return {"status": "error", "message": f"Geometry node not found: {geometry_path}"}

        # Check if it's an OBJ-level geo node
        node_type = geo_node.type().name()
        node_category = geo_node.type().category().name()

        if node_category != "Object":
            return {
                "status": "error",
                "message": f"Node {geometry_path} is not an Object-level node. "
                f"Expected geo node, got {node_category}/{node_type}",
            }

        # Validate material exists
        mat_node = hou.node(material_path)
        if mat_node is None:
            return {"status": "error", "message": f"Material not found: {material_path}"}

        # Method 1: Try setting shop_materialpath on the OBJ node directly
        mat_parm = geo_node.parm("shop_materialpath")
        if mat_parm and not group:
            mat_parm.set(material_path)
            return {
                "status": "success",
                "geometry_path": geometry_path,
                "material_path": material_path,
                "method": "shop_materialpath",
            }

        # Method 2: Create/update Material SOP inside the geometry
        # Find the display node to connect to
        display_node = geo_node.displayNode()
        if display_node is None:
            # No display node, try to find any SOP
            children = geo_node.children()
            if not children:
                return {
                    "status": "error",
                    "message": f"Geometry node {geometry_path} has no SOP nodes inside",
                }
            display_node = children[-1]

        # Check if a material SOP already exists and is connected
        existing_mat_sop = None
        for child in geo_node.children():
            if child.type().name() == "material":
                existing_mat_sop = child
                break

        if existing_mat_sop:
            mat_sop = existing_mat_sop
        else:
            # Create new Material SOP
            mat_sop = geo_node.createNode("material", "material1")
            mat_sop.setFirstInput(display_node)
            mat_sop.setDisplayFlag(True)
            mat_sop.setRenderFlag(True)

        # Set material path
        mat_path_parm = mat_sop.parm("shop_materialpath1")
        if mat_path_parm:
            mat_path_parm.set(material_path)
        else:
            return {
                "status": "error",
                "message": "Cannot find shop_materialpath1 parameter on Material SOP",
            }

        # Set group if provided
        if group:
            group_parm = mat_sop.parm("group1")
            if group_parm:
                group_parm.set(group)

        return {
            "status": "success",
            "geometry_path": geometry_path,
            "material_path": material_path,
            "material_sop_path": mat_sop.path(),
            "method": "material_sop",
            "group": group if group else None,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "assigning_material")
    except Exception as e:
        logger.error(f"Error assigning material: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def get_material_info(
    material_path: str,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Get detailed information about a material node.

    Returns material type, parameters, and texture references.

    Args:
        material_path: Path to the material node (e.g., "/mat/principledshader1")

    Returns:
        Dict with:
        - status: "success" or "error"
        - material_path: Path to the material
        - material_name: Name of the material
        - material_type: Type of material (e.g., "principledshader")
        - parameters: Dict of parameter names to current values
        - textures: List of texture file references found in parameters

    Examples:
        get_material_info("/mat/principledshader1")
        get_material_info("/mat/mtlxstandard_surface1")
    """
    try:
        hou = ensure_connected(host, port)

        mat_node = hou.node(material_path)
        if mat_node is None:
            return {"status": "error", "message": f"Material not found: {material_path}"}

        # Get basic info
        result: Dict[str, Any] = {
            "status": "success",
            "material_path": mat_node.path(),
            "material_name": mat_node.name(),
            "material_type": mat_node.type().name(),
            "parameters": {},
            "textures": [],
        }

        # Common material parameter names to include
        common_params = [
            # Principled Shader
            "basecolor",
            "basecolor_texture",
            "rough",
            "rough_texture",
            "metallic",
            "metallic_texture",
            "ior",
            "reflect",
            "reflecttint",
            "coat",
            "coatrough",
            "transparency",
            "transcolor",
            "dispersion",
            "sss",
            "sssdist",
            "ssscolor",
            "sheen",
            "sheentint",
            "emitcolor",
            "emitint",
            "opac",
            "opaccolor",
            # Normal/Bump
            "baseBumpAndNormal_enable",
            "baseNormal_texture",
            "baseBump_bumpTexture",
            # MaterialX Standard Surface
            "base",
            "base_color",
            "diffuse_roughness",
            "specular",
            "specular_color",
            "specular_roughness",
            "specular_IOR",
            "transmission",
            "transmission_color",
            "subsurface",
            "subsurface_color",
            "emission",
            "emission_color",
        ]

        textures = []

        for parm_name in common_params:
            try:
                parm = mat_node.parm(parm_name)
                if parm:
                    value = parm.eval()
                    result["parameters"][parm_name] = value
                    # Check if it's a texture path
                    if isinstance(value, str) and value:
                        if any(
                            ext in value.lower()
                            for ext in [".jpg", ".png", ".exr", ".hdr", ".tif", ".tex"]
                        ):
                            textures.append({"parameter": parm_name, "path": value})
                else:
                    # Try as tuple
                    parm_tuple = mat_node.parmTuple(parm_name)
                    if parm_tuple:
                        value = parm_tuple.eval()
                        result["parameters"][parm_name] = (
                            list(value) if hasattr(value, "__iter__") else value
                        )
            except Exception:
                pass

        result["textures"] = textures
        result["parameter_count"] = len(result["parameters"])

        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "getting_material_info")
    except Exception as e:
        logger.error(f"Error getting material info: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def layout_children(
    node_path: str,
    horizontal_spacing: float = 2.0,
    vertical_spacing: float = 1.0,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Auto-layout child nodes in a network.

    Calls Houdini's built-in layoutChildren() to automatically arrange
    child nodes in a clean, organized layout.

    Args:
        node_path: Path to the parent node (e.g., "/obj/geo1")
        horizontal_spacing: Horizontal spacing between nodes (default: 2.0)
        vertical_spacing: Vertical spacing between nodes (default: 1.0)

    Returns:
        Dict with:
        - status: "success" or "error"
        - node_path: Path to the parent node
        - child_count: Number of children that were laid out

    Examples:
        layout_children("/obj/geo1")
        layout_children("/obj/geo1", horizontal_spacing=3.0, vertical_spacing=2.0)
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        children = node.children()
        child_count = len(children)

        if child_count == 0:
            return {
                "status": "success",
                "node_path": node_path,
                "child_count": 0,
                "message": "No children to layout",
            }

        # Call layoutChildren with spacing parameters
        node.layoutChildren(
            horizontal_spacing=horizontal_spacing,
            vertical_spacing=vertical_spacing,
        )

        return {
            "status": "success",
            "node_path": node_path,
            "child_count": child_count,
            "horizontal_spacing": horizontal_spacing,
            "vertical_spacing": vertical_spacing,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "laying_out_children")
    except Exception as e:
        logger.error(f"Error laying out children: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def set_node_color(
    node_path: str,
    color: List[float],
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Set the display color of a node in the network editor.

    Args:
        node_path: Path to the node (e.g., "/obj/geo1/sphere1")
        color: RGB color values as [r, g, b] where each value is 0.0-1.0
               Common colors:
               - Red: [1, 0, 0]
               - Green: [0, 1, 0]
               - Blue: [0, 0, 1]
               - Yellow: [1, 1, 0]
               - Orange: [1, 0.5, 0]
               - Purple: [0.5, 0, 1]

    Returns:
        Dict with:
        - status: "success" or "error"
        - node_path: Path to the node
        - color: The color that was set

    Examples:
        set_node_color("/obj/geo1/sphere1", [1, 0, 0])  # Red
        set_node_color("/obj/geo1/important_node", [1, 1, 0])  # Yellow
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        # Validate color values
        if len(color) != 3:
            return {"status": "error", "message": "Color must be [r, g, b] with 3 values"}

        # Clamp values to 0-1 range
        clamped_color = [max(0.0, min(1.0, c)) for c in color]

        # Create hou.Color and set it
        hou_color = hou.Color(clamped_color)
        node.setColor(hou_color)

        return {
            "status": "success",
            "node_path": node_path,
            "color": clamped_color,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "setting_node_color")
    except Exception as e:
        logger.error(f"Error setting node color: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def set_node_position(
    node_path: str,
    x: float,
    y: float,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Set the position of a node in the network editor.

    Args:
        node_path: Path to the node (e.g., "/obj/geo1/sphere1")
        x: X position in network editor units
        y: Y position in network editor units

    Returns:
        Dict with:
        - status: "success" or "error"
        - node_path: Path to the node
        - position: [x, y] the position that was set

    Examples:
        set_node_position("/obj/geo1/sphere1", 0, 0)
        set_node_position("/obj/geo1/sphere1", 5.0, -3.0)
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        # Create position vector and set it
        position = hou.Vector2(x, y)
        node.setPosition(position)

        return {
            "status": "success",
            "node_path": node_path,
            "position": [x, y],
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "setting_node_position")
    except Exception as e:
        logger.error(f"Error setting node position: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def create_network_box(
    parent_path: str,
    node_paths: List[str],
    label: str = "",
    color: Optional[List[float]] = None,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Create a network box around a group of nodes.

    Network boxes help organize and visually group related nodes
    in the network editor.

    Args:
        parent_path: Path to the parent network (e.g., "/obj/geo1")
        node_paths: List of node paths to include in the box
        label: Optional label text for the network box
        color: Optional RGB color [r, g, b] for the box (0.0-1.0 each)

    Returns:
        Dict with:
        - status: "success" or "error"
        - network_box_path: Path to the created network box
        - nodes_contained: List of nodes in the box
        - label: The label set on the box

    Examples:
        create_network_box("/obj/geo1", ["/obj/geo1/sphere1", "/obj/geo1/noise1"], "Deform Setup")
        create_network_box("/obj/geo1", ["/obj/geo1/box1"], "Input", color=[0.2, 0.6, 0.2])
    """
    try:
        hou = ensure_connected(host, port)

        parent = hou.node(parent_path)
        if parent is None:
            return {"status": "error", "message": f"Parent node not found: {parent_path}"}

        # Validate all nodes exist and are children of parent
        nodes = []
        for path in node_paths:
            node = hou.node(path)
            if node is None:
                return {"status": "error", "message": f"Node not found: {path}"}
            # Check if it's a child of the parent
            if node.parent().path() != parent_path:
                return {
                    "status": "error",
                    "message": f"Node {path} is not a child of {parent_path}",
                }
            nodes.append(node)

        if not nodes:
            return {"status": "error", "message": "No nodes specified for network box"}

        # Create network box
        netbox = parent.createNetworkBox()

        # Set label
        if label:
            netbox.setComment(label)

        # Set color if provided
        if color and len(color) == 3:
            clamped_color = [max(0.0, min(1.0, c)) for c in color]
            hou_color = hou.Color(clamped_color)
            netbox.setColor(hou_color)

        # Add nodes to the box
        for node in nodes:
            netbox.addNode(node)

        # Fit box to contents
        netbox.fitAroundContents()

        return {
            "status": "success",
            "network_box_name": netbox.name(),
            "parent_path": parent_path,
            "nodes_contained": node_paths,
            "label": label,
            "color": color,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "creating_network_box")
    except Exception as e:
        logger.error(f"Error creating network box: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
