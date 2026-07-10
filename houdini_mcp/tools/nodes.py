"""Node management tools for Houdini MCP.

This module provides tools for managing Houdini nodes:
- create_node: Create a new node
- get_node_info: Get detailed node information
- delete_node: Delete a node
- list_node_types: List available node types (with caching)
- list_children: List child nodes with connection info
- find_nodes: Find nodes by pattern or type
"""

import logging
from typing import Any

from ._common import (
    _add_response_metadata,
    _json_safe_hou_value,
    ensure_connected,
    handle_connection_errors,
    paginate_list,
)
from .cache import node_type_cache

logger = logging.getLogger("houdini_mcp.tools.nodes")


@handle_connection_errors("create_node")
def create_node(
    node_type: str,
    parent_path: str = "/obj",
    name: str | None = None,
    host: str = "localhost",
    port: int = 18811,
) -> dict[str, Any]:
    """
    Create a new node in the Houdini scene.

    Args:
        node_type: The type of node to create (e.g., "geo", "sphere", "box")
        parent_path: The parent node path (default: "/obj")
        name: Optional name for the new node

    Returns:
        Dict with created node information.
    """
    hou = ensure_connected(host, port)

    parent = hou.node(parent_path)
    if parent is None:
        return {"status": "error", "message": f"Parent node not found: {parent_path}"}

    node = parent.createNode(node_type, name) if name else parent.createNode(node_type)

    return {
        "status": "success",
        "node_path": node.path(),
        "node_type": node.type().name(),
        "node_name": node.name(),
    }


