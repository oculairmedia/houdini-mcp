"""Node layout and organization tools.

This module provides tools for organizing nodes in the network editor,
including auto-layout, positioning, coloring, and network box creation.
"""

import logging
import traceback
from typing import Any, Dict, List, Optional

from ._common import (
    ensure_connected,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
)

logger = logging.getLogger("houdini_mcp.tools.layout")


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
        host: Houdini RPC server host
        port: Houdini RPC server port

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
        host: Houdini RPC server host
        port: Houdini RPC server port

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
        host: Houdini RPC server host
        port: Houdini RPC server port

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
        host: Houdini RPC server host
        port: Houdini RPC server port

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
