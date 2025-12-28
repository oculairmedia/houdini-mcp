"""Geometry inspection and summary tools.

This module provides tools for inspecting geometry data in Houdini,
including point/primitive counts, attributes, groups, and sampling.
"""

import json
import logging
import traceback
from typing import Any, Dict

from ._common import (
    ensure_connected,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
    _add_response_metadata,
)

logger = logging.getLogger("houdini_mcp.tools.geometry")


def get_geo_summary(
    node_path: str,
    max_sample_points: int = 100,
    include_attributes: bool = True,
    include_groups: bool = True,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Get geometry statistics and metadata for verification.

    Returns comprehensive geometry information including point/primitive counts,
    bounding box, attributes, groups, and optionally sample points. Useful for
    agents to verify results after operations.

    This function executes geometry analysis on the Houdini side to avoid
    slow RPC iteration over large point/primitive counts.

    Args:
        node_path: Path to the SOP node (e.g., "/obj/geo1/sphere1")
        max_sample_points: Maximum number of sample points to return (default: 100, max: 10000)
        include_attributes: Whether to include attribute metadata (default: True)
        include_groups: Whether to include group information (default: True)

    Returns:
        Dict with geometry summary including:
        - status: "success" or "error"
        - node_path: Path to the node
        - cook_state: "cooked", "dirty", "uncooked", or "error"
        - point_count: Number of points
        - primitive_count: Number of primitives
        - vertex_count: Total number of vertices across all primitives
        - bounding_box: {min, max, size, center} in world space
        - attributes: {point, primitive, vertex, detail} attribute lists
        - groups: {point, primitive} group lists
        - sample_points: Optional list of first N points with attribute values

    Example:
        get_geo_summary("/obj/geo1/sphere1", max_sample_points=50)

    Edge cases:
        - Uncooked geometry: Will attempt to cook first
        - Empty geometry: Returns zeros, not error
        - Massive geometry (>1M points): Caps sampling with warning
        - No bounding box: Returns None for bbox fields
    """
    # Import execute_code here to avoid circular imports
    from .code import execute_code

    # Validate max_sample_points
    if max_sample_points < 0:
        max_sample_points = 0
    elif max_sample_points > 10000:
        logger.warning(f"max_sample_points capped at 10000 (was {max_sample_points})")
        max_sample_points = 10000

    # Build Houdini-side code that does all the heavy lifting locally
    # This avoids slow RPC iteration over geometry elements
    geo_analysis_code = f"""
import json

node_path = {repr(node_path)}
max_sample_points = {max_sample_points}
include_attributes = {include_attributes}
include_groups = {include_groups}

result = {{"status": "success", "node_path": node_path}}

# Get node
node = hou.node(node_path)
if node is None:
    result = {{"status": "error", "message": f"Node not found: {{node_path}}"}}
else:
    # Check cook state
    cook_state = "unknown"
    try:
        if hasattr(node, "needsToCook"):
            if node.needsToCook():
                cook_state = "dirty"
                node.cook(force=True)
            cook_state = "cooked"
    except:
        pass
    result["cook_state"] = cook_state

    # Get geometry
    geo = None
    try:
        geo = node.geometry()
    except:
        pass

    if geo is None:
        result = {{"status": "error", "message": f"Node {{node_path}} has no geometry"}}
    else:
        # Counts - these are fast native calls
        result["point_count"] = geo.intrinsicValue("pointcount")
        result["primitive_count"] = geo.intrinsicValue("primitivecount")
        result["vertex_count"] = geo.intrinsicValue("vertexcount")

        # Bounding box
        try:
            bbox = geo.boundingBox()
            result["bounding_box"] = {{
                "min": list(bbox.minvec()),
                "max": list(bbox.maxvec()),
                "size": list(bbox.sizevec()),
                "center": list(bbox.center()),
            }}
        except:
            result["bounding_box"] = None

        # Attributes
        if include_attributes:
            attributes = {{"point": [], "primitive": [], "vertex": [], "detail": []}}
            
            for attrib in geo.pointAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["point"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            for attrib in geo.primAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["primitive"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            for attrib in geo.vertexAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["vertex"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            for attrib in geo.globalAttribs():
                try:
                    dt = attrib.dataType()
                    dt_name = dt.name() if hasattr(dt, "name") else str(dt)
                    attributes["detail"].append({{"name": attrib.name(), "type": dt_name.lower(), "size": attrib.size()}})
                except:
                    pass
                    
            result["attributes"] = attributes

        # Groups
        if include_groups:
            groups = {{"point": [], "primitive": []}}
            for g in geo.pointGroups():
                try:
                    groups["point"].append(g.name())
                except:
                    pass
            for g in geo.primGroups():
                try:
                    groups["primitive"].append(g.name())
                except:
                    pass
            result["groups"] = groups

        # Sample points - use numpy-style array access if possible
        point_count = result["point_count"]
        if max_sample_points > 0 and point_count > 0:
            if point_count > 1000000:
                result["warning"] = f"Geometry has {{point_count}} points (>1M). Sampling limited."
            
            sample_count = min(max_sample_points, point_count)
            sample_points = []
            
            # Get point attribute names
            point_attrib_names = [a.name() for a in geo.pointAttribs()]
            
            # Sample using efficient access
            for i in range(sample_count):
                pt = geo.point(i)
                if pt is None:
                    continue
                point_data = {{"index": i}}
                for aname in point_attrib_names:
                    try:
                        val = pt.attribValue(aname)
                        if val is not None:
                            if isinstance(val, (tuple, list, hou.Vector2, hou.Vector3, hou.Vector4)):
                                point_data[aname] = list(val)
                            else:
                                point_data[aname] = val
                    except:
                        pass
                sample_points.append(point_data)
            
            result["sample_points"] = sample_points

# Return JSON string
print(json.dumps(result))
"""

    try:
        # Use execute_code to run the analysis on Houdini side
        exec_result = execute_code(
            code=geo_analysis_code,
            capture_diff=False,
            max_stdout_size=500000,  # Allow larger output for geo data
            timeout=30,
            host=host,
            port=port,
        )

        if exec_result.get("status") == "error":
            return exec_result

        # Parse the JSON output from stdout
        stdout = exec_result.get("stdout", "").strip()
        if not stdout:
            return {"status": "error", "message": "No output from geometry analysis"}

        try:
            result = json.loads(stdout)
            return _add_response_metadata(result)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "message": f"Failed to parse geometry data: {e}",
                "raw_output": stdout[:500],
            }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "getting_geometry_summary")
    except Exception as e:
        logger.error(f"Error getting geometry summary: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