@handle_connection_errors("get_node_info")
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
) -> dict[str, Any]:
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
    hou = ensure_connected(host, port)

    node = hou.node(node_path)
    if node is None:
        return {"status": "error", "message": f"Node not found: {node_path}"}

    # Compact mode: minimal response with just essential info
    if compact:
        info: dict[str, Any] = {
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
        input_connections: list[dict[str, Any]] = []
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
        params: dict[str, Any] = {}
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
            errors_list: list[dict[str, str]] = []
            warnings_list: list[dict[str, str]] = []

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
            cook_info: dict[str, Any] = {
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
                "errors": [{"severity": "error", "message": f"Failed to get cook info: {str(e)}"}],
                "warnings": [],
            }

    return info


@handle_connection_errors("delete_node")
def delete_node(node_path: str, host: str = "localhost", port: int = 18811) -> dict[str, Any]:
    """
    Delete a node from the scene.

    Args:
        node_path: Path to the node to delete

    Returns:
        Dict with result.
    """
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


@handle_connection_errors("list_node_types")
def list_node_types(
    category: str | None = None,
    max_results: int | None = None,
    name_filter: str | None = None,
    offset: int | None = None,
    limit: int | None = None,
    cursor: int | None = None,
    host: str = "localhost",
    port: int = 18811,
) -> dict[str, Any]:
    """
    List available node types, optionally filtered by category.

    Uses in-memory caching for fast repeated queries. Node types are fetched
    once per session and cached - subsequent calls filter from cache instantly.

    Args:
        category: Optional category filter (e.g., "Object", "Sop", "Cop2", "Vop")
        max_results: Maximum number of results to return (default: 100, max: 500)
                    DEPRECATED: Use limit instead for consistency
        name_filter: Optional substring filter for node type names (case-insensitive)
        offset: Number of results to skip for pagination (default: 0)
               DEPRECATED: Use cursor instead for consistency
        limit: Maximum number of results per page (default: 100, max: 500)
              Preferred alias for max_results
        cursor: Pagination cursor/offset (default: 0)
               Preferred alias for offset

    Returns:
        Dict with list of node types and pagination info.

    Note:
        Large categories like "Sop" have thousands of node types.
        Use name_filter to narrow results (e.g., name_filter="noise" for noise-related SOPs).
        Use offset for pagination through large result sets.

    Performance:
        - First call: ~200-500ms (populates cache using batch fetch)
        - Subsequent calls: <1ms (filters from cache)
    """
    hou = ensure_connected(host, port)

    # Backward-compatible aliases: limit/cursor take precedence over max_results/offset
    if limit is not None:
        max_results = limit
    elif max_results is None:
        max_results = 100

    if cursor is not None:
        offset = cursor
    elif offset is None:
        offset = 0

    # Cap max_results to prevent excessive data transfer
    if max_results > 500:
        max_results = 500
    elif max_results < 1:
        max_results = 100

    # Validate offset
    if offset < 0:
        offset = 0

    # Populate cache if needed (first call fetches all types)
    # This is done automatically by get_all_types()
    node_type_cache.get_all_types(hou, host, port)

    # Filter from cache (instant)
    node_types, total_matched, has_more = node_type_cache.filter_types(
        category=category,
        name_filter=name_filter,
        max_results=max_results,
        offset=offset,
    )

    # Build result with consistent pagination metadata (HDMCP-52)
    result: dict[str, Any] = {
        "status": "success",
        "node_types": node_types,
        "count": len(node_types),  # Backward compat: count = returned
        "total": total_matched,
        "returned": len(node_types),
        "has_more": has_more,
    }

    # Include category in result if filtered
    if category:
        result["category"] = category
    else:
        # Get available categories from cache
        result["categories_available"] = node_type_cache.get_categories(hou)

    # Add cursor for next page
    if has_more:
        result["cursor"] = offset + len(node_types)

    # Add warning if results were limited
    if len(node_types) >= max_results and has_more:
        result["warning"] = (
            f"Results limited to {max_results}. "
            f"Use offset={offset + max_results} for next page, or use name_filter to narrow results."
        )
        result["total_matched"] = total_matched

    # Add cache stats for visibility
    cache_stats = node_type_cache.stats
    result["_cache_info"] = {
        "hit": cache_stats.hits > 0 and node_type_cache.is_valid(),
        "total_cached": cache_stats.entry_count,
    }

    # Add response size metadata for large responses
    return _add_response_metadata(result)


@handle_connection_errors("list_children")
def list_children(
    node_path: str,
    recursive: bool = False,
    max_depth: int = 10,
    max_nodes: int = 1000,
    limit: int = 20,
    cursor: int | None = None,
    compact: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> dict[str, Any]:
    """
    List child nodes with paths, types, and current input connections.

    This tool is essential for agents to understand node networks and insert
    nodes without breaking existing connections.

    Pagination (HDMCP-52 / houdini-mcp-2t6): Use limit/cursor for page-by-page
    traversal. The default limit is 20 nodes per page.

    Args:
        node_path: Path to the parent node
        recursive: If True, recursively traverse child nodes
        max_depth: Maximum recursion depth (prevents infinite loops)
        max_nodes: Maximum total nodes to collect (safety limit, default: 1000)
        limit: Maximum nodes per page (default: 20)
        cursor: Pagination cursor (offset) for next page
        compact: If True, return only path/name/type without connection details

    Returns:
        Dict with child nodes including their connection information.
        When compact=True, inputs/outputs are omitted for reduced payload size.
        Includes pagination metadata: total, returned, has_more, cursor.
    """
    hou = ensure_connected(host, port)

    parent = hou.node(node_path)
    if parent is None:
        return {"status": "error", "message": f"Node not found: {node_path}"}

    children_list: list[dict[str, Any]] = []
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
                    child_info: dict[str, Any] = {
                        "path": child.path(),
                        "name": child.name(),
                        "type": child.type().name(),
                    }
                else:
                    # Full mode: include input/output connection details
                    # Build input connection details
                    input_connections: list[dict[str, Any]] = []
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

    # Apply pagination to collected children
    paginated = paginate_list(children_list, limit=limit, cursor=cursor)

    result: dict[str, Any] = {
        "status": "success",
        "node_path": node_path,
        "children": paginated["items"],
        "count": paginated["returned"],  # Backward compat: count = returned
        "total": paginated["total"],
        "returned": paginated["returned"],
        "has_more": paginated["has_more"],
    }

    if paginated["has_more"]:
        result["cursor"] = paginated["cursor"]

    if nodes_collected >= max_nodes:
        result["warning"] = f"Collection limited to {max_nodes} nodes"

    # Add response size metadata for large responses
    return _add_response_metadata(result)


@handle_connection_errors("find_nodes")
def find_nodes(
    root_path: str = "/obj",
    pattern: str = "*",
    node_type: str | None = None,
    max_results: int | None = None,
    offset: int | None = None,
    limit: int | None = None,
    cursor: int | None = None,
    host: str = "localhost",
    port: int = 18811,
) -> dict[str, Any]:
    """
    Find nodes by name pattern or type using glob/substring matching.

    Args:
        root_path: Root path to start search from
        pattern: Glob pattern or substring to match against node names (* for wildcard)
        node_type: Optional node type filter (e.g., "sphere", "noise", "geo")
        max_results: Maximum number of results to return (default: 100)
                    DEPRECATED: Use limit instead for consistency
        offset: Number of results to skip for pagination (default: 0)
               DEPRECATED: Use cursor instead for consistency
        limit: Maximum number of results per page (default: 100)
              Preferred alias for max_results
        cursor: Pagination cursor/offset (default: 0)
               Preferred alias for offset

    Returns:
        Dict with matching nodes and their types.
        Includes pagination info (has_more, next_offset) when applicable.

    Example:
        find_nodes("/obj", "noise*", max_results=50)
        find_nodes("/obj/geo1", "*", node_type="sphere")
        find_nodes("/obj", "*", offset=100)  # Get next page
    """
    hou = ensure_connected(host, port)

    root = hou.node(root_path)
    if root is None:
        return {"status": "error", "message": f"Root node not found: {root_path}"}

    # Backward-compatible aliases: limit/cursor take precedence over max_results/offset
    if limit is not None:
        max_results = limit
    elif max_results is None:
        max_results = 100

    if cursor is not None:
        offset = cursor
    elif offset is None:
        offset = 0

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
        exec_globals: dict[str, Any] = {
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

    # Calculate pagination metadata
    has_more = total_matched > offset + len(matches)

    result: dict[str, Any] = {
        "status": "success",
        "root_path": root_path,
        "pattern": pattern,
        "matches": matches,
        "count": len(matches),  # Backward compat: count = returned
        "total": total_matched,
        "returned": len(matches),
        "has_more": has_more,
    }

    if node_type:
        result["node_type_filter"] = node_type

    # Add offset for backward compat
    if offset > 0:
        result["offset"] = offset

    # Add cursor for next page
    if has_more:
        result["cursor"] = offset + len(matches)

    if len(matches) >= max_results:
        result["warning"] = (
            f"Results limited to {max_results} nodes. Use offset={offset + max_results} for next page."
        )

    # Add response size metadata for large responses
    return _add_response_metadata(result)
