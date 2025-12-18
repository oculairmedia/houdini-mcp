"""Houdini MCP Server - Main server entry point."""

import os
import logging
from typing import Any, Dict, Optional, Literal

from fastmcp import FastMCP

from .connection import (
    ensure_connected, 
    is_connected, 
    disconnect,
    get_connection_info,
    ping
)
from . import tools

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("houdini_mcp.server")

# Environment configuration
HOUDINI_HOST = os.getenv("HOUDINI_HOST", "localhost")
HOUDINI_PORT = int(os.getenv("HOUDINI_PORT", "18811"))

# Create FastMCP instance
mcp = FastMCP("Houdini MCP")


@mcp.tool()
def get_scene_info() -> Dict[str, Any]:
    """
    Get current Houdini scene information.
    
    Returns information about the currently open scene including:
    - Hip file path
    - Houdini version
    - List of nodes in /obj
    """
    return tools.get_scene_info(HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def create_node(
    node_type: str,
    parent_path: str = "/obj",
    name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new node in the Houdini scene.
    
    Args:
        node_type: The type of node to create (e.g., "geo", "null", "cam")
        parent_path: The parent node path (default: "/obj")
        name: Optional name for the new node
        
    Examples:
        - create_node("geo") -> Creates a geometry container at /obj
        - create_node("sphere", "/obj/geo1") -> Creates a sphere SOP inside geo1
        - create_node("cam", name="render_cam") -> Creates a camera named render_cam
    """
    return tools.create_node(node_type, parent_path, name, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def execute_code(code: str, capture_diff: bool = True) -> Dict[str, Any]:
    """
    Execute Python code in Houdini with scene change tracking.
    
    The 'hou' module is available in the execution context.
    Use this for complex operations that aren't covered by other tools.
    
    Args:
        code: Python code to execute
        capture_diff: If True, captures before/after scene state and returns changes
        
    Example:
        execute_code('''
            obj = hou.node("/obj")
            geo = obj.createNode("geo", "my_geometry")
            sphere = geo.createNode("sphere")
            sphere.parm("radx").set(2.0)
            sphere.setDisplayFlag(True)
            sphere.setRenderFlag(True)
        ''')
        
    Returns:
        Dict with status, stdout, stderr, and scene_changes (if capture_diff=True)
    """
    return tools.execute_code(code, HOUDINI_HOST, HOUDINI_PORT, capture_diff)


@mcp.tool()
def set_parameter(
    node_path: str,
    param_name: str,
    value: Any
) -> Dict[str, Any]:
    """
    Set a parameter value on a node.
    
    Args:
        node_path: Full path to the node (e.g., "/obj/geo1/sphere1")
        param_name: Name of the parameter (e.g., "radx", "tx", "scale")
        value: Value to set (number, string, or tuple for vector params)
        
    Examples:
        - set_parameter("/obj/geo1/sphere1", "radx", 2.5)
        - set_parameter("/obj/cam1", "tx", 10.0)
        - set_parameter("/obj/geo1", "t", [1.0, 2.0, 3.0])  # Vector param
    """
    return tools.set_parameter(node_path, param_name, value, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def get_node_info(
    node_path: str,
    include_params: bool = True
) -> Dict[str, Any]:
    """
    Get detailed information about a node.
    
    Args:
        node_path: Full path to the node
        include_params: Whether to include parameter values (default: True)
        
    Returns:
        Node information including type, children, connections, flags, and parameters.
    """
    return tools.get_node_info(node_path, include_params, 50, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def delete_node(node_path: str) -> Dict[str, Any]:
    """
    Delete a node from the scene.
    
    Args:
        node_path: Full path to the node to delete
        
    Warning: This operation cannot be undone via this API.
    """
    return tools.delete_node(node_path, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def save_scene(file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Save the current Houdini scene.
    
    Args:
        file_path: Optional path to save to. If not provided, saves to current file.
        
    Example:
        - save_scene() -> Saves to current file
        - save_scene("/path/to/scene.hip") -> Saves to specified path
    """
    return tools.save_scene(file_path, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def load_scene(file_path: str) -> Dict[str, Any]:
    """
    Load a Houdini scene file.
    
    Args:
        file_path: Path to the .hip file to load
    """
    return tools.load_scene(file_path, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def new_scene() -> Dict[str, Any]:
    """
    Create a new empty Houdini scene.
    
    Warning: This will clear the current scene. Make sure to save first if needed.
    """
    return tools.new_scene(HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def serialize_scene(
    root_path: str = "/obj",
    include_params: bool = False
) -> Dict[str, Any]:
    """
    Serialize the scene structure to a dictionary.
    
    Useful for comparing scene states before and after operations,
    or for understanding the scene hierarchy.
    
    Args:
        root_path: Root node path to serialize from (default: "/obj")
        include_params: Include parameter values (can be verbose, default: False)
    """
    return tools.serialize_scene(root_path, include_params, 10, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def get_last_scene_diff() -> Dict[str, Any]:
    """
    Get the scene diff from the last execute_code call.
    
    Shows what nodes were added, removed, or modified during the last
    code execution. Useful for understanding what changes were made.
    """
    return tools.get_last_scene_diff()


@mcp.tool()
def list_node_types(category: Optional[str] = None) -> Dict[str, Any]:
    """
    List available Houdini node types.
    
    Args:
        category: Optional category filter (e.g., "Object", "Sop", "Cop2", "Vop")
        
    Returns:
        List of node types with their categories and descriptions.
    """
    return tools.list_node_types(category, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def check_connection() -> Dict[str, Any]:
    """
    Check Houdini connection status with detailed info.
    
    Returns connection status, Houdini version, build info, and current hip file.
    Attempts to connect if not already connected.
    """
    try:
        # First try a quick ping
        if not is_connected():
            # Try to connect
            ensure_connected(HOUDINI_HOST, HOUDINI_PORT)
        
        # Get detailed connection info
        info = get_connection_info(HOUDINI_HOST, HOUDINI_PORT)
        info["status"] = "connected" if info["connected"] else "disconnected"
        return info
        
    except Exception as e:
        return {
            "status": "disconnected",
            "host": HOUDINI_HOST,
            "port": HOUDINI_PORT,
            "error": str(e)
        }


@mcp.tool()
def ping_houdini() -> Dict[str, Any]:
    """
    Quick connectivity test to Houdini.
    
    Returns True if Houdini RPC server is reachable.
    Does not maintain a persistent connection.
    """
    reachable = ping(HOUDINI_HOST, HOUDINI_PORT)
    return {
        "status": "success" if reachable else "error",
        "reachable": reachable,
        "host": HOUDINI_HOST,
        "port": HOUDINI_PORT
    }


def run_server(transport: str = "http", port: int = 3055) -> None:
    """Run the MCP server."""
    logger.info(f"Starting Houdini MCP Server on {transport}://0.0.0.0:{port}")
    logger.info(f"Houdini connection target: {HOUDINI_HOST}:{HOUDINI_PORT}")
    logger.info(f"Log level: {log_level}")
    
    # Cast transport to literal type for FastMCP
    transport_literal: Literal["stdio", "http", "sse", "streamable-http"] = "http"
    if transport in ("stdio", "http", "sse", "streamable-http"):
        transport_literal = transport  # type: ignore
    
    mcp.run(transport=transport_literal, port=port)


if __name__ == "__main__":
    run_server()
