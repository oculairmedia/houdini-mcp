"""Node management tools for Houdini MCP.

This module provides tools for managing Houdini nodes:
- create_node: Create a new node
- get_node_info: Get detailed node information
- delete_node: Delete a node
- list_node_types: List available node types
- list_children: List child nodes with connection info
- find_nodes: Find nodes by pattern or type
"""

import logging
import traceback
from typing import Any, Dict, List, Optional

from ._common import (
    ensure_connected,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
    _add_response_metadata,
    _json_safe_hou_value,
    logger as common_logger,
)

logger = logging.getLogger("houdini_mcp.tools.nodes")


def create_node(
    node_type: str,
    parent_path: str = "/obj",
    name: Optional[str] = None,
    host: str = "localhost",
    port: int = 18811,
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
            return {"status": "error", "message": f"Parent node not found: {parent_path}"}

        if name:
            node = parent.createNode(node_type, name)
        else:
            node = parent.createNode(node_type)

        return {
            "status": "success",
            "node_path": node.path(),
            "node_type": node.type().name(),
            "node_name": node.name(),
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "creating_node")
    except Exception as e:
        logger.error(f"Error creating node: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def get_node_info(
    node_path: str,
    include_params: bool = True,
    max_params: int = 50,
    include_input_details: bool = True,
    include_errors: bool = False,
    force_cook: bool = False,
    compact: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Get detailed information about a node.

    Args:
        node_path: Path to the node
        include_params: Whether to include parameter values
        max_params: Maximum number of parameters to return
        include_input_details: When True, expand input connections to show source node,
                              output index, and connection index details
        include_errors: When True, include cook state and error/warning information
        force_cook: When True, force cook the node before checking errors (requires include_errors=True)
        compact: When True, return minimal info (path, type, counts only)

    Returns:
        Dict with node information. When include_errors=True, also includes cook_info
        with cook_state, errors, warnings, and last_cook_time.
    """
    try:
        hou = ensure_connected(host, port)

        node = hou.node(node_path)
        if node is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        # Compact mode: minimal response with just essential info
        if compact:
            info: Dict[str, Any] = {
                "status": "success",
                "path": node.path(),
                "type": node.type().name(),
            }
            # Only include non-empty children/inputs/outputs counts
            children_count = len(node.children())
            inputs_count = len([i for i in node.inputs() if i])
            outputs_count = len(node.outputs())
            if children_count:
                info["children_count"] = children_count
            if inputs_count:
                info["inputs_count"] = inputs_count
            if outputs_count:
                info["outputs_count"] = outputs_count
            return info

        info = {
            "status": "success",
            "path": node.path(),
            "name": node.name(),
            "type": node.type().name(),
            "type_description": node.type().description(),
            "children": [child.name() for child in node.children()],
            "inputs": [inp.path() if inp else None for inp in node.inputs()],
            "outputs": [out.path() for out in node.outputs()],
            "is_displayed": node.isDisplayFlagSet() if hasattr(node, "isDisplayFlagSet") else None,
            "is_rendered": node.isRenderFlagSet() if hasattr(node, "isRenderFlagSet") else None,
        }

        # Add detailed input connection information if requested
        if include_input_details:
            input_connections: List[Dict[str, Any]] = []
            node_inputs = node.inputs()

            # Cache inputConnectors call OUTSIDE the loop to avoid
            # redundant RPC calls (was previously called per input)
            try:
                connectors = node.inputConnectors()
            except Exception:
                connectors = None

            for idx, input_node in enumerate(node_inputs):
                if input_node is not None:
                    # Use cached connectors
                    source_output_idx = 0
                    if connectors is not None and idx < len(connectors):
                        connector = connectors[idx]
                        source_output_idx = connector[1] if len(connector) > 1 else 0

                    input_connections.append(
                        {
                            "input_index": idx,
                            "source_node": input_node.path(),
                            "source_output_index": source_output_idx,
                        }
                    )

            info["input_connections"] = input_connections

        if include_params:
            params: Dict[str, Any] = {}
            for i, parm in enumerate(node.parms()):
                if i >= max_params:
                    params["_truncated"] = True
                    break
                try:
                    params[parm.name()] = _json_safe_hou_value(hou, parm.eval())
                except Exception:
                    params[parm.name()] = "<unable to evaluate>"
            info["parameters"] = params

        # Add cook info if requested
        if include_errors:
            try:
                # Force cook if requested
                if force_cook:
                    node.cook(force=True)

                # Determine cook state using available methods
                # Houdini 20.5+ doesn't have cookState(), use needsToCook() instead
                try:
                    if hasattr(node, "cookState"):
                        cook_state_obj = node.cookState()
                        cook_state_name = (
                            cook_state_obj.name()
                            if hasattr(cook_state_obj, "name")
                            else str(cook_state_obj)
                        )
                        cook_state_map = {
                            "Cooked": "cooked",
                            "CookFailed": "error",
                            "Dirty": "dirty",
                            "Uncooked": "uncooked",
                        }
                        cook_state = cook_state_map.get(cook_state_name, cook_state_name.lower())
                    elif hasattr(node, "needsToCook"):
                        # Fallback for Houdini versions without cookState()
                        needs_cook = node.needsToCook()
                        cook_state = "dirty" if needs_cook else "cooked"
                    else:
                        cook_state = "unknown"
                except Exception:
                    cook_state = "unknown"

                # Get errors and warnings
                errors_list: List[Dict[str, str]] = []
                warnings_list: List[Dict[str, str]] = []

                # Get errors
                try:
                    node_errors = node.errors()
                    for error_msg in node_errors:
                        errors_list.append(
                            {"severity": "error", "message": error_msg, "node_path": node.path()}
                        )
                except Exception:
                    pass

                # Get warnings
                try:
                    node_warnings = node.warnings()
                    for warning_msg in node_warnings:
                        warnings_list.append(
                            {
                                "severity": "warning",
                                "message": warning_msg,
                                "node_path": node.path(),
                            }
                        )
                except Exception:
                    pass

                # Build cook info dict
                cook_info: Dict[str, Any] = {
                    "cook_state": cook_state,
                    "errors": errors_list,
                    "warnings": warnings_list,
                }

                # Try to get last cook time (may not be available on all node types)
                try:
                    # Houdini doesn't have a direct lastCookTime, but we can check if cooked
                    # For now, we'll skip this or use current time if just cooked
                    if force_cook:
                        import time

                        cook_info["last_cook_time"] = time.time()
                except Exception:
                    pass

                info["cook_info"] = cook_info

            except Exception as e:
                # If we can't get cook info, add error but don't fail the whole request
                logger.warning(f"Error getting cook info: {e}")
                info["cook_info"] = {
                    "cook_state": "unknown",
                    "errors": [
                        {"severity": "error", "message": f"Failed to get cook info: {str(e)}"}
                    ],
                    "warnings": [],
                }

        return info
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "getting_node_info")
    except Exception as e:
        logger.error(f"Error getting node info: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def delete_node(node_path: str, host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
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
            return {"status": "error", "message": f"Node not found: {node_path}"}

        node_name = node.name()
        node.destroy()

        return {
            "status": "success",
            "message": f"Deleted node: {node_name}",
            "deleted_path": node_path,
        }
    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "deleting_node")
    except Exception as e:
        logger.error(f"Error deleting node: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def list_node_types(
    category: Optional[str] = None,
    max_results: int = 100,
    name_filter: Optional[str] = None,
    offset: int = 0,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    List available node types, optionally filtered by category.

    Args:
        category: Optional category filter (e.g., "Object", "Sop", "Cop2", "Vop")
        max_results: Maximum number of results to return (default: 100, max: 500)
        name_filter: Optional substring filter for node type names (case-insensitive)
        offset: Number of results to skip for pagination (default: 0)

    Returns:
        Dict with list of node types and pagination info.

    Note:
        Large categories like "Sop" have thousands of node types.
        Use name_filter to narrow results (e.g., name_filter="noise" for noise-related SOPs).
        Use offset for pagination through large result sets.
    """
    try:
        hou = ensure_connected(host, port)

        # Cap max_results to prevent excessive data transfer
        if max_results > 500:
            max_results = 500
        elif max_results < 1:
            max_results = 100

        node_types: List[Dict[str, str]] = []
        total_scanned = 0
        total_matched = 0
        categories_scanned: List[str] = []

        # Validate offset
        if offset < 0:
            offset = 0

        # Get category info first (lightweight operation)
        all_categories = list(hou.nodeTypeCategories().items())

        for cat_name, cat in all_categories:
            # Filter by category if specified
            if category and cat_name.lower() != category.lower():
                continue

            categories_scanned.append(cat_name)

            # Early termination if we've collected enough results
            if len(node_types) >= max_results:
                break

            try:
                # Get node types for this category
                # Use items() to iterate - don't convert entire dict to list
                for type_name, type_obj in cat.nodeTypes().items():
                    total_scanned += 1

                    # Apply name filter if provided
                    if name_filter:
                        if name_filter.lower() not in type_name.lower():
                            continue

                    # Count matched items for pagination info
                    total_matched += 1

                    # Skip items before offset
                    if total_matched <= offset:
                        continue

                    # Early termination check inside the loop
                    if len(node_types) >= max_results:
                        break

                    try:
                        description = type_obj.description()
                    except Exception:
                        description = ""

                    node_types.append(
                        {"category": cat_name, "name": type_name, "description": description}
                    )

            except Exception as e:
                logger.warning(f"Error iterating node types in category {cat_name}: {e}")
                continue

        result: Dict[str, Any] = {
            "status": "success",
            "count": len(node_types),
            "node_types": node_types,
            "categories_scanned": categories_scanned,
        }

        # Add pagination info
        if offset > 0:
            result["offset"] = offset

        # Calculate if there are more results
        has_more = total_matched > offset + len(node_types)
        if has_more:
            result["has_more"] = True
            result["next_offset"] = offset + len(node_types)

        # Add warning if results were limited
        if len(node_types) >= max_results:
            result["warning"] = (
                f"Results limited to {max_results}. "
                f"Use offset={offset + max_results} for next page, or use name_filter to narrow results."
            )
            result["total_scanned"] = total_scanned

        # Add response size metadata for large responses
        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "listing_node_types")
    except Exception as e:
        logger.error(f"Error listing node types: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def list_children(
    node_path: str,
    recursive: bool = False,
    max_depth: int = 10,
    max_nodes: int = 1000,
    compact: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    List child nodes with paths, types, and current input connections.

    This tool is essential for agents to understand node networks and insert
    nodes without breaking existing connections.

    Args:
        node_path: Path to the parent node
        recursive: If True, recursively traverse child nodes
        max_depth: Maximum recursion depth (prevents infinite loops)
        max_nodes: Maximum number of nodes to return (safety limit)
        compact: If True, return only path/name/type without connection details

    Returns:
        Dict with child nodes including their connection information.
        When compact=True, inputs/outputs are omitted for reduced payload size.
    """
    try:
        hou = ensure_connected(host, port)

        parent = hou.node(node_path)
        if parent is None:
            return {"status": "error", "message": f"Node not found: {node_path}"}

        children_list: List[Dict[str, Any]] = []
        nodes_collected = 0

        def collect_children(node: Any, depth: int = 0) -> None:
            nonlocal nodes_collected

            if depth > max_depth:
                logger.warning(f"Max depth {max_depth} reached at {node.path()}")
                return

            if nodes_collected >= max_nodes:
                logger.warning(f"Max nodes {max_nodes} limit reached")
                return

            try:
                for child in node.children():
                    if nodes_collected >= max_nodes:
                        break

                    # Compact mode: only path, name, type
                    if compact:
                        child_info: Dict[str, Any] = {
                            "path": child.path(),
                            "name": child.name(),
                            "type": child.type().name(),
                        }
                    else:
                        # Full mode: include input/output connection details
                        # Build input connection details
                        input_connections: List[Dict[str, Any]] = []
                        child_inputs = child.inputs()

                        # Cache inputConnectors call OUTSIDE the loop to avoid
                        # redundant RPC calls (was previously called per input)
                        try:
                            connectors = child.inputConnectors()
                        except Exception:
                            connectors = None

                        for idx, input_node in enumerate(child_inputs):
                            if input_node is not None:
                                # Use cached connectors
                                output_idx = 0
                                if connectors is not None and idx < len(connectors):
                                    connector = connectors[idx]
                                    output_idx = connector[1] if len(connector) > 1 else 0

                                input_connections.append(
                                    {
                                        "index": idx,
                                        "source_node": input_node.path(),
                                        "output_index": output_idx,
                                    }
                                )

                        # Build output list
                        output_paths = [out.path() for out in child.outputs()]

                        child_info = {
                            "path": child.path(),
                            "name": child.name(),
                            "type": child.type().name(),
                            "inputs": input_connections,
                            "outputs": output_paths,
                        }

                    children_list.append(child_info)
                    nodes_collected += 1

                    # Recurse if requested
                    if recursive:
                        collect_children(child, depth + 1)

            except Exception as e:
                # Handle locked HDAs or other access issues
                logger.warning(f"Could not access children of {node.path()}: {e}")

        collect_children(parent)

        result: Dict[str, Any] = {
            "status": "success",
            "node_path": node_path,
            "children": children_list,
            "count": len(children_list),
        }

        if nodes_collected >= max_nodes:
            result["warning"] = f"Result limited to {max_nodes} nodes"

        # Add response size metadata for large responses
        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "listing_children")
    except Exception as e:
        logger.error(f"Error listing children: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def find_nodes(
    root_path: str = "/obj",
    pattern: str = "*",
    node_type: Optional[str] = None,
    max_results: int = 100,
    offset: int = 0,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Find nodes by name pattern or type using glob/substring matching.

    Args:
        root_path: Root path to start search from
        pattern: Glob pattern or substring to match against node names (* for wildcard)
        node_type: Optional node type filter (e.g., "sphere", "noise", "geo")
        max_results: Maximum number of results to return
        offset: Number of results to skip for pagination (default: 0)

    Returns:
        Dict with matching nodes and their types.
        Includes pagination info (has_more, next_offset) when applicable.

    Example:
        find_nodes("/obj", "noise*", max_results=50)
        find_nodes("/obj/geo1", "*", node_type="sphere")
        find_nodes("/obj", "*", offset=100)  # Get next page
    """
    try:
        hou = ensure_connected(host, port)

        root = hou.node(root_path)
        if root is None:
            return {"status": "error", "message": f"Root node not found: {root_path}"}

        # Validate offset
        if offset < 0:
            offset = 0

        # Execute search on Houdini side to minimize RPC overhead
        # Uses allSubChildren() which is much faster than recursive children() calls
        search_code = """
import fnmatch

root = hou.node("{root_path}")
pattern = "{pattern}"
node_type_filter = {node_type_repr}
max_results = {max_results}
offset = {offset}

matches = []
total_matched = 0
has_wildcards = "*" in pattern or "?" in pattern

if root is not None:
    # allSubChildren() returns all descendants in a single call
    for child in root.allSubChildren():
        child_name = child.name()
        child_name_lower = child_name.lower()
        pattern_lower = pattern.lower()
        
        # Check name pattern match
        if has_wildcards:
            name_match = fnmatch.fnmatch(child_name_lower, pattern_lower)
        else:
            # Exact match or substring match
            name_match = fnmatch.fnmatch(child_name_lower, pattern_lower) or pattern_lower in child_name_lower
        
        # Check type filter
        type_match = True
        child_type = child.type().name()
        if node_type_filter is not None:
            type_match = child_type.lower() == node_type_filter.lower()
        
        if name_match and type_match:
            total_matched += 1
            
            # Skip items before offset
            if total_matched <= offset:
                continue
            
            matches.append({{
                "path": child.path(),
                "name": child_name,
                "type": child_type,
            }})
            
            # Stop if we have enough results
            if len(matches) >= max_results:
                break

_result = {{"matches": matches, "total_matched": total_matched}}
""".format(
            root_path=root_path,
            pattern=pattern.replace('"', '\\"'),
            node_type_repr=repr(node_type),
            max_results=max_results,
            offset=offset,
        )

        try:
            exec_globals: Dict[str, Any] = {
                "hou": hou,
                "_result": {"matches": [], "total_matched": 0},
            }
            exec(search_code, exec_globals)
            search_result = exec_globals.get("_result", {"matches": [], "total_matched": 0})
            matches = search_result["matches"]
            total_matched = search_result["total_matched"]
        except Exception as e:
            logger.warning(f"Fast search failed, falling back to slow path: {e}")
            # Fallback to original slow implementation
            import fnmatch as fnmatch_module

            matches = []
            total_matched = 0

            def search_recursive(node: Any) -> None:
                nonlocal total_matched
                if len(matches) >= max_results:
                    return

                try:
                    for child in node.children():
                        if len(matches) >= max_results:
                            break

                        name_match = fnmatch_module.fnmatch(child.name().lower(), pattern.lower())
                        if "*" not in pattern and "?" not in pattern:
                            name_match = name_match or pattern.lower() in child.name().lower()

                        type_match = True
                        if node_type is not None:
                            type_match = child.type().name().lower() == node_type.lower()

                        if name_match and type_match:
                            total_matched += 1
                            if total_matched <= offset:
                                search_recursive(child)
                                continue
                            matches.append(
                                {
                                    "path": child.path(),
                                    "name": child.name(),
                                    "type": child.type().name(),
                                }
                            )
                        search_recursive(child)
                except Exception as ex:
                    logger.debug(f"Could not search in {node.path()}: {ex}")

            search_recursive(root)

        result: Dict[str, Any] = {
            "status": "success",
            "root_path": root_path,
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
        }

        if node_type:
            result["node_type_filter"] = node_type

        # Add pagination info
        if offset > 0:
            result["offset"] = offset

        # Calculate if there are more results
        has_more = total_matched > offset + len(matches)
        if has_more:
            result["has_more"] = True
            result["next_offset"] = offset + len(matches)

        if len(matches) >= max_results:
            result["warning"] = (
                f"Results limited to {max_results} nodes. Use offset={offset + max_results} for next page."
            )

        # Add response size metadata for large responses
        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "finding_nodes")
    except Exception as e:
        logger.error(f"Error finding nodes: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
