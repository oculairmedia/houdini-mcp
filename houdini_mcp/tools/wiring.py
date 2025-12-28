"""Node connection and wiring tools.

This module provides tools for connecting, disconnecting, and managing
node connections in Houdini networks.
"""

import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple

from ._common import (
    ensure_connected,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
)

logger = logging.getLogger("houdini_mcp.tools.wiring")


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

    Validates that node types are compatible (e.g., SOP->SOP, OBJ->OBJ) before connecting.
    Automatically disconnects existing connection if the destination input is already wired.

    Args:
        src_path: Path to source node
        dst_path: Path to destination node
        dst_input_index: Input index on destination node (default: 0)
        src_output_index: Output index on source node (default: 0)

    Returns:
        Dict with connection result.

    Example:
        connect_nodes("/obj/geo1/grid1", "/obj/geo1/noise1")  # Connect grid -> noise
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
                    "message": f"Incompatible node types: {src_category} -> {dst_category}. "
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
            "message": f"Connected {src_path} -> {dst_path}",
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
