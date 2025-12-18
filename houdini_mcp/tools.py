"""Houdini MCP Tools - Functions exposed via MCP protocol."""

import logging
import traceback
from typing import Any, Dict, List, Optional, Set
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

from .connection import ensure_connected, is_connected, HoudiniConnectionError

logger = logging.getLogger("houdini_mcp.tools")


# Scene state for before/after comparisons (ported from OpenWebUI pipeline)
_before_scene: List[Dict[str, Any]] = []
_after_scene: List[Dict[str, Any]] = []


def _node_to_dict(node: Any, include_params: bool = True, max_params: int = 100) -> Dict[str, Any]:
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
    
    if include_params:
        params: Dict[str, Any] = {}
        for i, parm in enumerate(node.parms()):
            if i >= max_params:
                break
            try:
                params[parm.name()] = parm.eval()
            except Exception:
                params[parm.name()] = "<unevaluable>"
        result["parameters"] = params
    
    # Recursively serialize children
    result["children"] = [
        _node_to_dict(child, include_params=False)  # Don't include params for children to reduce size
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
    return [_node_to_dict(child) for child in obj.children()]


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
        "has_changes": bool(added or removed or modified)
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
                nodes.append({
                    "path": child.path(),
                    "type": child.type().name(),
                    "name": child.name()
                })
        
        return {
            "status": "success",
            "hip_file": hip_file if hip_file else "untitled.hip",
            "houdini_version": hou.applicationVersionString(),
            "node_count": len(nodes),
            "nodes": nodes
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
    port: int = 18811
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
            return {
                "status": "error",
                "message": f"Parent node not found: {parent_path}"
            }
        
        if name:
            node = parent.createNode(node_type, name)
        else:
            node = parent.createNode(node_type)
        
        return {
            "status": "success",
            "node_path": node.path(),
            "node_type": node.type().name(),
            "node_name": node.name()
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error creating node: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def execute_code(
    code: str,
    host: str = "localhost",
    port: int = 18811,
    capture_diff: bool = True
) -> Dict[str, Any]:
    """
    Execute Python code in Houdini with optional scene diff tracking.
    
    Args:
        code: Python code to execute. The 'hou' module is available.
        capture_diff: If True, captures before/after scene state for comparison
        
    Returns:
        Dict with execution result including stdout/stderr and scene changes.
    """
    global _before_scene, _after_scene
    
    try:
        hou = ensure_connected(host, port)
        
        # Capture scene state before execution (from OpenWebUI pipeline pattern)
        if capture_diff:
            _before_scene = _serialize_scene_state(hou)
        
        # Capture stdout and stderr
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        
        try:
            # Execute in a namespace with hou available
            exec_globals = {"hou": hou, "__builtins__": __builtins__}
            
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, exec_globals)
            
            result: Dict[str, Any] = {
                "status": "success",
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue()
            }
            
            # Capture scene state after execution and compute diff
            if capture_diff:
                _after_scene = _serialize_scene_state(hou)
                result["scene_changes"] = _get_scene_diff(_before_scene, _after_scene)
            
            return result
            
        except Exception as exec_error:
            return {
                "status": "error",
                "message": str(exec_error),
                "traceback": traceback.format_exc(),
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue()
            }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error executing code: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def set_parameter(
    node_path: str,
    param_name: str,
    value: Any,
    host: str = "localhost",
    port: int = 18811
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
            return {
                "status": "error",
                "message": f"Node not found: {node_path}"
            }
        
        parm = node.parm(param_name)
        if parm is None:
            # Try parmTuple for vector parameters
            parm_tuple = node.parmTuple(param_name)
            if parm_tuple is None:
                return {
                    "status": "error",
                    "message": f"Parameter not found: {param_name} on {node_path}"
                }
            # Set tuple value
            if isinstance(value, (list, tuple)):
                parm_tuple.set(value)
            else:
                return {
                    "status": "error",
                    "message": f"Parameter {param_name} is a tuple, provide a list/tuple value"
                }
        else:
            parm.set(value)
        
        return {
            "status": "success",
            "node_path": node_path,
            "param_name": param_name,
            "value": value
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
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
    """
    Get detailed information about a node.
    
    Args:
        node_path: Path to the node
        include_params: Whether to include parameter values
        max_params: Maximum number of parameters to return
        
    Returns:
        Dict with node information.
    """
    try:
        hou = ensure_connected(host, port)
        
        node = hou.node(node_path)
        if node is None:
            return {
                "status": "error",
                "message": f"Node not found: {node_path}"
            }
        
        info: Dict[str, Any] = {
            "status": "success",
            "path": node.path(),
            "name": node.name(),
            "type": node.type().name(),
            "type_description": node.type().description(),
            "children": [child.name() for child in node.children()],
            "inputs": [inp.path() if inp else None for inp in node.inputs()],
            "outputs": [out.path() for out in node.outputs()],
            "is_displayed": node.isDisplayFlagSet() if hasattr(node, 'isDisplayFlagSet') else None,
            "is_rendered": node.isRenderFlagSet() if hasattr(node, 'isRenderFlagSet') else None
        }
        
        if include_params:
            params: Dict[str, Any] = {}
            for i, parm in enumerate(node.parms()):
                if i >= max_params:
                    params["_truncated"] = True
                    break
                try:
                    params[parm.name()] = parm.eval()
                except Exception:
                    params[parm.name()] = "<unable to evaluate>"
            info["parameters"] = params
        
        return info
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error getting node info: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def delete_node(
    node_path: str,
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
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
            return {
                "status": "error",
                "message": f"Node not found: {node_path}"
            }
        
        node_name = node.name()
        node.destroy()
        
        return {
            "status": "success",
            "message": f"Deleted node: {node_name}",
            "deleted_path": node_path
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error deleting node: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def save_scene(
    file_path: Optional[str] = None,
    host: str = "localhost",
    port: int = 18811
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
        
        return {
            "status": "success",
            "message": "Scene saved",
            "file_path": saved_path
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error saving scene: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def load_scene(
    file_path: str,
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
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
        
        return {
            "status": "success",
            "message": "Scene loaded",
            "file_path": file_path
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error loading scene: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def new_scene(
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
    """
    Create a new empty Houdini scene.
    
    Returns:
        Dict with result.
    """
    try:
        hou = ensure_connected(host, port)
        
        hou.hipFile.clear()
        
        return {
            "status": "success",
            "message": "New scene created"
        }
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
    port: int = 18811
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
                        params[parm.name()] = parm.eval()
                    except Exception:
                        params[parm.name()] = "<unevaluable>"
                result["parameters"] = params
            
            result["children"] = [
                node_to_dict_recursive(child, depth + 1)
                for child in node.children()
            ]
            
            return result
        
        root = hou.node(root_path)
        if root is None:
            return {
                "status": "error",
                "message": f"Root node not found: {root_path}"
            }
        
        return {
            "status": "success",
            "root": root_path,
            "structure": node_to_dict_recursive(root)
        }
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
            "message": "No scene diff available. Run execute_code with capture_diff=True first."
        }
    
    return {
        "status": "success",
        "diff": _get_scene_diff(_before_scene, _after_scene)
    }


def list_node_types(
    category: Optional[str] = None,
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
    """
    List available node types, optionally filtered by category.
    
    Args:
        category: Optional category filter (e.g., "Object", "Sop", "Cop2")
        
    Returns:
        Dict with list of node types.
    """
    try:
        hou = ensure_connected(host, port)
        
        node_types: List[Dict[str, str]] = []
        
        for node_type in hou.nodeTypeCategories().items():
            cat_name, cat = node_type
            if category and cat_name.lower() != category.lower():
                continue
            
            for type_name, type_obj in cat.nodeTypes().items():
                node_types.append({
                    "category": cat_name,
                    "name": type_name,
                    "description": type_obj.description()
                })
        
        return {
            "status": "success",
            "count": len(node_types),
            "node_types": node_types[:100]  # Limit to first 100 to avoid huge responses
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error listing node types: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
