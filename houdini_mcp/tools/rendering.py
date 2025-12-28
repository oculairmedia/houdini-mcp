"""Rendering and viewport capture tools.

This module provides tools for rendering the Houdini viewport
and capturing images for AI analysis.
"""

import base64
import logging
import math
import traceback
from typing import Any, Dict, List, Optional

from ._common import (
    ensure_connected,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
    get_connection,
)

logger = logging.getLogger("houdini_mcp.tools.rendering")


def _get_remote_modules():
    """Get remote os and tempfile modules via RPyC for file operations on Houdini machine."""
    conn = get_connection()
    if conn is None:
        raise HoudiniConnectionError("No active connection to Houdini")
    # Access remote modules through the RPyC connection
    remote_os = conn.modules.os
    remote_tempfile = conn.modules.tempfile
    return remote_os, remote_tempfile


def render_viewport(
    camera_position: Optional[List[float]] = None,
    camera_rotation: Optional[List[float]] = None,
    look_at: Optional[str] = None,
    resolution: Optional[List[int]] = None,
    renderer: str = "opengl",
    output_format: str = "png",
    auto_frame: bool = True,
    orthographic: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Render the viewport and return the image as base64.

    Creates a temporary camera, positions it to frame the scene geometry,
    renders the scene, and returns the rendered image encoded as base64.

    Args:
        camera_position: [x, y, z] world position for camera (default: auto-calculated)
        camera_rotation: [rx, ry, rz] rotation in degrees (default: [-30, 45, 0] isometric)
        look_at: Node path to look at (centers camera on this node's geometry)
        resolution: [width, height] in pixels (default: [512, 512])
        renderer: Render engine - "opengl" (fast) or "karma" (quality)
        output_format: Image format - "png", "jpg", or "exr"
        auto_frame: If True, automatically frame all visible geometry (default: True)
        orthographic: If True, use orthographic projection (default: False)

    Returns:
        Dict with:
        - status: "success" or "error"
        - image_base64: Base64-encoded image data
        - format: Image format used
        - resolution: [width, height]
        - camera_path: Path to the temporary camera used
        - bounding_box: Scene bounding box if auto_frame was used

    Example:
        render_viewport()  # Auto-frame scene with isometric view
        render_viewport(camera_rotation=[0, 0, 0])  # Front view
        render_viewport(camera_rotation=[-90, 0, 0])  # Top view
        render_viewport(look_at="/obj/geo1", orthographic=True)
    """
    try:
        hou = ensure_connected(host, port)

        # Set defaults
        if resolution is None:
            resolution = [512, 512]
        if camera_rotation is None:
            camera_rotation = [-30.0, 45.0, 0.0]  # Isometric view

        # Validate resolution
        width, height = resolution[0], resolution[1]
        if width < 64 or height < 64:
            return {"status": "error", "message": "Resolution must be at least 64x64"}
        if width > 4096 or height > 4096:
            return {"status": "error", "message": "Resolution cannot exceed 4096x4096"}

        # Get /obj context
        obj_context = hou.node("/obj")
        if obj_context is None:
            return {"status": "error", "message": "Cannot find /obj context"}

        # Calculate bounding box of visible geometry if auto_frame
        bbox_info = None
        bbox_center = [0.0, 0.0, 0.0]
        bbox_size = 10.0  # Default size

        if auto_frame:
            # Find all displayed geometry nodes
            displayed_geo = []
            for node in obj_context.children():
                try:
                    node_type = node.type().name()
                    if node_type in ["geo", "subnet"] and node.isDisplayFlagSet():
                        displayed_geo.append(node)
                except Exception:
                    continue

            # Calculate collective bounding box
            if displayed_geo:
                min_bounds = [float("inf")] * 3
                max_bounds = [float("-inf")] * 3

                for node in displayed_geo:
                    try:
                        display_node = node.displayNode()
                        if display_node is None:
                            continue
                        geo = display_node.geometry()
                        if geo is None:
                            continue
                        bbox = geo.boundingBox()
                        if bbox is None:
                            continue

                        # Get node's world transform
                        transform = node.worldTransform()

                        # Transform bounding box corners
                        for x in [bbox.minvec()[0], bbox.maxvec()[0]]:
                            for y in [bbox.minvec()[1], bbox.maxvec()[1]]:
                                for z in [bbox.minvec()[2], bbox.maxvec()[2]]:
                                    point = hou.Vector4(x, y, z, 1.0)
                                    transformed = point * transform
                                    min_bounds[0] = min(min_bounds[0], transformed[0])
                                    min_bounds[1] = min(min_bounds[1], transformed[1])
                                    min_bounds[2] = min(min_bounds[2], transformed[2])
                                    max_bounds[0] = max(max_bounds[0], transformed[0])
                                    max_bounds[1] = max(max_bounds[1], transformed[1])
                                    max_bounds[2] = max(max_bounds[2], transformed[2])
                    except Exception as e:
                        logger.debug(f"Error getting bbox for {node.path()}: {e}")
                        continue

                if min_bounds[0] != float("inf"):
                    bbox_center = [
                        (min_bounds[0] + max_bounds[0]) / 2,
                        (min_bounds[1] + max_bounds[1]) / 2,
                        (min_bounds[2] + max_bounds[2]) / 2,
                    ]
                    bbox_size = max(
                        max_bounds[0] - min_bounds[0],
                        max_bounds[1] - min_bounds[1],
                        max_bounds[2] - min_bounds[2],
                    )
                    bbox_info = {
                        "min": min_bounds,
                        "max": max_bounds,
                        "center": bbox_center,
                        "size": bbox_size,
                    }

        # Override center if look_at is specified
        if look_at:
            target_node = hou.node(look_at)
            if target_node:
                try:
                    # Try to get geometry center
                    display_node = (
                        target_node.displayNode() if hasattr(target_node, "displayNode") else None
                    )
                    if display_node:
                        geo = display_node.geometry()
                        if geo:
                            bbox = geo.boundingBox()
                            if bbox:
                                bbox_center = list(bbox.center())
                                bbox_size = max(bbox.sizevec())
                except Exception:
                    # Fall back to node transform
                    try:
                        bbox_center = [
                            target_node.parm("tx").eval() if target_node.parm("tx") else 0,
                            target_node.parm("ty").eval() if target_node.parm("ty") else 0,
                            target_node.parm("tz").eval() if target_node.parm("tz") else 0,
                        ]
                    except Exception:
                        pass

        # Create camera null (for rotation pivot) and camera
        null_name = "_mcp_cam_center"
        cam_name = "_mcp_render_cam"

        # Delete existing nodes
        existing_null = obj_context.node(null_name)
        if existing_null:
            existing_null.destroy()
        existing_cam = obj_context.node(cam_name)
        if existing_cam:
            existing_cam.destroy()

        # Create null at bbox center
        null = obj_context.createNode("null", null_name)
        null.parmTuple("t").set(bbox_center)
        null.parmTuple("r").set(camera_rotation)

        # Create camera as child of null
        camera = obj_context.createNode("cam", cam_name)
        camera.setFirstInput(null)

        # Calculate camera distance to frame geometry
        # Using FOV and bbox size
        fov_degrees = 45.0  # Default FOV
        padding = 1.2  # 20% padding
        distance = (bbox_size * padding / 2) / math.tan(math.radians(fov_degrees / 2))
        distance = max(5.0, distance + bbox_size / 2)  # Ensure minimum distance

        # Position camera along Z axis (it will be rotated by null)
        if camera_position:
            camera.parmTuple("t").set(camera_position)
        else:
            camera.parmTuple("t").set([0, 0, distance])

        # Set resolution
        camera.parm("resx").set(width)
        camera.parm("resy").set(height)

        # Set projection type
        if orthographic:
            camera.parm("projection").set(1)  # Orthographic
            # Set ortho width to frame geometry
            camera.parm("orthowidth").set(bbox_size * padding)
        else:
            camera.parm("projection").set(0)  # Perspective

        # Get remote modules for file operations on the Houdini machine
        remote_os, remote_tempfile = _get_remote_modules()

        # Create temp file for output ON THE REMOTE MACHINE
        suffix = f".{output_format}"
        fd, output_path = remote_tempfile.mkstemp(suffix=suffix)
        remote_os.close(fd)

        try:
            out_context = hou.node("/out")
            if out_context is None:
                return {"status": "error", "message": "Cannot find /out context"}

            # Render using OpenGL or Karma
            if renderer.lower() == "opengl":
                rop_name = "_mcp_opengl_rop"
                rop = out_context.node(rop_name)
                if rop is None:
                    rop = out_context.createNode("opengl", rop_name)

                rop.parm("camera").set(camera.path())
                rop.parm("picture").set(output_path)
                if rop.parm("tres"):
                    rop.parm("tres").set(True)
                if rop.parm("res1"):
                    rop.parm("res1").set(width)
                if rop.parm("res2"):
                    rop.parm("res2").set(height)
                if rop.parm("trange"):
                    rop.parm("trange").set(0)  # Current frame only
                rop.render()

            elif renderer.lower() == "karma":
                rop_name = "_mcp_karma_rop"
                rop = out_context.node(rop_name)
                if rop is None:
                    rop = out_context.createNode("karma", rop_name)

                rop.parm("camera").set(camera.path())
                rop.parm("picture").set(output_path)
                if rop.parm("resolutionx"):
                    rop.parm("resolutionx").set(width)
                if rop.parm("resolutiony"):
                    rop.parm("resolutiony").set(height)
                if rop.parm("trange"):
                    rop.parm("trange").set(0)
                rop.render()
            else:
                return {"status": "error", "message": f"Unknown renderer: {renderer}"}

            # Read rendered image from REMOTE MACHINE and encode as base64
            if remote_os.path.exists(output_path):
                with remote_os.fdopen(remote_os.open(output_path, remote_os.O_RDONLY), "rb") as f:
                    image_data = f.read()
                image_base64 = base64.b64encode(image_data).decode("utf-8")

                result = {
                    "status": "success",
                    "image_base64": image_base64,
                    "format": output_format,
                    "resolution": [width, height],
                    "camera_path": camera.path(),
                    "renderer": renderer,
                }
                if bbox_info:
                    result["bounding_box"] = bbox_info
                return result
            else:
                return {"status": "error", "message": "Render completed but output file not found"}

        finally:
            # Clean up temp file on remote machine
            if remote_os.path.exists(output_path):
                try:
                    remote_os.remove(output_path)
                except Exception:
                    pass

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "rendering_viewport")
    except Exception as e:
        logger.error(f"Error rendering viewport: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def render_quad_view(
    resolution: Optional[List[int]] = None,
    renderer: str = "opengl",
    output_format: str = "png",
    orthographic: bool = True,
    include_perspective: bool = True,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Render 4 canonical views (Front, Left, Top, Perspective) in one call.

    Creates a camera rig and renders standardized views for spatial understanding.
    Returns all 4 images as base64-encoded strings. This is more efficient than
    calling render_viewport 4 times as it reuses the camera rig and calculates
    the bounding box only once.

    Args:
        resolution: [width, height] in pixels (default: [512, 512])
        renderer: Render engine - "opengl" (fast) or "karma" (quality)
        output_format: Image format - "png", "jpg", or "exr"
        orthographic: If True, use orthographic projection for Front/Left/Top views (default: True)
        include_perspective: If True, include perspective view; if False, only orthographic views (default: True)

    Returns:
        Dict with:
        - status: "success" or "error"
        - views: List of view results, each containing:
            - name: View name (front, left, top, perspective)
            - rotation: [rx, ry, rz] camera rotation used
            - image_base64: Base64-encoded image data
            - format: Image format used
            - resolution: [width, height]
            - orthographic: Whether orthographic projection was used
        - bounding_box: Scene bounding box info
        - renderer: Render engine used
        - total_render_time_ms: Total time for all renders

    Examples:
        render_quad_view()  # All 4 views with orthographic projection
        render_quad_view(orthographic=False)  # All views with perspective
        render_quad_view(resolution=[1024, 1024], renderer="karma")  # Higher quality
        render_quad_view(include_perspective=False)  # Only 3 orthographic views
    """
    import time

    start_time = time.time()

    try:
        hou = ensure_connected(host, port)

        # Set defaults
        if resolution is None:
            resolution = [512, 512]

        # Validate resolution
        width, height = resolution[0], resolution[1]
        if width < 64 or height < 64:
            return {"status": "error", "message": "Resolution must be at least 64x64"}
        if width > 4096 or height > 4096:
            return {"status": "error", "message": "Resolution cannot exceed 4096x4096"}

        # Get remote modules for file operations on the Houdini machine
        remote_os, remote_tempfile = _get_remote_modules()

        # Define the 4 canonical views
        # Using rotations that match standard 3D viewport conventions
        views_config = [
            {"name": "front", "rotation": [0.0, 0.0, 0.0], "ortho": orthographic},
            {"name": "left", "rotation": [0.0, -90.0, 0.0], "ortho": orthographic},
            {"name": "top", "rotation": [-90.0, 0.0, 0.0], "ortho": orthographic},
        ]

        if include_perspective:
            # Isometric-like perspective view
            views_config.append(
                {"name": "perspective", "rotation": [-30.0, 45.0, 0.0], "ortho": False}
            )

        # Get /obj context
        obj_context = hou.node("/obj")
        if obj_context is None:
            return {"status": "error", "message": "Cannot find /obj context"}

        # Calculate bounding box of visible geometry (do this ONCE for all views)
        bbox_info = None
        bbox_center = [0.0, 0.0, 0.0]
        bbox_size = 10.0  # Default size

        # Find all displayed geometry nodes
        displayed_geo = []
        for node in obj_context.children():
            try:
                node_type = node.type().name()
                if node_type in ["geo", "subnet"] and node.isDisplayFlagSet():
                    displayed_geo.append(node)
            except Exception:
                continue

        # Calculate collective bounding box
        if displayed_geo:
            min_bounds = [float("inf")] * 3
            max_bounds = [float("-inf")] * 3

            for node in displayed_geo:
                try:
                    display_node = node.displayNode()
                    if display_node is None:
                        continue
                    geo = display_node.geometry()
                    if geo is None:
                        continue
                    bbox = geo.boundingBox()
                    if bbox is None:
                        continue

                    # Get node's world transform
                    transform = node.worldTransform()

                    # Transform bounding box corners
                    for x in [bbox.minvec()[0], bbox.maxvec()[0]]:
                        for y in [bbox.minvec()[1], bbox.maxvec()[1]]:
                            for z in [bbox.minvec()[2], bbox.maxvec()[2]]:
                                point = hou.Vector4(x, y, z, 1.0)
                                transformed = point * transform
                                min_bounds[0] = min(min_bounds[0], transformed[0])
                                min_bounds[1] = min(min_bounds[1], transformed[1])
                                min_bounds[2] = min(min_bounds[2], transformed[2])
                                max_bounds[0] = max(max_bounds[0], transformed[0])
                                max_bounds[1] = max(max_bounds[1], transformed[1])
                                max_bounds[2] = max(max_bounds[2], transformed[2])
                except Exception as e:
                    logger.debug(f"Error getting bbox for {node.path()}: {e}")
                    continue

            if min_bounds[0] != float("inf"):
                bbox_center = [
                    (min_bounds[0] + max_bounds[0]) / 2,
                    (min_bounds[1] + max_bounds[1]) / 2,
                    (min_bounds[2] + max_bounds[2]) / 2,
                ]
                bbox_size = max(
                    max_bounds[0] - min_bounds[0],
                    max_bounds[1] - min_bounds[1],
                    max_bounds[2] - min_bounds[2],
                )
                bbox_info = {
                    "min": min_bounds,
                    "max": max_bounds,
                    "center": bbox_center,
                    "size": bbox_size,
                }

        # Create camera rig (null + camera) - reused for all views
        null_name = "_mcp_quad_cam_center"
        cam_name = "_mcp_quad_render_cam"

        # Delete existing nodes
        existing_null = obj_context.node(null_name)
        if existing_null:
            existing_null.destroy()
        existing_cam = obj_context.node(cam_name)
        if existing_cam:
            existing_cam.destroy()

        # Create null at bbox center
        null = obj_context.createNode("null", null_name)
        null.parmTuple("t").set(bbox_center)

        # Create camera as child of null
        camera = obj_context.createNode("cam", cam_name)
        camera.setFirstInput(null)

        # Set camera resolution
        camera.parm("resx").set(width)
        camera.parm("resy").set(height)

        # Calculate camera distance to frame geometry
        fov_degrees = 45.0
        padding = 1.2  # 20% padding
        distance = (bbox_size * padding / 2) / math.tan(math.radians(fov_degrees / 2))
        distance = max(5.0, distance + bbox_size / 2)

        # Get/create render context
        out_context = hou.node("/out")
        if out_context is None:
            return {"status": "error", "message": "Cannot find /out context"}

        # Create/get render ROP based on renderer
        if renderer.lower() == "opengl":
            rop_name = "_mcp_quad_opengl_rop"
            rop = out_context.node(rop_name)
            if rop is None:
                rop = out_context.createNode("opengl", rop_name)
        elif renderer.lower() == "karma":
            rop_name = "_mcp_quad_karma_rop"
            rop = out_context.node(rop_name)
            if rop is None:
                rop = out_context.createNode("karma", rop_name)
        else:
            return {"status": "error", "message": f"Unknown renderer: {renderer}"}

        # Render each view
        view_results = []

        for view_config in views_config:
            view_name = view_config["name"]
            rotation = view_config["rotation"]
            is_ortho = view_config["ortho"]

            try:
                # Set null rotation for this view
                null.parmTuple("r").set(rotation)

                # Position camera along Z axis
                camera.parmTuple("t").set([0, 0, distance])

                # Set projection type
                if is_ortho:
                    camera.parm("projection").set(1)  # Orthographic
                    camera.parm("orthowidth").set(bbox_size * padding)
                else:
                    camera.parm("projection").set(0)  # Perspective

                # Create temp file for output ON THE REMOTE MACHINE
                suffix = f".{output_format}"
                fd, output_path = remote_tempfile.mkstemp(suffix=suffix)
                remote_os.close(fd)

                try:
                    # Configure and render
                    if renderer.lower() == "opengl":
                        rop.parm("camera").set(camera.path())
                        rop.parm("picture").set(output_path)
                        if rop.parm("tres"):
                            rop.parm("tres").set(True)
                        if rop.parm("res1"):
                            rop.parm("res1").set(width)
                        if rop.parm("res2"):
                            rop.parm("res2").set(height)
                        if rop.parm("trange"):
                            rop.parm("trange").set(0)
                        rop.render()
                    elif renderer.lower() == "karma":
                        rop.parm("camera").set(camera.path())
                        rop.parm("picture").set(output_path)
                        if rop.parm("resolutionx"):
                            rop.parm("resolutionx").set(width)
                        if rop.parm("resolutiony"):
                            rop.parm("resolutiony").set(height)
                        if rop.parm("trange"):
                            rop.parm("trange").set(0)
                        rop.render()

                    # Read and encode image from REMOTE MACHINE
                    if remote_os.path.exists(output_path):
                        with remote_os.fdopen(
                            remote_os.open(output_path, remote_os.O_RDONLY), "rb"
                        ) as f:
                            image_data = f.read()
                        image_base64 = base64.b64encode(image_data).decode("utf-8")

                        view_results.append(
                            {
                                "name": view_name,
                                "rotation": rotation,
                                "image_base64": image_base64,
                                "format": output_format,
                                "resolution": [width, height],
                                "orthographic": is_ortho,
                            }
                        )
                    else:
                        view_results.append(
                            {
                                "name": view_name,
                                "rotation": rotation,
                                "error": "Render completed but output file not found",
                            }
                        )

                finally:
                    # Clean up temp file on remote machine
                    if remote_os.path.exists(output_path):
                        try:
                            remote_os.remove(output_path)
                        except Exception:
                            pass

            except Exception as e:
                view_results.append(
                    {
                        "name": view_name,
                        "rotation": rotation,
                        "error": str(e),
                    }
                )

        # Calculate total render time
        total_time_ms = (time.time() - start_time) * 1000

        result = {
            "status": "success",
            "views": view_results,
            "renderer": renderer,
            "total_render_time_ms": round(total_time_ms, 1),
        }

        if bbox_info:
            result["bounding_box"] = bbox_info

        return result

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "render_quad_view")
    except Exception as e:
        logger.error(f"Error in render_quad_view: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
