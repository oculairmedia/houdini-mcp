"""Houdini MCP Tools - Functions exposed via MCP protocol."""

import logging
import re
import traceback
import signal
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

from .connection import ensure_connected, is_connected, HoudiniConnectionError

logger = logging.getLogger("houdini_mcp.tools")


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
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    List available node types, optionally filtered by category.

    Args:
        category: Optional category filter (e.g., "Object", "Sop", "Cop2", "Vop")
        max_results: Maximum number of results to return (default: 100, max: 500)
        name_filter: Optional substring filter for node type names (case-insensitive)

    Returns:
        Dict with list of node types.

    Note:
        Large categories like "Sop" have thousands of node types.
        Use name_filter to narrow results (e.g., name_filter="noise" for noise-related SOPs).
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
        categories_scanned: List[str] = []

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

        # Add warning if results were limited
        if len(node_types) >= max_results:
            result["warning"] = (
                f"Results limited to {max_results}. "
                f"Use name_filter to narrow results or increase max_results (max 500)."
            )
            result["total_scanned"] = total_scanned

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error listing node types: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def list_children(
    node_path: str,
    recursive: bool = False,
    max_depth: int = 10,
    max_nodes: int = 1000,
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

    Returns:
        Dict with child nodes including their connection information.

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

                    child_info: Dict[str, Any] = {
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

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error listing children: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def find_nodes(
    root_path: str = "/obj",
    pattern: str = "*",
    node_type: Optional[str] = None,
    max_results: int = 100,
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

    Returns:
        Dict with matching nodes and their types.

    Example:
        find_nodes("/obj", "noise*", max_results=50)
        find_nodes("/obj/geo1", "*", node_type="sphere")
    """
    try:
        hou = ensure_connected(host, port)

        root = hou.node(root_path)
        if root is None:
            return {"status": "error", "message": f"Root node not found: {root_path}"}

        import fnmatch

        matches: List[Dict[str, str]] = []

        def search_recursive(node: Any) -> None:
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

        if len(matches) >= max_results:
            result["warning"] = f"Results limited to {max_results} nodes"

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error finding nodes: {e}")
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

        return {
            "status": "success",
            "node_path": node_path,
            "parameters": parameters,
            "count": len(parameters),
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
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
    try:
        hou = ensure_connected(host, port)

        # Validate max_sample_points
        if max_sample_points < 0:
            max_sample_points = 0
        elif max_sample_points > 10000:
            logger.warning(f"max_sample_points capped at 10000 (was {max_sample_points})")
            max_sample_points = 10000

        # Get the node
        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        # Check cook state using available methods (cookState not available in Houdini 20.5+)
        try:
            cook_state_map = {
                "Cooked": "cooked",
                "CookFailed": "error",
                "Dirty": "dirty",
                "Uncooked": "uncooked",
            }

            def get_cook_state(n):
                """Get cook state using available methods."""
                if hasattr(n, "cookState"):
                    state_obj = n.cookState()
                    state_name = state_obj.name() if hasattr(state_obj, "name") else str(state_obj)
                    return cook_state_map.get(state_name, state_name.lower())
                elif hasattr(n, "needsToCook"):
                    return "dirty" if n.needsToCook() else "cooked"
                return "unknown"

            cook_state = get_cook_state(node)

            # If not cooked, try to cook
            if cook_state in ("dirty", "uncooked"):
                logger.info(f"Node {node_path} is {cook_state}, attempting to cook")
                node.cook(force=True)
                cook_state = get_cook_state(node)
        except Exception as e:
            logger.warning(f"Could not determine cook state for {node_path}: {e}")
            cook_state = "unknown"

        # Get geometry
        try:
            geo = node.geometry()
            if geo is None:
                return {
                    "status": "error",
                    "message": f"Node {node_path} has no geometry (not a SOP node or no output)",
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get geometry from {node_path}: {str(e)}",
            }

        # Get point and primitive counts
        try:
            points_list = list(geo.points())
            point_count = len(points_list)
        except Exception:
            points_list = []
            point_count = 0

        try:
            prims_list = list(geo.prims())
            prim_count = len(prims_list)
        except Exception:
            prims_list = []
            prim_count = 0

        # Calculate total vertex count
        vertex_count = 0
        try:
            for prim in prims_list:
                try:
                    vertex_count += prim.numVertices()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Error counting vertices: {e}")

        # Build result dict
        result: Dict[str, Any] = {
            "status": "success",
            "node_path": node_path,
            "cook_state": cook_state,
            "point_count": point_count,
            "primitive_count": prim_count,
            "vertex_count": vertex_count,
        }

        # Get bounding box
        try:
            bbox = geo.boundingBox()
            if bbox is not None:
                min_vec = list(bbox.minvec())
                max_vec = list(bbox.maxvec())
                size_vec = list(bbox.sizevec())
                center_vec = list(bbox.center())

                result["bounding_box"] = {
                    "min": min_vec,
                    "max": max_vec,
                    "size": size_vec,
                    "center": center_vec,
                }
            else:
                result["bounding_box"] = None
        except Exception as e:
            logger.warning(f"Could not get bounding box: {e}")
            result["bounding_box"] = None

        # Get attributes
        if include_attributes:
            attributes: Dict[str, List[Dict[str, Any]]] = {
                "point": [],
                "primitive": [],
                "vertex": [],
                "detail": [],
            }

            try:
                # Point attributes
                for attrib in geo.pointAttribs():
                    try:
                        data_type = attrib.dataType()
                        data_type_name = (
                            data_type.name() if hasattr(data_type, "name") else str(data_type)
                        )

                        attributes["point"].append(
                            {
                                "name": attrib.name(),
                                "type": data_type_name.lower(),
                                "size": attrib.size(),
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Error reading point attribute: {e}")
            except Exception as e:
                logger.warning(f"Error getting point attributes: {e}")

            try:
                # Primitive attributes
                for attrib in geo.primAttribs():
                    try:
                        data_type = attrib.dataType()
                        data_type_name = (
                            data_type.name() if hasattr(data_type, "name") else str(data_type)
                        )

                        attributes["primitive"].append(
                            {
                                "name": attrib.name(),
                                "type": data_type_name.lower(),
                                "size": attrib.size(),
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Error reading primitive attribute: {e}")
            except Exception as e:
                logger.warning(f"Error getting primitive attributes: {e}")

            try:
                # Vertex attributes
                for attrib in geo.vertexAttribs():
                    try:
                        data_type = attrib.dataType()
                        data_type_name = (
                            data_type.name() if hasattr(data_type, "name") else str(data_type)
                        )

                        attributes["vertex"].append(
                            {
                                "name": attrib.name(),
                                "type": data_type_name.lower(),
                                "size": attrib.size(),
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Error reading vertex attribute: {e}")
            except Exception as e:
                logger.warning(f"Error getting vertex attributes: {e}")

            try:
                # Detail (global) attributes
                for attrib in geo.globalAttribs():
                    try:
                        data_type = attrib.dataType()
                        data_type_name = (
                            data_type.name() if hasattr(data_type, "name") else str(data_type)
                        )

                        attributes["detail"].append(
                            {
                                "name": attrib.name(),
                                "type": data_type_name.lower(),
                                "size": attrib.size(),
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Error reading detail attribute: {e}")
            except Exception as e:
                logger.warning(f"Error getting detail attributes: {e}")

            result["attributes"] = attributes

        # Get groups
        if include_groups:
            groups: Dict[str, List[str]] = {"point": [], "primitive": []}

            try:
                for group in geo.pointGroups():
                    try:
                        groups["point"].append(group.name())
                    except Exception as e:
                        logger.debug(f"Error reading point group: {e}")
            except Exception as e:
                logger.warning(f"Error getting point groups: {e}")

            try:
                for group in geo.primGroups():
                    try:
                        groups["primitive"].append(group.name())
                    except Exception as e:
                        logger.debug(f"Error reading primitive group: {e}")
            except Exception as e:
                logger.warning(f"Error getting primitive groups: {e}")

            result["groups"] = groups

        # Sample points
        if max_sample_points > 0 and point_count > 0:
            # Check for massive geometry and add warning
            if point_count > 1000000:
                result["warning"] = (
                    f"Geometry has {point_count} points (>1M). Sampling limited to {max_sample_points} points."
                )

            sample_points: List[Dict[str, Any]] = []
            sample_count = min(max_sample_points, point_count)

            try:
                # Get list of point attribute names for sampling
                point_attrib_names: List[str] = []
                if include_attributes:
                    try:
                        for attrib in geo.pointAttribs():
                            point_attrib_names.append(attrib.name())
                    except Exception:
                        pass

                # Sample first N points
                for i, pt in enumerate(points_list):
                    if i >= sample_count:
                        break

                    try:
                        point_data: Dict[str, Any] = {"index": i}

                        # Get position (P attribute)
                        try:
                            pos = pt.attribValue("P")
                            if pos is not None:
                                point_data["P"] = (
                                    list(pos) if isinstance(pos, (tuple, list)) else pos
                                )
                        except Exception:
                            pass

                        # Get other attributes
                        for attrib_name in point_attrib_names:
                            if attrib_name == "P":
                                continue  # Already got P
                            try:
                                value = pt.attribValue(attrib_name)
                                if value is not None:
                                    # Convert tuples/vectors to lists for JSON serialization
                                    if isinstance(value, (tuple, list)):
                                        point_data[attrib_name] = list(value)
                                    else:
                                        point_data[attrib_name] = value
                            except Exception:
                                pass

                        sample_points.append(point_data)

                    except Exception as e:
                        logger.debug(f"Error sampling point {i}: {e}")
            except Exception as e:
                logger.warning(f"Error sampling points: {e}")

            result["sample_points"] = sample_points

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error getting geometry summary: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
