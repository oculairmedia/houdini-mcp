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


def render_snapshot(hou, geometry_path, directory, views, resolution, checkpoint, focus=None):
    directions = {
        "front": (0, 0.1, -1),
        "back": (0, 0.1, 1),
        "left": (-1, 0.1, 0),
        "right": (1, 0.1, 0),
        "top": (0.001, 1, 0.001),
        "persp": (1, 0.65, -1),
    }
    if not views or len(views) > 6 or any(v not in directions for v in views):
        raise CompanionError("INVALID_VIEWS", "Choose 1–6 front/back/left/right/top/persp views")
    if not isinstance(resolution, int) or not 128 <= resolution <= 1600:
        raise CompanionError("INVALID_RESOLUTION", "Resolution must be 128–1600")
    created, images = [], []
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
                "shadows": 1,
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
                direction = hou.Vector3(directions[view]).normalized()
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
                cam.parm("near").set(max(0.001, radius * 0.001))
                cam.parm("far").set(max(100, radius * 20))
                path = Path(directory) / f"{view}.png"
                rop.parm("picture").set(str(path))
                rop.render()
                if rop.errors():
                    raise CompanionError("RENDER_FAILED", "; ".join(rop.errors()))
                images.append({**artifact(path, "image"), "view": view, **image_metrics(path)})
        finally:
            for node in reversed(created):
                try:
                    node.destroy()
                except hou.ObjectWasDeleted:
                    pass
    return {
        "images": images,
        "render_ms": round((time.perf_counter() - started) * 1000, 2),
        "coordinates": "SOP local space",
        "renderer": "opengl",
        "backface_culling": True,
        "focus": focus,
    }
