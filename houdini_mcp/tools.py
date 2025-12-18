"""Houdini MCP Tools - Functions exposed via MCP protocol."""

import logging
import traceback
from typing import Any, Dict, List, Optional
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

from .connection import ensure_connected, is_connected, HoudiniConnectionError

logger = logging.getLogger("houdini_mcp.tools")


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
        
        nodes = []
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
        return {"status": "error", "message": str(e)}


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
        return {"status": "error", "message": str(e)}


def execute_code(
    code: str,
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
    """
    Execute Python code in Houdini.
    
    Args:
        code: Python code to execute. The 'hou' module is available.
        
    Returns:
        Dict with execution result including any stdout/stderr output.
    """
    try:
        hou = ensure_connected(host, port)
        
        # Capture stdout and stderr
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, {"hou": hou})
            
            return {
                "status": "success",
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue()
            }
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
        return {"status": "error", "message": str(e)}


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
            return {
                "status": "error",
                "message": f"Parameter not found: {param_name} on {node_path}"
            }
        
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
        return {"status": "error", "message": str(e)}


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
        
        info = {
            "status": "success",
            "path": node.path(),
            "name": node.name(),
            "type": node.type().name(),
            "type_description": node.type().description(),
            "children": [child.name() for child in node.children()],
            "inputs": [inp.path() if inp else None for inp in node.inputs()],
            "outputs": [out.path() for out in node.outputs()]
        }
        
        if include_params:
            params = {}
            for i, parm in enumerate(node.parms()):
                if i >= max_params:
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
        return {"status": "error", "message": str(e)}


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
        return {"status": "error", "message": str(e)}


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
            "message": f"Scene saved",
            "file_path": saved_path
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error saving scene: {e}")
        return {"status": "error", "message": str(e)}


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
            "message": f"Scene loaded",
            "file_path": file_path
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error loading scene: {e}")
        return {"status": "error", "message": str(e)}


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
        return {"status": "error", "message": str(e)}


def serialize_scene(
    root_path: str = "/obj",
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
    """
    Serialize the scene structure to a dictionary (useful for diffs/comparisons).
    
    Args:
        root_path: Root node path to serialize from
        
    Returns:
        Dict with serialized scene structure.
    """
    try:
        hou = ensure_connected(host, port)
        
        def node_to_dict(node, depth=0, max_depth=10):
            if depth > max_depth:
                return {"path": node.path(), "truncated": True}
            
            return {
                "path": node.path(),
                "type": node.type().name(),
                "name": node.name(),
                "children": [
                    node_to_dict(child, depth + 1, max_depth)
                    for child in node.children()
                ]
            }
        
        root = hou.node(root_path)
        if root is None:
            return {
                "status": "error",
                "message": f"Root node not found: {root_path}"
            }
        
        return {
            "status": "success",
            "root": root_path,
            "structure": node_to_dict(root)
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error serializing scene: {e}")
        return {"status": "error", "message": str(e)}
