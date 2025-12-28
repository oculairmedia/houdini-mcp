"""Error detection and introspection tools.

This module provides tools for finding nodes with cook errors
and warnings in the Houdini scene.
"""

import logging
from typing import Any, Dict, List

from ._common import (
    ensure_connected,
    handle_connection_errors,
    _add_response_metadata,
)

logger = logging.getLogger("houdini_mcp.tools.errors")


@handle_connection_errors("find_error_nodes")
def find_error_nodes(
    root_path: str = "/",
    include_warnings: bool = True,
    max_results: int = 100,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Find all nodes with cook errors or warnings in the scene.

    Scans the entire node hierarchy starting from root_path and returns
    all nodes that have errors or warnings. Essential for debugging
    complex scenes where error locations are unknown.

    Args:
        root_path: Root path to start search from (default: "/" for entire scene)
        include_warnings: Whether to include nodes with warnings (default: True)
        max_results: Maximum number of results to return (default: 100)
        host: Houdini RPC server host
        port: Houdini RPC server port

    Returns:
        Dict with error/warning nodes including:
        - error_nodes: List of nodes with errors
        - warning_nodes: List of nodes with warnings (if include_warnings=True)
        - total_scanned: Number of nodes scanned

    Example:
        find_error_nodes()  # Find all errors in scene
        find_error_nodes("/obj/geo1")  # Find errors within a specific network
        find_error_nodes(include_warnings=False)  # Only errors, no warnings
    """
    hou = ensure_connected(host, port)

    root = hou.node(root_path)
    if root is None:
        return {"status": "error", "message": f"Root node not found: {root_path}"}

    error_nodes: List[Dict[str, Any]] = []
    warning_nodes: List[Dict[str, Any]] = []
    total_scanned = 0

    def scan_recursive(node: Any) -> None:
        nonlocal total_scanned

        # Check if we've hit the limit
        total_results = len(error_nodes) + (len(warning_nodes) if include_warnings else 0)
        if total_results >= max_results:
            return

        try:
            # Get all descendant nodes
            all_children = node.allSubChildren()

            for child in all_children:
                total_scanned += 1

                # Check limits again inside loop
                total_results = len(error_nodes) + (len(warning_nodes) if include_warnings else 0)
                if total_results >= max_results:
                    break

                try:
                    # Get errors
                    errors = child.errors()
                    if errors:
                        error_nodes.append(
                            {
                                "path": child.path(),
                                "name": child.name(),
                                "type": child.type().name(),
                                "errors": list(errors) if errors else [],
                            }
                        )

                    # Get warnings if requested
                    if include_warnings:
                        warnings = child.warnings()
                        if warnings:
                            warning_nodes.append(
                                {
                                    "path": child.path(),
                                    "name": child.name(),
                                    "type": child.type().name(),
                                    "warnings": list(warnings) if warnings else [],
                                }
                            )

                except Exception as e:
                    logger.debug(f"Could not check errors on {child.path()}: {e}")

        except Exception as e:
            logger.warning(f"Could not scan children of {node.path()}: {e}")

    # Also check the root node itself if it's not "/"
    if root_path != "/":
        total_scanned += 1
        try:
            errors = root.errors()
            if errors:
                error_nodes.append(
                    {
                        "path": root.path(),
                        "name": root.name(),
                        "type": root.type().name(),
                        "errors": list(errors) if errors else [],
                    }
                )
            if include_warnings:
                warnings = root.warnings()
                if warnings:
                    warning_nodes.append(
                        {
                            "path": root.path(),
                            "name": root.name(),
                            "type": root.type().name(),
                            "warnings": list(warnings) if warnings else [],
                        }
                    )
        except Exception:
            pass

    scan_recursive(root)

    result: Dict[str, Any] = {
        "status": "success",
        "root_path": root_path,
        "error_nodes": error_nodes,
        "error_count": len(error_nodes),
        "total_scanned": total_scanned,
    }

    if include_warnings:
        result["warning_nodes"] = warning_nodes
        result["warning_count"] = len(warning_nodes)

    # Add warning if results were limited
    total_results = len(error_nodes) + (len(warning_nodes) if include_warnings else 0)
    if total_results >= max_results:
        result["warning"] = f"Results limited to {max_results}. Increase max_results to see more."

    return _add_response_metadata(result)
