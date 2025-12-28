"""Houdini MCP Tools Package.

This package provides all the tools exposed via the MCP protocol.
Tools are organized into modules by functionality, but all public
functions are re-exported here for backward compatibility.

Usage:
    from houdini_mcp.tools import get_scene_info, create_node
    # or
    from houdini_mcp.tools.scene import get_scene_info
"""

# Import from extracted modules
from .help import get_houdini_help
from .errors import find_error_nodes
from .layout import layout_children, set_node_color, set_node_position, create_network_box
from .materials import create_material, assign_material, get_material_info
from .geometry import get_geo_summary
from .parameters import set_parameter, get_parameter_schema
from .rendering import (
    render_viewport,
    render_quad_view,
    list_render_nodes,
    get_render_settings,
    set_render_settings,
    create_render_node,
)
from .wiring import connect_nodes, disconnect_node_input, reorder_inputs, set_node_flags
from .code import execute_code, get_last_scene_diff
from .scene import get_scene_info, save_scene, load_scene, new_scene, serialize_scene
from .hscript import HscriptBatch, get_batch, fast_list_paths, fast_get_scene_tree
from .cache import node_type_cache, invalidate_all_caches, get_cache_stats
from .summarization import (
    summarize_geometry,
    summarize_errors,
    summarize_scene,
    summarize_render_settings,
    get_summarization_status,
    should_summarize,
    estimate_tokens,
)
from .nodes import (
    create_node,
    get_node_info,
    delete_node,
    list_node_types,
    list_children,
    find_nodes,
)
from .pane_screenshot import (
    capture_pane_screenshot,
    list_visible_panes,
    capture_multiple_panes,
    render_node_network,
    VALID_PANE_TYPES,
)

# Import shared utilities from _common (needed by some tests)
from ._common import (
    _handle_connection_error,
    _add_response_metadata,
    _estimate_response_size,
    _detect_dangerous_code,
    _truncate_output,
    _node_to_dict,
    _get_scene_diff,
    _serialize_scene_state,
    _json_safe_hou_value,
    RESPONSE_SIZE_WARNING_THRESHOLD,
    RESPONSE_SIZE_LARGE_THRESHOLD,
    CONNECTION_ERRORS,
    ensure_connected,
)

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
    "render_quad_view",
    "list_render_nodes",
    "get_render_settings",
    "set_render_settings",
    "create_render_node",
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
    # Cache management
    "node_type_cache",
    "invalidate_all_caches",
    "get_cache_stats",
    # AI Summarization
    "summarize_geometry",
    "summarize_errors",
    "summarize_scene",
    "summarize_render_settings",
    "get_summarization_status",
    "should_summarize",
    "estimate_tokens",
    # Pane screenshots
    "capture_pane_screenshot",
    "list_visible_panes",
    "capture_multiple_panes",
    "render_node_network",
    "VALID_PANE_TYPES",
]
