"""Houdini MCP Server - Main server entry point."""

import os
import logging
from typing import Any, Dict, List, Optional, Literal, Union

from fastmcp import FastMCP

from .connection import ensure_connected, is_connected, disconnect, get_connection_info, ping
from . import tools

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
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
    node_type: str, parent_path: str = "/obj", name: Optional[str] = None
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
def execute_code(
    code: str,
    capture_diff: bool = True,
    max_stdout_size: int = 100000,
    max_stderr_size: int = 100000,
    max_diff_nodes: int = 1000,
    timeout: int = 30,
    allow_dangerous: bool = False,
) -> Dict[str, Any]:
    """
    Execute Python code in Houdini with scene change tracking and safety rails.

    The 'hou' module is available in the execution context.
    Use this for complex operations that aren't covered by other tools.

    SAFETY FEATURES:
    - Dangerous operation detection: Scans for patterns like hou.exit(), os.remove(), subprocess, etc.
    - Output size caps: Prevents massive output from overwhelming the response
    - Execution timeout: Prevents runaway code from blocking indefinitely
    - Scene diff limits: Caps the number of nodes returned in scene changes

    Args:
        code: Python code to execute
        capture_diff: If True, captures before/after scene state and returns changes (default: True)
        max_stdout_size: Maximum stdout size in bytes (default: 100000 = 100KB)
        max_stderr_size: Maximum stderr size in bytes (default: 100000 = 100KB)
        max_diff_nodes: Maximum nodes in scene diff added_nodes list (default: 1000)
        timeout: Execution timeout in seconds (default: 30)
        allow_dangerous: If True, allows code with dangerous patterns to execute (default: False)

    Dangerous patterns detected:
        - hou.exit() - closes Houdini
        - os.remove(), os.unlink() - file deletion
        - shutil.rmtree() - directory deletion
        - subprocess, os.system() - shell execution
        - open() with write modes - file writing
        - hou.hipFile.clear() - scene wipe

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
        Dict with status, stdout, stderr, and scene_changes (if capture_diff=True).
        May include truncation flags (stdout_truncated, stderr_truncated, diff_truncated)
        if output exceeded size limits.
        If dangerous patterns detected and not allowed, returns error with detected patterns.
    """
    return tools.execute_code(
        code,
        HOUDINI_HOST,
        HOUDINI_PORT,
        capture_diff,
        max_stdout_size,
        max_stderr_size,
        max_diff_nodes,
        timeout,
        allow_dangerous,
    )


@mcp.tool()
def set_parameter(
    node_path: str,
    param_name: str,
    value: Union[float, int, str, bool, List[float], List[int], List[str]],
) -> Dict[str, Any]:
    """
    Set a parameter value on a node.

    Args:
        node_path: Full path to the node (e.g., "/obj/geo1/sphere1")
        param_name: Name of the parameter (e.g., "radx", "tx", "scale")
        value: Value to set - can be:
               - float/int for numeric parameters
               - str for string/menu parameters
               - bool for toggle parameters
               - List[float]/List[int] for vector parameters (e.g., translate, rotate, scale)

    Examples:
        - set_parameter("/obj/geo1/sphere1", "radx", 2.5)
        - set_parameter("/obj/cam1", "tx", 10.0)
        - set_parameter("/obj/geo1", "t", [1.0, 2.0, 3.0])  # Vector param
    """
    return tools.set_parameter(node_path, param_name, value, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def get_node_info(
    node_path: str,
    include_params: bool = True,
    include_input_details: bool = True,
    include_errors: bool = False,
    force_cook: bool = False,
) -> Dict[str, Any]:
    """
    Get detailed information about a node.

    Args:
        node_path: Full path to the node
        include_params: Whether to include parameter values (default: True)
        include_input_details: When True, expand input connections to show source node,
                              output index, and connection index details (default: True)
        include_errors: When True, include cook state and error/warning information (default: False)
        force_cook: When True, force cook the node before checking errors (default: False)

    Returns:
        Node information including type, children, connections, flags, and parameters.
        When include_input_details=True, also includes detailed input_connections array
        showing source nodes and output indices for each connection.
        When include_errors=True, also includes cook_info with cook_state, errors, and warnings.

    Example:
        # Get node info with cook state and errors
        get_node_info("/obj/geo1/sphere1", include_errors=True)

        # Force cook and check for errors
        get_node_info("/obj/geo1/sphere1", include_errors=True, force_cook=True)
    """
    return tools.get_node_info(
        node_path,
        include_params,
        50,
        include_input_details,
        include_errors,
        force_cook,
        HOUDINI_HOST,
        HOUDINI_PORT,
    )


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
def serialize_scene(root_path: str = "/obj", include_params: bool = False) -> Dict[str, Any]:
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
def list_children(
    node_path: str, recursive: bool = False, max_depth: int = 10, max_nodes: int = 1000
) -> Dict[str, Any]:
    """
    List child nodes with paths, types, and current input connections.

    This tool is essential for understanding node networks and helps agents
    insert nodes without breaking existing connections. Each child includes
    detailed input connection information showing which nodes are connected
    and at which indices.

    Args:
        node_path: Path to the parent node (e.g., "/obj/geo1")
        recursive: If True, recursively traverse all descendants (default: False)
        max_depth: Maximum recursion depth to prevent infinite loops (default: 10)
        max_nodes: Maximum number of nodes to return as safety limit (default: 1000)

    Returns:
        Dict with children array containing node info including:
        - path: Full node path
        - name: Node name
        - type: Node type
        - inputs: Array of input connections with source_node and output_index
        - outputs: Array of output node paths

    Example:
        list_children("/obj/geo1", recursive=True, max_depth=3)
    """
    return tools.list_children(
        node_path, recursive, max_depth, max_nodes, HOUDINI_HOST, HOUDINI_PORT
    )


@mcp.tool()
def find_nodes(
    root_path: str = "/obj",
    pattern: str = "*",
    node_type: Optional[str] = None,
    max_results: int = 100,
) -> Dict[str, Any]:
    """
    Find nodes by name pattern or type using glob/substring matching.

    Supports wildcard patterns (* and ?) for flexible searching. When pattern
    contains no wildcards, also performs substring matching.

    Args:
        root_path: Root path to start search from (default: "/obj")
        pattern: Glob pattern or substring to match node names (default: "*")
                Examples: "noise*", "*grid*", "sphere"
        node_type: Optional node type filter (e.g., "sphere", "noise", "geo")
        max_results: Maximum number of results to return (default: 100)

    Returns:
        Dict with matches array containing matching nodes with path, name, and type.

    Examples:
        find_nodes("/obj", "noise*") - Find all nodes starting with "noise"
        find_nodes("/obj/geo1", "*", node_type="sphere") - Find all sphere nodes
        find_nodes("/obj", "grid") - Substring match for "grid"
    """
    return tools.find_nodes(root_path, pattern, node_type, max_results, HOUDINI_HOST, HOUDINI_PORT)


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
            "error": str(e),
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
        "port": HOUDINI_PORT,
    }


