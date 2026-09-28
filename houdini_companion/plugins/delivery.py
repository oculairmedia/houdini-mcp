"""Explicit show/save and isolated saved-HIP acceptance with bounded worker lifetime."""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from ..core import atomic_json
from ..errors import CompanionError
from ..observation import fingerprint, require_node
from ..registry import OperationSpec, PluginSpec
from ..saved_scene import camera_signature, geometry_signature, sha256
from ..state_guard import StateGuard, time_state
from .introspection import PATH, object_schema


def show(ctx, job, path, camera, frame=None):
    """Intentionally show an object/camera; return explicit before/after UI state."""
    h = ctx.hou
    root, cam = require_node(h, path), require_node(h, camera)
    if not isinstance(root, h.ObjNode) or cam.type().name() != "cam":
        raise CompanionError("SHOW_TARGET", "An object and camera are required")
    if not h.isUIAvailable():
        raise CompanionError("UI_REQUIRED", "Showing requires interactive Houdini")
    viewer = h.ui.paneTabOfType(h.paneTabType.SceneViewer)
    if viewer is None:
        raise CompanionError("VIEWPORT_REQUIRED", "Open a Scene View")
    vp = viewer.curViewport()
    before = {
        "time": time_state(h),
        "display": root.isDisplayFlagSet(),
        "camera": vp.camera().path() if vp.camera() else None,
    }
    viewer.setIsCurrentTab()
    root.setDisplayFlag(True)
    vp.lockCameraToView(False)
    vp.setCamera(cam)
    if frame is not None:
        h.setFrame(frame)
    return {
        "intentional_changes": ["object_display", "viewport_camera", "frame"],
        "before": before,
        "after": {"time": time_state(h), "display": root.isDisplayFlagSet(), "camera": camera},
    }


def save(ctx, job, destination, paths, cameras=None, frames=None, activate=False):
    """Save a new HIP and declared-output verification manifest; never overwrite."""
    h, destination = ctx.hou, Path(destination).expanduser().resolve()
    if destination.exists():
        raise CompanionError("TARGET_EXISTS", "Save requires a new destination")
    if destination.suffix.lower() not in {".hip", ".hiplc", ".hipnc"}:
        raise CompanionError("HIP_PATH", "A HIP file extension is required")
    original = h.hipFile.path()
    if len(ctx.state.setdefault("deliverables", {})) >= 16:
        raise CompanionError("SAVE_LIMIT", "Release a saved receipt before creating another")
    frames = frames or [h.frame()]
    deps, geometry = {}, []
    camera_nodes = [require_node(h, p) for p in (cameras or [])]
    with StateGuard(h, camera_nodes) as state:
        for path in paths:
            node = require_node(h, path)
            node.geometry()
            for item in fingerprint(h, node)["sources"]:
                if item.get("missing"):
                    raise CompanionError("MISSING_DEPENDENCY", item["path"])
                deps[item["path"]] = {"path": item["path"], "sha256": sha256(item["path"])}
            for frame in frames:
                geo = node.geometryAtFrame(frame)
                if node.errors():
                    raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
                geometry.append(
                    {"path": path, "frame": frame, "signature": geometry_signature(geo)}
                )
            node.geometry()
        manifest = {
            "version": 1,
            "save_id": job["job_id"],
            "hip": str(destination),
            "frame": h.frame(),
            "fps": h.fps(),
            "geometry": geometry,
            "cameras": {n.path(): camera_signature(n) for n in camera_nodes},
            "dependencies": list(deps.values()),
            "scope": "Declared SOP outputs/cameras and discoverable source dependencies; not whole-scene portability certification",
        }
        try:
            h.hipFile.save(file_name=str(destination))
            manifest["hip"] = h.hipFile.path()
            manifest["hip_sha256"] = sha256(manifest["hip"])
        finally:
            if not activate:
                h.hipFile.setName(original)
    folder = ctx.ledger.root / job["job_id"]
    atomic_json(folder / "saved-scene.json", manifest)
    ctx.state.setdefault("deliverables", {})[job["job_id"]] = str(folder / "saved-scene.json")
    return {
        "save_id": job["job_id"],
        "hip": manifest["hip"],
        "active_hip": h.hipFile.path(),
        "manifest": str(folder / "saved-scene.json"),
        "state_receipt": state.receipt,
        "verified_reopen": False,
        "next_operation": "save.verify",
    }


