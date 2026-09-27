"""Time-aware, bounded review of deterministic procedural SOP animation."""

import hashlib
import time
from contextlib import contextmanager

from ..core import atomic_json
from ..diagnostics import audit, valid
from ..errors import CompanionError
from ..observation import check_expected, fingerprint, require_node
from ..registry import OperationSpec, PluginSpec
from ..rendering import artifact, render_snapshot
from ..temporal import displacement
from .introspection import PATH, object_schema


def time_state(hou):
    return {
        "frame": hou.frame(),
        "seconds": hou.time(),
        "fps": hou.fps(),
        "frame_range": list(hou.playbar.frameRange()),
        "playback_range": list(hou.playbar.playbackRange()),
        "playing": hou.playbar.isPlaying(),
    }


@contextmanager
def preserve_time(hou):
    before = time_state(hou)
    if before["playing"]:
        hou.playbar.stop()
    try:
        yield before
    finally:
        if hou.frame() != before["frame"]:
            hou.setFrame(before["frame"])
        if before["playing"]:
            hou.playbar.play()


def inspect(ctx, job, path=None, limit=64):
    """Current time context and bounded animated channel readback."""
    result = {
        "time": time_state(ctx.hou),
        "scope": "deterministic SOP sampling; simulation reset/preroll is not automated",
    }
    if path:
        node = require_node(ctx.hou, path)
        channels = []
        for parm in node.parms():
            keys = parm.keyframes()
            if keys:
                channels.append(
                    {
                        "path": parm.path(),
                        "value": parm.eval(),
                        "key_count": len(keys),
                        "keys": [k.asCode() for k in keys[:limit]],
                    }
                )
        result.update(
            path=path,
            time_dependent=node.isTimeDependent(),
            observation=fingerprint(ctx.hou, node),
            channels=channels[:limit],
            truncated=len(channels) > limit,
        )
    return result


