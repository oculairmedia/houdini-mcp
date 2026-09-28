"""Owned declarative SOP builds: stage, validate, explicitly promote or discard."""

import re

from ..core import atomic_json
from ..errors import CompanionError
from ..observation import check_expected, fingerprint, require_node
from ..registry import OperationSpec, PluginSpec
from ..state_guard import StateGuard
from .introspection import PATH, object_schema

TYPES = [
    "box",
    "sphere",
    "attribwrangle",
    "normal",
    "null",
    "xform",
    "merge",
    "reverse",
    "subdivide",
]
PROFILES = {"type": "string", "enum": ["surface", "open_cards", "closed_solids", "walkway"]}
VECTOR = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
PROBES = {
    "type": "array",
    "maxItems": 128,
    "items": object_schema(
        {
            "origin": VECTOR,
            "direction": VECTOR,
            "distance": {"type": "number", "minimum": 0.001, "maximum": 10000},
        },
        ["origin", "direction", "distance"],
    ),
}


def validate(ctx, job, path, profile="surface", frame=None, probes=None):
    """Validate declared polygon semantics and explicit local-space clearance probes."""
    from ..geometry_profiles import from_hou

    node = require_node(ctx.hou, path)
    with StateGuard(ctx.hou) as state:
        geo = node.geometryAtFrame(frame if frame is not None else ctx.hou.frame())
        if node.errors():
            raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
        result = from_hou(geo, profile, probes or [])
    return {**result, "state_receipt": state.receipt}


def stage(ctx, job, nodes, output, name="candidate", profile="surface"):
    """Stage a hidden SOP graph; any failed cook/check removes its owned container."""
    if profile == "walkway":
        raise CompanionError(
            "PROFILE", "Use geometry.validate with explicit probes for walking clearance"
        )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        raise CompanionError("NAME", "Use a simple object name")
    identifiers = [n["id"] for n in nodes]
    if len(set(identifiers)) != len(nodes) or output not in identifiers:
        raise CompanionError("BUILD_GRAPH", "Unique node ids and a declared output are required")
    for spec in nodes:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", spec["id"]):
            raise CompanionError("BUILD_GRAPH", "Node ids must be simple names")
        if any(i not in identifiers for i in spec.get("inputs", [])):
            raise CompanionError("BUILD_GRAPH", "Inputs must refer to this candidate's nodes")
    states = ctx.state.setdefault("builds", {})
    if len(states) >= 16:
        raise CompanionError("BUILD_LIMIT", "Promote or discard a pending candidate first")
    h, root = ctx.hou, None
    with StateGuard(h) as state:
        try:
            root = h.node("/obj").createNode("geo", "__build_" + job["job_id"])
            root.setUserData("companion_build", job["job_id"])
            root.setDisplayFlag(False)
            created = {}
            for spec in nodes:
                ctx.ledger.checkpoint(job["job_id"])
                node = root.createNode(spec["type"], spec["id"])
                created[spec["id"]] = node
                for key, value in spec.get("parms", {}).items():
                    parm = node.parmTuple(key) if isinstance(value, list) else node.parm(key)
                    if parm is None:
                        raise CompanionError("PARM_NOT_FOUND", key)
                    parm.set(value)
            for spec in nodes:
                for index, source in enumerate(spec.get("inputs", [])):
                    created[spec["id"]].setInput(index, created[source])
            for node in created.values():
                node.cook(force=True)
                if node.errors():
                    raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
            out = created[output]
            out.setDisplayFlag(True)
            out.setRenderFlag(True)
            checked = validate(ctx, job, out.path(), profile)
            if not checked["accepted"]:
                raise CompanionError(
                    "BUILD_REJECTED", "Candidate geometry rejected", validation=checked
                )
            root.layoutChildren()
            observation = fingerprint(h, out)
            record = {
                "build_id": job["job_id"],
                "scene_id": ctx.ledger.scene_id,
                "root": root.path(),
                "output": out.path(),
                "name": name,
                "expected": observation["token"],
                "validation": checked,
            }
            atomic_json(ctx.ledger.root / job["job_id"] / "build.json", record)
            states[job["job_id"]] = record
        except Exception as exc:
            cleanup = "not_created"
            if root is not None:
                try:
                    root.destroy()
                    cleanup = "removed"
                except Exception as cleanup_error:
                    raise CompanionError(
                        "BUILD_CLEANUP_FAILED",
                        str(exc),
                        cleanup_error=str(cleanup_error),
                        root=root.path(),
                    ) from exc
            raise CompanionError("BUILD_FAILED", str(exc), cleanup=cleanup) from exc
    return {**record, "hidden": True, "state_receipt": state.receipt}