def verify_start(ctx, job, save_id, timeout=120):
    """Start a disposable hython verifier; returns immediately without reloading the artist scene."""
    manifest = ctx.state.get("deliverables", {}).get(save_id)
    if not manifest:
        raise CompanionError("SAVE_NOT_FOUND", "No saved receipt in this runtime")
    states = ctx.state.setdefault("save_verifiers", {})
    if len(states) >= 16:
        raise CompanionError(
            "VERIFY_LIMIT", "Release completed saved receipts before starting more verifiers"
        )
    if sum(r["process"].poll() is None for r in states.values()) >= 2:
        raise CompanionError("VERIFY_BUSY", "At most two verifier processes may run")
    folder = ctx.ledger.root / job["job_id"]
    folder.mkdir(parents=True, exist_ok=True)
    executable = (
        Path(ctx.hou.getenv("HFS")) / "bin" / ("hython.exe" if os.name == "nt" else "hython")
    )
    worker = Path(__file__).resolve().parents[1] / "saved_verify_worker.py"
    env = {
        **os.environ,
        "HOUDINI_COMPANION_AUTOSTART": "0",
        "HOUDINI_USER_PREF_DIR": str(folder / "prefs"),
        "HOUDINI_NO_ENV_FILE": "1",
    }
    with (folder / "worker.log").open("wb") as log:
        process = subprocess.Popen(
            [str(executable), str(worker), manifest, str(folder / "verification.json")],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    timer = threading.Timer(timeout, lambda: process.kill() if process.poll() is None else None)
    timer.daemon = True
    timer.start()
    states[job["job_id"]] = {
        "process": process,
        "timer": timer,
        "deadline": time.monotonic() + timeout,
        "folder": folder,
        "save_id": save_id,
    }
    return {
        "verification_id": job["job_id"],
        "state": "running",
        "pid": process.pid,
        "next_operation": "save.verify_status",
    }


def verify_status(ctx, job, verification_id):
    record = ctx.state.get("save_verifiers", {}).get(verification_id)
    if not record:
        raise CompanionError("VERIFY_NOT_FOUND", verification_id)
    code = record["process"].poll()
    if code is None:
        return {"verification_id": verification_id, "state": "running"}
    record["timer"].cancel()
    report = record["folder"] / "verification.json"
    if code != 0 or not report.exists():
        return {
            "verification_id": verification_id,
            "state": "failed",
            "accepted": False,
            "reason": "TIMEOUT" if time.monotonic() >= record["deadline"] else "WORKER_FAILED",
            "exit_code": code,
        }
    return {
        "verification_id": verification_id,
        "state": "complete",
        "exit_code": code,
        **json.loads(report.read_text(encoding="utf-8")),
        "report": str(report),
    }


def release(ctx, job, save_id):
    """Unpin completed saved-scene receipts; never deletes the destination HIP."""
    if save_id not in ctx.state.get("deliverables", {}):
        raise CompanionError("SAVE_NOT_FOUND", save_id)
    workers = ctx.state.get("save_verifiers", {})
    matches = [key for key, value in workers.items() if value["save_id"] == save_id]
    if any(workers[key]["process"].poll() is None for key in matches):
        raise CompanionError("VERIFY_BUSY", "Wait for all associated verifiers before release")
    for key in matches:
        workers[key]["timer"].cancel()
        del workers[key]
    del ctx.state["deliverables"][save_id]
    return {"released": save_id, "hip_deleted": False}


def plugin():
    return PluginSpec(
        "delivery",
        "0.1.0",
        (
            OperationSpec(
                "save.release",
                "artifacts",
                object_schema({"save_id": PATH}, ["save_id"]),
                release,
                release.__doc__,
            ),
            OperationSpec(
                "scene.show",
                "scene",
                object_schema(
                    {"path": PATH, "camera": PATH, "frame": {"type": "number"}}, ["path", "camera"]
                ),
                show,
                show.__doc__,
            ),
            OperationSpec(
                "scene.save",
                "scene",
                object_schema(
                    {
                        "destination": PATH,
                        "paths": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 16},
                        "cameras": {"type": "array", "items": PATH, "maxItems": 8},
                        "frames": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 1,
                            "maxItems": 8,
                        },
                        "activate": {"type": "boolean"},
                    },
                    ["destination", "paths"],
                ),
                save,
                save.__doc__,
            ),
            OperationSpec(
                "save.verify",
                "artifacts",
                object_schema(
                    {
                        "save_id": PATH,
                        "timeout": {"type": "integer", "minimum": 10, "maximum": 300},
                    },
                    ["save_id"],
                ),
                verify_start,
                verify_start.__doc__,
            ),
            OperationSpec(
                "save.verify_status",
                "read",
                object_schema({"verification_id": PATH}, ["verification_id"]),
                verify_status,
            ),
        ),
        requires=("query",),
    )