@mcp.tool()
def connect_nodes(
    src_path: str, dst_path: str, dst_input_index: int = 0, src_output_index: int = 0
) -> Dict[str, Any]:
    """
    Wire output of source node to input of destination node.

    Validates that node types are compatible (e.g., SOP→SOP, OBJ→OBJ) before connecting.
    Automatically disconnects existing connection if the destination input is already wired.

    Args:
        src_path: Path to source node (e.g., "/obj/geo1/grid1")
        dst_path: Path to destination node (e.g., "/obj/geo1/noise1")
        dst_input_index: Input index on destination node (default: 0)
        src_output_index: Output index on source node (default: 0)

    Returns:
        Dict with connection result including validation and connection details.

    Examples:
        connect_nodes("/obj/geo1/grid1", "/obj/geo1/noise1")
        connect_nodes("/obj/geo1/grid1", "/obj/geo1/merge1", dst_input_index=1)
    """
    return tools.connect_nodes(
        src_path, dst_path, dst_input_index, src_output_index, HOUDINI_HOST, HOUDINI_PORT
    )


@mcp.tool()
def disconnect_node_input(node_path: str, input_index: int = 0) -> Dict[str, Any]:
    """
    Break/disconnect an input connection on a node.

    Args:
        node_path: Path to the node (e.g., "/obj/geo1/noise1")
        input_index: Input index to disconnect (default: 0)

    Returns:
        Dict with disconnection result including previous connection info if applicable.

    Examples:
        disconnect_node_input("/obj/geo1/noise1")  # Disconnect first input
        disconnect_node_input("/obj/geo1/merge1", input_index=1)  # Disconnect second input
    """
    return tools.disconnect_node_input(node_path, input_index, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def set_node_flags(
    node_path: str,
    display: Optional[bool] = None,
    render: Optional[bool] = None,
    bypass: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Set display, render, and bypass flags on a node.

    Only non-None values are set, allowing partial flag updates.
    Checks for flag availability using hasattr() before setting.

    Args:
        node_path: Path to the node (e.g., "/obj/geo1/sphere1")
        display: Display flag value (True/False) or None to skip
        render: Render flag value (True/False) or None to skip
        bypass: Bypass flag value (True/False) or None to skip

    Returns:
        Dict with result and flags that were set.

    Examples:
        set_node_flags("/obj/geo1/sphere1", display=True, render=True)
        set_node_flags("/obj/geo1/noise1", bypass=True)
        set_node_flags("/obj/geo1/mountain1", display=True)  # Only set display
    """
    return tools.set_node_flags(node_path, display, render, bypass, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def reorder_inputs(node_path: str, new_order: List[int]) -> Dict[str, Any]:
    """
    Reorder inputs on a node (useful for merge nodes).

    Stores existing connections, disconnects all, then reconnects in new order.
    new_order specifies the new position for each input: [1, 0, 2] swaps first two inputs.

    Args:
        node_path: Path to the node (e.g., "/obj/geo1/merge1")
        new_order: List specifying new input order (e.g., [1, 0, 2] to swap first two)

    Returns:
        Dict with reordering result including reconnection details.

    Examples:
        reorder_inputs("/obj/geo1/merge1", [1, 0, 2, 3])  # Swap first two inputs
        reorder_inputs("/obj/geo1/merge1", [2, 1, 0])  # Reverse three inputs
    """
    return tools.reorder_inputs(node_path, new_order, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def get_parameter_schema(
    node_path: str, parm_name: Optional[str] = None, max_parms: int = 100
) -> Dict[str, Any]:
    """
    Get parameter metadata/schema for intelligent parameter setting.

    Returns detailed parameter information including types, defaults, ranges,
    menu items, tuple sizes, and current values. Essential for understanding
    what parameters are available on a node and how to set them correctly.

    Args:
        node_path: Full path to the node (e.g., "/obj/geo1/sphere1")
        parm_name: Optional specific parameter name. If provided, returns only that parameter's schema.
                  If None, returns schema for all parameters (up to max_parms)
        max_parms: Maximum number of parameters to return when parm_name is None (default: 100)

    Returns:
        Dict containing parameter schemas with type information, defaults, ranges, and current values.

    Schema includes:
        - name: Parameter name
        - label: UI label
        - type: Parameter type (float, int, string, menu, toggle, vector, ramp, etc.)
        - default: Default value(s)
        - min/max: Numeric ranges (if applicable)
        - menu_items: List of {label, value} for menu parameters
        - tuple_size: Size for vector parameters
        - is_animatable: Whether parameter can be keyframed
        - current_value: Current parameter value

    Examples:
        # Get all parameters on a sphere
        get_parameter_schema("/obj/geo1/sphere1")

        # Get specific parameter info
        get_parameter_schema("/obj/geo1/sphere1", parm_name="radx")

        # Get info for translate parameter (vector)
        get_parameter_schema("/obj/geo1", parm_name="t")
    """
    return tools.get_parameter_schema(node_path, parm_name, max_parms, HOUDINI_HOST, HOUDINI_PORT)


@mcp.tool()
def get_geo_summary(
    node_path: str,
    max_sample_points: int = 100,
    include_attributes: bool = True,
    include_groups: bool = True,
) -> Dict[str, Any]:
    """
    Get geometry statistics and metadata for verification.

    Returns comprehensive geometry information including point/primitive counts,
    bounding box, attributes, groups, and optionally sample points. This tool is
    essential for agents to verify results after geometry operations.

    Args:
        node_path: Full path to the SOP node (e.g., "/obj/geo1/sphere1")
        max_sample_points: Maximum number of sample points to return (default: 100, max: 10000).
                          Set to 0 to skip point sampling.
        include_attributes: Whether to include attribute metadata (default: True)
        include_groups: Whether to include group information (default: True)

    Returns:
        Dict with comprehensive geometry summary including:
        - point_count, primitive_count, vertex_count: Geometry topology stats
        - bounding_box: {min, max, size, center} vectors in world space
        - cook_state: Current cook state ("cooked", "dirty", "uncooked", "error")
        - attributes: Metadata for point/primitive/vertex/detail attributes
        - groups: Names of point and primitive groups
        - sample_points: Optional array of first N points with their attribute values

    Edge Cases:
        - Uncooked geometry: Tool will attempt to cook the node first
        - Empty geometry: Returns zeros for counts, not an error
        - Massive geometry (>1M points): Automatically caps sampling with warning
        - No geometry/Not a SOP: Returns error status

    Examples:
        # Basic geometry summary with 50 sample points
        get_geo_summary("/obj/geo1/sphere1", max_sample_points=50)

        # Just get counts and bbox, skip attributes/groups/samples
        get_geo_summary("/obj/geo1/grid1", max_sample_points=0,
                       include_attributes=False, include_groups=False)

        # Full detail for verification
        get_geo_summary("/obj/geo1/noise1", max_sample_points=200)
    """
    return tools.get_geo_summary(
        node_path, max_sample_points, include_attributes, include_groups, HOUDINI_HOST, HOUDINI_PORT
    )


def run_server(transport: str = "http", port: int = 3055) -> None:
    """Run the MCP server."""
    logger.info(f"Starting Houdini MCP Server on {transport}://0.0.0.0:{port}")
    logger.info(f"Houdini connection target: {HOUDINI_HOST}:{HOUDINI_PORT}")
    logger.info(f"Log level: {log_level}")

    # Cast transport to literal type for FastMCP
    transport_literal: Literal["stdio", "http", "sse", "streamable-http"] = "http"
    if transport in ("stdio", "http", "sse", "streamable-http"):
        transport_literal = transport  # type: ignore

    mcp.run(transport=transport_literal, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_server()
