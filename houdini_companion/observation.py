"""Houdini observations. Called exclusively from the UI dispatcher."""

from __future__ import annotations

import hashlib
import math
import re
import time
from itertools import islice
from pathlib import Path

from .core import CompanionError, digest

INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"\n]+)"', re.MULTILINE)


def require_node(hou, path):
    node = hou.node(path)
    if node is None:
        raise CompanionError("NODE_NOT_FOUND", f"Node no longer exists: {path}")
    return node


def file_record(path):
    path = Path(path).resolve()
    if not path.is_file():
        return {"path": str(path), "missing": True}
    stat = path.stat()
    result = {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if stat.st_size <= 16 * 1024 * 1024:
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        result["fingerprint_kind"] = "size_and_mtime"
    return result


def source_files(hou, text, directory=None, found=None):
    found = {} if found is None else found
    for value in INCLUDE.findall(text):
        path = Path(hou.expandString(value))
        if not path.is_absolute():
            if directory is None:
                raise CompanionError(
                    "UNRESOLVED_INCLUDE", f"Relative include needs explicit resolution: {value}"
                )
            path = directory / path
        path = path.resolve()
        if str(path) in found:
            continue
        if len(found) >= 64:
            raise CompanionError("DEPENDENCY_LIMIT", "More than 64 source includes")
        found[str(path)] = file_record(path)
        if path.is_file() and path.stat().st_size <= 1024 * 1024:
            source_files(
                hou, path.read_text(encoding="utf-8", errors="replace"), path.parent, found
            )
    return found


def fingerprint(hou, node, limit=256):
    """Conservative identity of target, input/reference graph, ancestors and sources.

    This does not claim to discover arbitrary dependencies hidden inside Python,
    plug-ins, network services or external processes.
    """
    pending, seen, nodes, files = [node], set(), [], {}
    while pending:
        current = pending.pop()
        sid = current.sessionId()
        if sid in seen:
            continue
        seen.add(sid)
        if len(seen) > limit:
            raise CompanionError("DEPENDENCY_LIMIT", f"Dependency graph exceeds {limit} nodes")
        parameters = []
        for parm in current.parms():
            try:
                raw = parm.rawValue()
                evaluated = parm.eval()
                if isinstance(evaluated, hou.Ramp):
                    evaluated = {
                        "basis": [str(b) for b in evaluated.basis()],
                        "keys": list(evaluated.keys()),
                        "values": list(evaluated.values()),
                    }
                if not isinstance(evaluated, (str, int, float)):
                    evaluated = str(evaluated)
                if isinstance(evaluated, float) and not math.isfinite(evaluated):
                    evaluated = str(evaluated)
                parameters.append((parm.name(), raw, evaluated))
                if isinstance(evaluated, str):
                    files.update(source_files(hou, evaluated))
                    if len(evaluated) < 2048 and "\n" not in evaluated:
                        candidate = Path(evaluated)
                        if candidate.is_absolute() and candidate.is_file():
                            files[str(candidate.resolve())] = file_record(candidate)
            except CompanionError:
                raise
            except (hou.Error, OSError, ValueError):
                parameters.append((parm.name(), "unavailable"))
        inputs = [
            (c.inputIndex(), c.inputNode().sessionId() if c.inputNode() else None, c.outputIndex())
            for c in current.inputConnections()
        ]
        record = {
            "path": current.path(),
            "id": sid,
            "type": current.type().name(),
            "parms": parameters,
            "inputs": inputs,
            "children": [
                (n.sessionId(), n.name(), n.type().name()) for n in current.children()[:256]
            ],
            "child_count": len(current.children()),
        }
        if hasattr(current, "isBypassed"):
            record["bypass"] = current.isBypassed()
        nodes.append(record)
        pending.extend(n for n in current.inputs() if n is not None)
        if hasattr(current, "references"):
            locked_definition = (
                current.type().definition() is not None and current.matchesCurrentDefinition()
            )
            pending.extend(
                n
                for n in current.references(include_children=False)
                if n is not None
                and not (locked_definition and n.path().startswith(current.path() + "/"))
            )
        parent = current.parent()
        if parent and parent.path() not in {"/", "/obj", "/out"}:
            pending.append(parent)
    state = {
        "frame": hou.frame(),
        "take": hou.takes.currentTake().name(),
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "files": sorted(files.values(), key=lambda f: f["path"]),
    }
    return {
        "token": digest(state),
        "node_id": node.sessionId(),
        "path": node.path(),
        "frame": state["frame"],
        "dependencies": len(nodes),
        "dependency_paths": [n["path"] for n in nodes],
        "sources": state["files"],
        "source_state": "Disk fingerprints; existing compiled VEX cache identity is not available",
        "scope": "parameters, inputs, declared references, ancestors and quoted includes",
    }


def check_expected(hou, node, expected):
    actual = fingerprint(hou, node)
    if not isinstance(expected, str) or expected != actual["token"]:
        raise CompanionError(
            "STALE_INPUT", "Inspect again: target or relevant inputs changed", actual=actual
        )
    return actual


def geometry_summary(geo, budget=50000):
    point_count = geo.intrinsicValue("pointcount")
    prim_count = geo.intrinsicValue("primitivecount")
    invalid_points = []
    for p in islice(geo.iterPoints(), budget):
        if not all(math.isfinite(v) for v in p.position()):
            invalid_points.append(p.number())
    zero_area = []
    polygons_checked = 0
    for prim in islice(geo.iterPrims(), budget):
        if prim.type().name() == "Polygon" and prim.isClosed():
            polygons_checked += 1
            if prim.intrinsicValue("measuredarea") <= 1e-12:
                zero_area.append(prim.number())
    bbox = geo.boundingBox()
    bounds = [list(bbox.minvec()), list(bbox.maxvec())] if point_count else None
    if bounds and not all(math.isfinite(v) for side in bounds for v in side):
        bounds = None
    return {
        "points": point_count,
        "primitives": prim_count,
        "bounds": bounds,
        "attributes": {
            "point": [a.name() for a in geo.pointAttribs()],
            "primitive": [a.name() for a in geo.primAttribs()],
            "detail": [a.name() for a in geo.globalAttribs()],
        },
        "checks": {
            "points_checked": min(point_count, budget),
            "polygons_checked": polygons_checked,
            "complete": point_count <= budget and prim_count <= budget,
            "nonfinite_point_count": len(invalid_points),
            "nonfinite_points": invalid_points[:20],
            "zero_area_count": len(zero_area),
            "zero_area_primitives": zero_area[:20],
            "topology_policy": "surface cards allowed; no blanket watertightness requirement",
        },
    }


def inspect_node(hou, path, geometry=False):
    node = require_node(hou, path)
    started = time.perf_counter()
    observation = fingerprint(hou, node)
    result = {
        "path": node.path(),
        "type": node.type().name(),
        "observation": observation,
        "inputs": [n.path() if n else None for n in node.inputs()],
        "children": [{"path": n.path(), "type": n.type().name()} for n in node.children()[:100]],
        "child_count": len(node.children()),
        "errors": list(node.errors()),
        "warnings": list(node.warnings()),
        "parameters": [
            {
                "name": p.name(),
                "type": p.parmTemplate().type().name(),
                "raw": p.rawValue()[:1000],
                "animated_or_expression": bool(p.keyframes()),
            }
            for p in node.parms()[:100]
        ],
        "parameter_count": len(node.parms()),
    }
    if geometry:
        if not isinstance(node, hou.SopNode):
            raise CompanionError("SOP_REQUIRED", "Geometry inspection requires a SOP node")
        frozen = node.geometry().freeze()
        result["geometry"] = geometry_summary(frozen)
        result["errors"] = list(node.errors())
        if fingerprint(hou, node)["token"] != observation["token"]:
            raise CompanionError("STALE_INPUT", "Inputs changed during observation")
    result["inspection_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result
