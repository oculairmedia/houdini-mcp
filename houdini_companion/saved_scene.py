"""Saved-scene signatures and a fresh-process verifier with no artist-session reload."""

import hashlib
from pathlib import Path

from .diagnostics import semantic_hash
from .state_guard import camera_state


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def geometry_signature(geo):
    topology = "\n".join(
        f"{p.type().name()}:" + ",".join(str(v.point().number()) for v in p.vertices())
        for p in geo.prims()
    ).encode()
    return {
        "points": len(geo.points()),
        "primitives": len(geo.prims()),
        "sha256": semantic_hash(geo, topology),
    }


def camera_signature(node):
    return {"transform": list(node.worldTransform().asTuple()), "parms": camera_state(node)}


def dependency_failures(manifest):
    failures = []
    for item in manifest["dependencies"]:
        path = Path(item["path"])
        if not path.is_file():
            failures.append({"code": "MISSING_DEPENDENCY", "path": str(path)})
        elif sha256(path) != item["sha256"]:
            failures.append({"code": "CHANGED_DEPENDENCY", "path": str(path)})
    return failures


def verify(hou, manifest):
    failures = dependency_failures(manifest)
    if sha256(manifest["hip"]) != manifest["hip_sha256"]:
        failures.append({"code": "HIP_CHANGED"})
    if failures:
        return {"accepted": False, "reasons": failures, "opened": False}
    hou.hipFile.load(manifest["hip"], suppress_save_prompt=True, ignore_load_warnings=False)
    for sample in manifest["geometry"]:
        node = hou.node(sample["path"])
        actual = geometry_signature(node.geometryAtFrame(sample["frame"])) if node else None
        if actual != sample["signature"]:
            failures.append(
                {"code": "GEOMETRY_MISMATCH", "path": sample["path"], "frame": sample["frame"]}
            )
    hou.setFrame(manifest["frame"])
    for path, expected in manifest["cameras"].items():
        cam = hou.node(path)
        if cam is None or camera_signature(cam) != expected:
            failures.append({"code": "CAMERA_MISMATCH", "path": path})
    if hou.fps() != manifest["fps"]:
        failures.append({"code": "FPS_MISMATCH"})
    return {
        "accepted": not failures,
        "reasons": failures,
        "opened": True,
        "geometry_samples": len(manifest["geometry"]),
        "cameras": len(manifest["cameras"]),
        "scope": manifest["scope"],
        "houdini": hou.applicationVersionString(),
    }