def contact_sheet(folder, rows, view):
    try:
        from PySide2.QtCore import Qt
        from PySide2.QtGui import QColor, QImage, QPainter
    except ImportError:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage, QPainter
    width, height, cols = 360, 280, 3
    sheet = QImage(cols * width, ((len(rows) + cols - 1) // cols) * height, QImage.Format_ARGB32)
    sheet.fill(QColor(28, 30, 34))
    painter = QPainter(sheet)
    try:
        for i, row in enumerate(rows):
            image = QImage(str(folder / row["images"][0]["name"]))
            image = image.scaled(width, height - 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x, y = (i % cols) * width, (i // cols) * height
            painter.drawImage(x + (width - image.width()) // 2, y + 32, image)
            painter.setPen(QColor(240, 240, 240))
            painter.drawText(
                x + 8, y + 21, f"Frame {row['frame']:g} | {row['seconds']:.3f}s | {view}"
            )
    finally:
        painter.end()
    path = folder / "contact-sheet.png"
    if not sheet.save(str(path)):
        raise CompanionError("RENDER_FAILED", "Could not save contact sheet")
    return artifact(path, "image")


def sample(
    ctx,
    job,
    path,
    frames,
    expected=None,
    views=None,
    resolution=480,
    require_motion=False,
    require_stable_topology=True,
    max_cook_ms=None,
    max_speed=None,
    focus=None,
):
    """Audit and render explicit frames with fixed framing and a temporal acceptance receipt."""
    total_start = time.perf_counter()
    hou = ctx.hou
    node = require_node(hou, path)
    if not isinstance(node, hou.SopNode):
        raise CompanionError("SOP_REQUIRED", path)
    views = views or ["persp"]
    if len(frames) * len(views) * resolution**2 > 32_000_000:
        raise CompanionError(
            "REVIEW_BUDGET", "Reduce frames, views or resolution below 32 million pixels"
        )
    # Arbitrary stateful simulations require a separate sequential/reset contract.
    deps = [node] + list(node.inputAncestors())
    if any("dop" in n.type().name().lower() or "solver" in n.type().name().lower() for n in deps):
        raise CompanionError(
            "SIMULATION_UNSUPPORTED",
            "Cache simulation first; this contract samples deterministic procedural SOPs",
        )
    ctx.ledger.phase(job["job_id"], "initial_geometry_access")
    initial_start = time.perf_counter()
    node.geometry()
    initial_geometry_access_ms = (time.perf_counter() - initial_start) * 1000
    if isinstance(node.parent(), hou.SopNode):
        node.parent().geometry()
    before = check_expected(hou, node, expected) if expected else fingerprint(hou, node)
    folder = ctx.ledger.root / job["job_id"]
    folder.mkdir(exist_ok=True, parents=True)
    rows, reasons, previous, recipes, repeated = [], [], None, {}, {}
    if max_cook_ms is not None and initial_geometry_access_ms > max_cook_ms:
        reasons.append({"code": "INITIAL_COOK_BUDGET", "actual_ms": initial_geometry_access_ms})
    try:
        with preserve_time(hou) as original:
            for index, frame in enumerate(frames):
                ctx.ledger.checkpoint(job["job_id"])
                ctx.ledger.phase(job["job_id"], f"frame_{index + 1}_of_{len(frames)}")
                count = node.cookCount()
                started = time.perf_counter()
                geo = node.geometryAtFrame(frame)
                cook_ms = (time.perf_counter() - started) * 1000
                if node.errors():
                    raise CompanionError("COOK_FAILED", "; ".join(node.errors()), frame=frame)
                positions = geo.pointFloatAttribValuesAsString("P")
                dest = folder / f"frame-{index:03d}.bgeo.sc"
                geo.saveToFile(str(dest))
                checks = audit(hou, dest, lambda: ctx.ledger.checkpoint(job["job_id"]))
                row = {
                    "frame": frame,
                    "seconds": hou.frameToTime(frame),
                    "geometry": checks,
                    "geometry_artifact": artifact(dest, "geometry"),
                    "cook_ms": cook_ms,
                    "cook_count_delta": node.cookCount() - count,
                    "position_sha256": hashlib.sha256(positions).hexdigest(),
                }
                if not valid(checks):
                    reasons.append({"code": "GEOMETRY_CHECKS", "frame": frame})
                topology = checks["topology_sha256"]
                if previous:
                    same_topology = topology == previous["topology"]
                    row["topology_stable"] = same_topology
                    row["motion"] = (
                        displacement(
                            previous["positions"],
                            positions,
                            hou.frameToTime(frame) - previous["seconds"],
                        )
                        if same_topology
                        else {"comparable": False}
                    )
                    if require_stable_topology and not same_topology:
                        reasons.append({"code": "TOPOLOGY_CHANGED", "frame": frame})
                    speed = row["motion"].get("max_average_speed")
                    if max_speed is not None and speed is not None and speed > max_speed:
                        reasons.append({"code": "SPEED_BUDGET", "frame": frame, "actual": speed})
                if max_cook_ms is not None and cook_ms > max_cook_ms:
                    reasons.append({"code": "COOK_BUDGET", "frame": frame, "actual_ms": cook_ms})
                if frame in repeated and repeated[frame] != checks["semantic_sha256"]:
                    reasons.append({"code": "NONDETERMINISTIC_FRAME", "frame": frame})
                repeated[frame] = checks["semantic_sha256"]
                rows.append(row)
                previous = {"positions": positions, "seconds": row["seconds"], "topology": topology}
            bounds = [r["geometry"]["bounds"] for r in rows if r["geometry"]["bounds"]]
            if not bounds:
                raise CompanionError("EMPTY_GEOMETRY", "No finite geometry to frame")
            focus = focus or [
                [min(b[0][i] for b in bounds) - 0.001 for i in range(3)],
                [max(b[1][i] for b in bounds) + 0.001 for i in range(3)],
            ]
            for index, row in enumerate(rows):
                ctx.ledger.phase(job["job_id"], f"render_{index + 1}_of_{len(rows)}")
                frame = row["frame"]
                dest = folder / row["geometry_artifact"]["name"]
                render_dir = folder / f"render-{index:03d}"
                render_dir.mkdir(exist_ok=True)
                rendered = render_snapshot(
                    hou,
                    dest,
                    render_dir,
                    views,
                    resolution,
                    lambda: ctx.ledger.checkpoint(job["job_id"]),
                    cameras=recipes,
                    focus=focus,
                )
                recipes = rendered["camera_recipes"]
                row["images"] = []
                for image in rendered["images"]:
                    source = render_dir / image["name"]
                    output = folder / f"frame-{index:03d}-{image['name']}"
                    source.replace(output)
                    row["images"].append({**image, "name": output.name})
                    if image["suspect_blank_or_dark"]:
                        reasons.append(
                            {"code": "BLANK_IMAGE", "frame": frame, "view": image["view"]}
                        )
                render_dir.rmdir()
                row["render_ms"] = rendered["render_ms"]
            # Restore source's current-frame cooked cache as well as UI time.
            node.geometry()
            if isinstance(node.parent(), hou.SopNode):
                node.parent().geometry()
            stale = fingerprint(hou, node)["token"] != before["token"]
            if stale:
                reasons.append({"code": "STALE_INPUT"})
    except Exception:
        atomic_json(
            folder / "sequence.json",
            {"complete": False, "frames": rows, "time_restored": time_state(hou)},
        )
        raise
    moved = any(r.get("motion", {}).get("moved_points", 0) > 0 for r in rows)
    if require_motion and not moved:
        reasons.append({"code": "NO_MOTION"})
    sheet = contact_sheet(folder, rows, views[0])
    summary = {
        "accepted": not reasons,
        "reasons": reasons,
        "sample_id": job["job_id"],
        "frame_count": len(rows),
        "frames": frames,
        "motion_detected": moved,
        "topology_stable": all(r.get("topology_stable", True) for r in rows),
        "repeated_frame_checks": len(frames) - len(repeated),
        "cook_ms": [r["cook_ms"] for r in rows],
        "initial_geometry_access_ms": initial_geometry_access_ms,
        "total_ms": (time.perf_counter() - total_start) * 1000,
        "original_time": original,
        "time_after": time_state(hou),
        "artifact_directory": str(folder),
        "contact_sheet": sheet,
        "hip_saved": False,
    }
    atomic_json(
        folder / "sequence.json",
        {
            **summary,
            "complete": True,
            "samples": rows,
            "camera_recipes": recipes,
            "scope": "sampled times; stable point-index correspondence, not continuous collision proof; deterministic procedural SOPs only",
        },
    )
    summary["manifest"] = artifact(folder / "sequence.json", "manifest")
    return summary


def plugin():
    props = {
        "focus": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}},
        },
        "path": PATH,
        "frames": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 32},
        "expected": PATH,
        "views": {
            "type": "array",
            "items": {"type": "string", "enum": ["front", "back", "left", "right", "top", "persp"]},
            "minItems": 1,
            "maxItems": 3,
        },
        "resolution": {"type": "integer", "minimum": 128, "maximum": 1200},
        "require_motion": {"type": "boolean"},
        "require_stable_topology": {"type": "boolean"},
        "max_cook_ms": {"type": "number", "minimum": 0},
        "max_speed": {"type": "number", "minimum": 0},
    }
    return PluginSpec(
        "timeline",
        "0.1.0",
        (
            OperationSpec(
                "timeline.inspect",
                "read",
                object_schema(
                    {"path": PATH, "limit": {"type": "integer", "minimum": 1, "maximum": 128}}
                ),
                inspect,
                inspect.__doc__,
            ),
            OperationSpec(
                "timeline.sample",
                "artifacts",
                object_schema(props, ["path", "frames"]),
                sample,
                sample.__doc__,
            ),
        ),
        requires=("review",),
    )
