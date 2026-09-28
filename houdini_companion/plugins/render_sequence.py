"""Resumable explicit one-frame jobs; no HOM object survives an event-loop yield."""

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path

from ..core import atomic_json
from ..errors import CompanionError
from ..observation import check_expected, fingerprint, require_node
from ..registry import OperationSpec, PluginSpec
from ..rendering import artifact, render_snapshot
from ..state_guard import StateGuard
from .introspection import PATH, object_schema


@lru_cache(maxsize=4096)
def cached_hash(path, mtime, ctime, size):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_ok(folder, item, strict=False):
    name = item.get("name", "")
    path = folder / name
    if Path(name).name != name or not path.is_file():
        return False
    stat = path.stat()
    value = (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if strict
        else cached_hash(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    )
    return value == item.get("sha256")


def completed(folder, row):
    return bool(row and row.get("images")) and all(
        file_ok(folder, item) for item in [row["geometry_artifact"], *row["images"]]
    )


def get(ctx, render_id):
    record = ctx.state.get("render_sequences", {}).get(render_id)
    if not record:
        raise CompanionError(
            "RENDER_NOT_FOUND",
            "No pinned render in this runtime; never replay across restart automatically",
        )
    folder = ctx.ledger.root / render_id
    data = json.loads((folder / "render-sequence.json").read_text(encoding="utf-8"))
    if data["scene_id"] != ctx.ledger.scene_id or data["session_id"] != ctx.ledger.session_id:
        raise CompanionError("STALE_SCENE", "Sequence belongs to another scene/session")
    return folder, data


def summary(folder, data):
    done = sum(completed(folder, row) for row in data["rows"])
    return {
        "render_id": data["render_id"],
        "completed": done,
        "total": len(data["frames"]),
        "complete": done == len(data["frames"]),
        "paused": data["paused"],
        "manifest": str(folder / "render-sequence.json"),
        "source": data["path"],
        "next_operation": None if done == len(data["frames"]) else "render.step",
    }


def start(ctx, job, path, frames, cameras, resolution=640):
    """Pin source and fixed camera observations; each render.step processes at most one frame."""
    if frames != sorted(set(frames)):
        raise CompanionError("FRAMES", "Frames must be unique and increasing")
    if len(frames) * len(cameras) * resolution**2 > 256_000_000:
        raise CompanionError("RENDER_BUDGET", "Sequence exceeds 256 million square-pixel budget")
    states = ctx.state.setdefault("render_sequences", {})
    if len(states) >= 16:
        raise CompanionError("RENDER_LIMIT", "Release an earlier pinned sequence")
    h = ctx.hou
    node = require_node(h, path)
    if not isinstance(node, h.SopNode):
        raise CompanionError("SOP_REQUIRED", path)
    if any(
        "dop" in n.type().name().lower() or "solver" in n.type().name().lower()
        for n in [node, *node.inputAncestors()]
    ):
        raise CompanionError("SIMULATION_UNSUPPORTED", "Cache stateful simulation before rendering")
    obj = node.parent()
    while obj is not None and not isinstance(obj, h.ObjNode):
        obj = obj.parent()
    if obj is None:
        raise CompanionError("OBJECT_REQUIRED", "SOP needs an object transform")
    recipes, camera_tokens = {}, {}
    with StateGuard(h) as state:
        node.geometry()
        expected = fingerprint(h, node)["token"]
        for index, path_cam in enumerate(cameras):
            cam = require_node(h, path_cam)
            if cam.type().name() != "cam":
                raise CompanionError("CAMERA_REQUIRED", path_cam)
            camera_tokens[path_cam] = fingerprint(h, cam)["token"]
            recipes[f"view{index}"] = {
                "transform": list(
                    (cam.worldTransform() * obj.worldTransform().inverted()).asTuple()
                ),
                "parms": {
                    p: cam.parm(p).eval()
                    for p in (
                        "focal",
                        "aperture",
                        "projection",
                        "aspect",
                        "winx",
                        "winy",
                        "winsizex",
                        "winsizey",
                        "near",
                        "far",
                    )
                },
                "output_aspect": cam.parm("resx").eval() / cam.parm("resy").eval(),
            }
        data = {
            "version": 1,
            "render_id": job["job_id"],
            "session_id": ctx.ledger.session_id,
            "scene_id": ctx.ledger.scene_id,
            "path": path,
            "frames": frames,
            "expected": expected,
            "anchor_frame": h.frame(),
            "fps": h.fps(),
            "camera_tokens": camera_tokens,
            "recipes": recipes,
            "resolution": resolution,
            "rows": [None] * len(frames),
            "paused": False,
        }
        folder = ctx.ledger.root / job["job_id"]
        atomic_json(folder / "render-sequence.json", data)
        states[job["job_id"]] = True
    return {**summary(folder, data), "state_receipt": state.receipt}


def step(ctx, job, render_id, resume=False):
    """Render only the next missing/corrupt frame, then return control to Houdini."""
    from ..diagnostics import audit

    folder, data = get(ctx, render_id)
    if data["paused"] and not resume:
        raise CompanionError("RENDER_PAUSED", "Pass resume=true to continue this sequence")
    missing = [i for i, row in enumerate(data["rows"]) if not completed(folder, row)]
    if not missing:
        return summary(folder, data)
    index = missing[0]
    node = require_node(ctx.hou, data["path"])
    started = time.perf_counter()
    try:
        with StateGuard(ctx.hou) as state:
            ctx.hou.setFrame(data["anchor_frame"])
            node.geometry()
            check_expected(ctx.hou, node, data["expected"])
            for camera, expected in data["camera_tokens"].items():
                check_expected(ctx.hou, require_node(ctx.hou, camera), expected)
            ctx.ledger.checkpoint(job["job_id"])
            ctx.ledger.phase(job["job_id"], f"frame_{index + 1}_of_{len(data['frames'])}")
            t = time.perf_counter()
            geo = node.geometryAtFrame(data["frames"][index])
            if node.errors():
                raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
            dest = folder / f"frame-{index:04d}.bgeo.sc"
            geo.saveToFile(str(dest))
            cook_ms = (time.perf_counter() - t) * 1000
            checks = audit(ctx.hou, dest, lambda: ctx.ledger.checkpoint(job["job_id"]))
            work = folder / f"work-{index:04d}"
            work.mkdir(exist_ok=True)
            render = render_snapshot(
                ctx.hou,
                dest,
                work,
                list(data["recipes"]),
                data["resolution"],
                lambda: ctx.ledger.checkpoint(job["job_id"]),
                cameras=data["recipes"],
            )
            images = []
            for image in render["images"]:
                target = folder / f"frame-{index:04d}-{image['name']}"
                (work / image["name"]).replace(target)
                images.append({**image, "name": target.name})
            work.rmdir()
            row = {
                "frame": data["frames"][index],
                "job_id": job["job_id"],
                "geometry_artifact": artifact(dest, "geometry"),
                "geometry": checks,
                "images": images,
                "cook_ms": cook_ms,
                "render_ms": render["render_ms"],
                "total_ms": (time.perf_counter() - started) * 1000,
            }
            node.geometry()
        row["state_receipt"] = state.receipt
        data["rows"][index] = row
        data["paused"] = False
        data.pop("last_error", None)
        atomic_json(folder / "render-sequence.json", data)
    except Exception as exc:
        data["last_error"] = {"frame": data["frames"][index], "message": str(exc)}
        atomic_json(folder / "render-sequence.json", data)
        raise
    return {
        **summary(folder, data),
        "rendered_frame": row["frame"],
        "state_receipt": state.receipt,
        "timings": {k: row[k] for k in ("cook_ms", "render_ms", "total_ms")},
    }


def status(ctx, job, render_id):
    return summary(*get(ctx, render_id))


def pause(ctx, job, render_id):
    folder, data = get(ctx, render_id)
    data["paused"] = True
    atomic_json(folder / "render-sequence.json", data)
    return summary(folder, data)


def release(ctx, job, render_id):
    get(ctx, render_id)
    del ctx.state["render_sequences"][render_id]
    return {"released": render_id, "artifacts": "eligible for normal retention cleanup"}


def plugin():
    key = object_schema({"render_id": PATH}, ["render_id"])
    return PluginSpec(
        "render_sequence",
        "0.1.0",
        (
            OperationSpec(
                "render.start",
                "artifacts",
                object_schema(
                    {
                        "path": PATH,
                        "frames": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 1,
                            "maxItems": 300,
                        },
                        "cameras": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 3},
                        "resolution": {"type": "integer", "minimum": 128, "maximum": 1280},
                    },
                    ["path", "frames", "cameras"],
                ),
                start,
                start.__doc__,
            ),
            OperationSpec(
                "render.step",
                "artifacts",
                object_schema({"render_id": PATH, "resume": {"type": "boolean"}}, ["render_id"]),
                step,
                step.__doc__,
            ),
            OperationSpec("render.status", "read", key, status),
            OperationSpec("render.cancel", "artifacts", key, pause),
            OperationSpec("render.release", "artifacts", key, release),
        ),
        requires=("review",),
    )
