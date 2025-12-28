"""Houdini MCP Tools Package.

This package provides all the tools exposed via the MCP protocol.
Tools are organized into modules by functionality, but all public
functions are re-exported here for backward compatibility.

Usage:
    from houdini_mcp.tools import get_scene_info, create_node
    # or (after Phase 2)
    from houdini_mcp.tools.scene import get_scene_info
"""

# For Phase 1, we re-export everything from the legacy tools module
# This maintains backward compatibility while we migrate to the new structure
#
# As modules are extracted in Phase 2, imports will be updated to come from
# the specific module files (scene.py, nodes.py, etc.)

# Import from extracted modules
from .help import get_houdini_help
from .errors import find_error_nodes
from .layout import layout_children, set_node_color, set_node_position, create_network_box
from .materials import create_material, assign_material, get_material_info
from .geometry import get_geo_summary
from .parameters import set_parameter, get_parameter_schema
from .rendering import render_viewport
from .wiring import connect_nodes, disconnect_node_input, reorder_inputs, set_node_flags
from .code import execute_code, get_last_scene_diff

# Import remaining functions from legacy module
from ..tools_legacy import (
    # Scene management
    get_scene_info,
    serialize_scene,
    new_scene,
    save_scene,
    load_scene,
    # Node management
    create_node,
    delete_node,
    get_node_info,
    list_children,
    find_nodes,
    list_node_types,
    # Internal utilities (needed by some tests)
    _handle_connection_error,
    _add_response_metadata,
    _estimate_response_size,
    _detect_dangerous_code,
    _truncate_output,
    _node_to_dict,
    _get_scene_diff,
    _serialize_scene_state,
    RESPONSE_SIZE_WARNING_THRESHOLD,
    RESPONSE_SIZE_LARGE_THRESHOLD,
    CONNECTION_ERRORS,
)

# Re-export connection utilities used by some tests
from ..connection import ensure_connected

__all__ = [
    # Scene management
    "get_scene_info",
    "serialize_scene",
    "new_scene",
    "save_scene",
    "load_scene",
    "get_last_scene_diff",
    # Node management
    "create_node",
    "delete_node",
    "get_node_info",
    "list_children",
    "find_nodes",
    "list_node_types",
    # Wiring/connections
    "connect_nodes",
    "disconnect_node_input",
    "reorder_inputs",
    "set_node_flags",
    # Parameters
    "set_parameter",
    "get_parameter_schema",
    # Geometry
    "get_geo_summary",
    # Rendering
    "render_viewport",
    # Materials
    "create_material",
    "assign_material",
    "get_material_info",
    # Errors
    "find_error_nodes",
    # Layout
    "layout_children",
    "set_node_position",
    "set_node_color",
    "create_network_box",
    # Code execution
    "execute_code",
    # Help/documentation
    "get_houdini_help",
]
