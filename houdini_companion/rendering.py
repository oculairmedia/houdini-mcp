"""Render immutable geometry through owned cameras, lights and an OpenGL ROP."""

from __future__ import annotations

import hashlib
import math
import time
from itertools import product
from pathlib import Path

from .core import CompanionError


def artifact(path, kind):
    path = Path(path)
    if not path.is_file() or not path.stat().st_size:
        raise CompanionError("EMPTY_ARTIFACT", f"No output was produced: {path.name}")
    return {
        "name": path.name,
        "kind": kind,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def image_metrics(path):
    try:
        from PySide2.QtGui import QImage
    except ImportError:
        from PySide6.QtGui import QImage
    img = QImage(str(path))
    if img.isNull():
        raise CompanionError("INVALID_IMAGE", "Rendered file could not be decoded")
    pixels = [
        img.pixelColor(x, y)
        for y in range(0, img.height(), max(1, img.height() // 64))
        for x in range(0, img.width(), max(1, img.width() // 64))
    ]
    luminance = [(0.2126 * p.redF() + 0.7152 * p.greenF() + 0.0722 * p.blueF()) for p in pixels]
    mean = sum(luminance) / len(luminance)
    variance = sum((v - mean) ** 2 for v in luminance) / len(luminance)
    coverage = sum(p.alphaF() > 0.1 for p in pixels) / len(pixels)
    return {
        "alpha_coverage": round(coverage, 4),
        "coverage_method": "sampled alpha on approximately 64x64 grid",
        "width": img.width(),
        "height": img.height(),
        "mean_luminance": round(mean, 4),
        "luminance_variance": round(variance, 6),
        "suspect_blank_or_dark": mean < 0.015 or variance < 0.00001,
    }


def projected_window(position_buffer, inverse_camera, tan_half_fov, margin=0.8):
    """Fit actual point projections; bbox corners overestimate sparse tall scenes."""
    import numpy as np

    points = np.frombuffer(position_buffer, dtype=np.float32).reshape(-1, 3)
    matrix = np.asarray(inverse_camera).reshape(4, 4)
    camera = points @ matrix[:3, :3] + matrix[3, :3]
    if not len(points) or not np.isfinite(camera).all() or np.any(camera[:, 2] >= 0):
        raise CompanionError(
            "INVALID_FRAMING", "Automatic framing requires finite points ahead of camera"
        )
    projected = camera[:, :2] / (-camera[:, 2, None] * tan_half_fov)
    lo, hi = projected.min(axis=0), projected.max(axis=0)
    center = (lo + hi) / 4  # Camera window offsets use full aperture units.
    size = max(float(max(hi - lo)) / (2 * margin), 0.01)
    return float(center[0]), float(center[1]), size


def render_snapshot(
    hou, geometry_path, directory, views, resolution, checkpoint, focus=None, cameras=None
):
    directions = {
        "front": (0, 0.1, -1),
        "back": (0, 0.1, 1),
        "left": (-1, 0.1, 0),
        "right": (1, 0.1, 0),
        "top": (0.001, 1, 0.001),
        "persp": (1, 0.65, -1),
    }
    cameras = cameras or {}
    if not views or len(views) > 6 or any(v not in directions and v not in cameras for v in views):
        raise CompanionError("INVALID_VIEWS", "Choose 1–6 front/back/left/right/top/persp views")
    if not isinstance(resolution, int) or not 128 <= resolution <= 1600:
        raise CompanionError("INVALID_RESOLUTION", "Resolution must be 128–1600")
    created, images, recipes = [], [], {}
    started = time.perf_counter()

    def own(parent, kind):
        node = parent.createNode(kind, "__companion_review")
        node.setUserData("houdini_companion_owner", str(directory))
        created.append(node)
        return node

    with hou.undos.disabler():
        try:
            obj = hou.node("/obj")
            geo = own(obj, "geo")
            geo.setDisplayFlag(False)
            file = geo.createNode("file", "frozen_geometry")
            file.parm("file").set(str(geometry_path))
            file.setDisplayFlag(True)
            file.setRenderFlag(True)
            material = own(hou.node("/mat"), "principledshader::2.0")
            material.parmTuple("basecolor").set((1, 1, 1))
            material.parm("reflect").set(0)
            material.parm("rough").set(1)
            geo.parm("shop_materialpath").set(material.path())
            bounds = file.geometry().boundingBox()
            lo, hi = bounds.minvec(), bounds.maxvec()
            if focus is not None:
                if (
                    not isinstance(focus, list)
                    or len(focus) != 2
                    or any(not isinstance(side, list) or len(side) != 3 for side in focus)
                    or not all(
                        isinstance(v, (int, float)) and math.isfinite(v)
                        for side in focus
                        for v in side
                    )
                    or any(focus[0][i] >= focus[1][i] for i in range(3))
                ):
                    raise CompanionError(
                        "INVALID_FOCUS", "focus must be finite [[minx,miny,minz],[maxx,maxy,maxz]]"
                    )
                lo, hi = hou.Vector3(focus[0]), hou.Vector3(focus[1])
            target = [(lo[i] + hi[i]) / 2 for i in range(3)]
            radius = max(0.01, (hi - lo).length() / 2)
            cam = own(obj, "cam")
            cam.parm("focal").set(35)
            camera_defaults = {
                p: cam.parm(p).eval()
                for p in (
                    "focal",
                    "aperture",
                    "projection",
                    "orthowidth",
                    "aspect",
                    "winx",
                    "winy",
                    "winsizex",
                    "winsizey",
                )
            }
            lights = []
            for rot, intensity in [
                ((-40, 35, 0), 0.9),
                ((-25, -140, 0), 0.55),
                ((-75, 170, 0), 0.35),
            ]:
                light = own(obj, "hlight::2.0")
                light.parm("light_type").set("distant")
                light.parmTuple("r").set(rot)
                light.parm("light_intensity").set(intensity)
                lights.append(light.path())
            rop = own(hou.node("/out"), "opengl")
            settings = {
                "camera": cam.path(),
                "vobjects": "",
                "forceobjects": geo.path(),
                "alights": " ".join(lights),
                "forcelights": " ".join(lights),
                "tres": 1,
                "res1": resolution,
                "res2": resolution,
                "shadingmode": 6,
                "hqlighting": 1,
                # Neutral geometry inspection must not bury errors in shadow maps.
                "shadows": 0,
                "ambocclusion": 0,
                "backfacecull": 1,
                "usegeocolor": 1,
                "usetextures": 0,
                "colorcorrect": 1,
                "gamma": 2.2,
                "aamode": 3,
            }
            for name, value in settings.items():
                if rop.parm(name):
                    rop.parm(name).set(value)
            for view in views:
                checkpoint()
                for name, value in camera_defaults.items():
                    cam.parm(name).set(value)
                rop.parm("res2").set(resolution)
                direction = hou.Vector3(directions.get(view, directions["persp"])).normalized()
                forward = -direction
                right = forward.cross(hou.Vector3((0, 1, 0))).normalized()
                up = right.cross(forward).normalized()
                tan_half_fov = cam.parm("aperture").eval() / (2 * cam.parm("focal").eval())
                corners = [
                    hou.Vector3(p) - hou.Vector3(target)
                    for p in product(*[(lo[i], hi[i]) for i in range(3)])
                ]
                distance = max(
                    v.dot(direction) + max(abs(v.dot(right)), abs(v.dot(up))) / (tan_half_fov * 0.8)
                    for v in corners
                )
                eye = hou.Vector3(target) + direction * max(radius, distance + 0.02 * radius)
                delta = hou.Vector3(target) - eye
                cam.parmTuple("t").set(tuple(eye))
                cam.parmTuple("r").set(
                    (
                        math.degrees(math.atan2(delta[1], math.hypot(delta[0], delta[2]))),
                        math.degrees(math.atan2(-delta[0], -delta[2])),
                        0,
                    )
                )
                cam.parm("near").set(max(0.01, radius * 0.002))
                cam.parm("far").set(max(10, (eye - hou.Vector3(target)).length() + radius * 4))
                if view in cameras:
                    recipe = cameras[view]
                    cam.setWorldTransform(hou.Matrix4(recipe["transform"]))
                    for name, value in recipe["parms"].items():
                        cam.parm(name).set(value)
                    rop.parm("res2").set(max(1, round(resolution / recipe.get("output_aspect", 1))))
                elif focus is None:
                    winx, winy, size = projected_window(
                        file.geometry().pointFloatAttribValuesAsString("P"),
                        cam.worldTransform().inverted().asTuple(),
                        tan_half_fov,
                    )
                    cam.parm("winx").set(winx)
                    cam.parm("winy").set(winy)
                    cam.parm("winsizex").set(size)
                    cam.parm("winsizey").set(size)
                cam.parm("resx").set(resolution)
                cam.parm("resy").set(rop.parm("res2").eval())
                recipes[view] = {
                    "transform": list(cam.worldTransform().asTuple()),
                    "parms": {p: cam.parm(p).eval() for p in camera_defaults},
                    "output_aspect": resolution / rop.parm("res2").eval(),
                }
                path = Path(directory) / f"{view}.png"
                rop.parm("picture").set(str(path))
                rop.render()
                if rop.errors():
                    raise CompanionError("RENDER_FAILED", "; ".join(rop.errors()))
                images.append(
                    {
                        **artifact(path, "image"),
                        "view": view,
                        **image_metrics(path),
                        "camera": {
                            "transform": list(cam.worldTransform().asTuple()),
                            "near": cam.parm("near").eval(),
                            "far": cam.parm("far").eval(),
                        },
                    }
                )
        finally:
            for node in reversed(created):
                try:
                    node.destroy()
                except hou.ObjectWasDeleted:
                    pass
    return {
        "images": images,
        "camera_recipes": recipes,
        "render_ms": round((time.perf_counter() - started) * 1000, 2),
        "coordinates": "SOP local space",
        "renderer": "opengl",
        "backface_culling": True,
        "focus": focus,
        "lighting_profile": "neutral diffuse diagnostic, specular and shadows disabled",
    }