def record(ctx, build_id):
    value = ctx.state.get("builds", {}).get(build_id)
    if not value or value["scene_id"] != ctx.ledger.scene_id:
        raise CompanionError("BUILD_NOT_FOUND", "No current candidate")
    root = require_node(ctx.hou, value["root"])
    if root.userData("companion_build") != build_id:
        raise CompanionError("BUILD_OWNER", "Candidate ownership changed")
    return value, root


def promote(ctx, job, build_id):
    """Expose the exact validated candidate; never overwrite an existing object."""
    value, root = record(ctx, build_id)
    check_expected(ctx.hou, require_node(ctx.hou, value["output"]), value["expected"])
    if ctx.hou.node("/obj/" + value["name"]):
        raise CompanionError("TARGET_EXISTS", "Choose an unused object name")
    old_name, old_display = root.name(), root.isDisplayFlagSet()
    try:
        root.setName(value["name"], unique_name=False)
        root.setDisplayFlag(True)
    except Exception as exc:
        failures = []
        for action in (
            lambda: root.setName(old_name, unique_name=False),
            lambda: root.setDisplayFlag(old_display),
        ):
            try:
                action()
            except Exception as rollback:
                failures.append(str(rollback))
        raise CompanionError(
            "PROMOTION_FAILED",
            str(exc),
            recovery="partial" if failures else "restored",
            failures=failures,
            current_root=root.path(),
        ) from exc
    del ctx.state["builds"][build_id]
    return {
        "promoted": root.path(),
        "output": root.path() + "/" + value["output"].rsplit("/", 1)[-1],
        "build_id": build_id,
        "validation": value["validation"],
    }


def discard(ctx, job, build_id):
    value, root = record(ctx, build_id)
    root.destroy()
    del ctx.state["builds"][build_id]
    return {"discarded": value["root"], "build_id": build_id}


def plugin():
    node = object_schema(
        {
            "id": PATH,
            "type": {"type": "string", "enum": TYPES},
            "parms": {"type": "object"},
            "inputs": {"type": "array", "items": PATH, "maxItems": 16},
        },
        ["id", "type"],
    )
    return PluginSpec(
        "build",
        "0.1.0",
        (
            OperationSpec(
                "build.stage",
                "preview",
                object_schema(
                    {
                        "nodes": {"type": "array", "items": node, "minItems": 1, "maxItems": 64},
                        "output": PATH,
                        "name": PATH,
                        "profile": PROFILES,
                    },
                    ["nodes", "output"],
                ),
                stage,
                stage.__doc__,
            ),
            OperationSpec(
                "build.promote",
                "scene",
                object_schema({"build_id": PATH}, ["build_id"]),
                promote,
                promote.__doc__,
            ),
            OperationSpec(
                "build.discard", "scene", object_schema({"build_id": PATH}, ["build_id"]), discard
            ),
            OperationSpec(
                "geometry.validate",
                "read",
                object_schema(
                    {
                        "path": PATH,
                        "profile": PROFILES,
                        "frame": {"type": "number"},
                        "probes": PROBES,
                    },
                    ["path"],
                ),
                validate,
                validate.__doc__,
            ),
        ),
        requires=("query",),
    )
