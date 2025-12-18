"""Houdini MCP Server - Main server entry point."""

import os
import logging
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from .connection import ensure_connected, is_connected, disconnect
from . import tools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
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
def execute_code(code: str) -> Dict[str, Any]:
    """
    Execute Python code in Houdini.
    
    The 'hou' module is available in the execution context.
    Use this for complex operations that aren't covered by other tools.
    
    Args:
        code: Python code to execute
        
    Example:
        execute_code('''
            obj = hou.node("/obj")
            geo = obj.createNode("geo", "my_geometry")
            sphere = geo.createNode("sphere")
            sphere.parm("radx").set(2.0)
        ''')
    """
    return tools.execute_code(code, HOUDINI_HOST, HOUDINI_PORT)


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
        Node information including type, children, connections, and parameters.
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
def serialize_scene(root_path: str = "/obj") -> Dict[str, Any]:
    """
    Serialize the scene structure to a dictionary.
    
    Useful for comparing scene states before and after operations.
    
    Args:
        root_path: Root node path to serialize from (default: "/obj")
    """
    return tools.serialize_scene(root_path, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def check_connection() -> Dict[str, Any]:
    """
    Check if connected to Houdini.
    
    Returns connection status and attempts to connect if not already connected.
    """
    try:
        if is_connected():
            hou = ensure_connected(HOUDINI_HOST, HOUDINI_PORT)
            return {
                "status": "connected",
                "host": HOUDINI_HOST,
                "port": HOUDINI_PORT,
                "houdini_version": hou.applicationVersionString()
            }
        else:
            # Try to connect
            hou = ensure_connected(HOUDINI_HOST, HOUDINI_PORT)
            return {
                "status": "connected",
                "host": HOUDINI_HOST,
                "port": HOUDINI_PORT,
                "houdini_version": hou.applicationVersionString(),
                "message": "Successfully connected"
            }
    except Exception as e:
        return {
            "status": "disconnected",
            "host": HOUDINI_HOST,
            "port": HOUDINI_PORT,
            "error": str(e)
        }


def run_server(transport: str = "http", port: int = 3055):
    """Run the MCP server."""
    from typing import Literal
    logger.info(f"Starting Houdini MCP Server on {transport}://0.0.0.0:{port}")
    logger.info(f"Houdini connection target: {HOUDINI_HOST}:{HOUDINI_PORT}")
    # Cast transport to literal type for FastMCP
    transport_literal: Literal["stdio", "http", "sse", "streamable-http"] = "http"  # type: ignore
    if transport in ("stdio", "http", "sse", "streamable-http"):
        transport_literal = transport  # type: ignore
    mcp.run(transport=transport_literal, port=port)


if __name__ == "__main__":
    run_server()
