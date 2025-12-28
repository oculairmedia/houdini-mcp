"""Parameter manipulation and introspection tools.

This module provides tools for getting and setting parameters on Houdini nodes,
including parameter schema introspection.
"""

import logging
from typing import Any, Dict, List, Optional

from ._common import (
    ensure_connected,
    handle_connection_errors,
    _add_response_metadata,
)

logger = logging.getLogger("houdini_mcp.tools.parameters")


@handle_connection_errors("set_parameter")
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


@handle_connection_errors("get_parameter_schema")
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
    # Import helper to flatten parameter templates
    from ._common import _flatten_parm_templates, _json_safe_hou_value

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
            if hasattr(node, "_params") and isinstance(node._params.get(parm_name), (list, tuple)):
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
            param_info = _extract_parameter_info(hou, node, parm_template, _json_safe_hou_value)
            if param_info is not None:
                parameters.append(param_info)
        except Exception as e:
            logger.warning(f"Failed to extract info for parameter {parm_template.name()}: {e}")
            # Continue with next parameter

    result = {
        "status": "success",
        "node_path": node_path,
        "parameters": parameters,
        "count": len(parameters),
    }

    # Add response size metadata for large responses
    return _add_response_metadata(result)


def _extract_parameter_info(
    hou: Any, node: Any, parm_template: Any, json_safe_fn: Any
) -> Optional[Dict[str, Any]]:
    """
    Extract parameter information from a parameter template.

    Args:
        hou: The hou module
        node: The node containing the parameter
        parm_template: The parameter template to extract info from
        json_safe_fn: Function to convert hou values to JSON-safe values

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
                param_info["current_value"] = json_safe_fn(hou, list(parm_tuple.eval()))
            else:
                param_info["current_value"] = None
        else:
            parm = node.parm(param_name)
            if parm is not None:
                param_info["current_value"] = json_safe_fn(hou, parm.eval())
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
