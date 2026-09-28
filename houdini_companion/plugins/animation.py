"""Typed numeric channel edits with explicit rollback and session restore receipts."""

import re

from ..core import atomic_json, digest
from ..errors import CompanionError
from ..observation import check_expected, fingerprint, require_node
from ..registry import OperationSpec, PluginSpec
from ..temporal import validate_tracks
from .introspection import PATH, object_schema


def control(ctx, job, path, name, label, expected, value=0.0):
    """Add a named scalar animation control; never replace existing parameters."""
    node = require_node(ctx.hou, path)
    check_expected(ctx.hou, node, expected)
    if (
        not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", name)
        or node.parm(name)
        or node.parmTuple(name)
    ):
        raise CompanionError("CONTROL_CONFLICT", "Choose a new valid parameter name")
    original = node.parmTemplateGroup()
    updated = node.parmTemplateGroup()
    updated.append(ctx.hou.FloatParmTemplate(name, label, 1, default_value=(value,)))
    snippet = node.parm("snippet") if node.type().name() == "attribwrangle" else None
    previous_code = snippet.eval() if snippet else None
    with ctx.hou.undos.group("Companion animation control"):
        try:
            node.setParmTemplateGroup(updated)
            if snippet:
                # A missing chf() may have compiled to a constant before this
                # control existed. Distinct source identity refreshes bindings.
                snippet.set(previous_code + "\n// companion control schema: " + name + "\n")
        except Exception:
            node.setParmTemplateGroup(original)
            if snippet:
                snippet.set(previous_code)
            raise
    return {
        "path": node.parm(name).path(),
        "observation": fingerprint(ctx.hou, node),
        "hip_saved": False,
        "vex_bindings_refreshed": snippet is not None,
    }


def channel_state(parm):
    keys = parm.keyframes()
    return {
        "path": parm.path(),
        "keys": [k.asCode() for k in keys],
        "raw": parm.rawValue(),
        "extrapolation": [str(parm.keyframeExtrapolation(v)) for v in (True, False)]
        if keys
        else [],
    }


def restore_channels(backups):
    errors = []
    for parm, keys, value, extrapolation in reversed(backups):
        try:
            parm.deleteAllKeyframes()
            if keys:
                parm.setKeyframes(keys)
                for before, extrapolate in zip((True, False), extrapolation, strict=True):
                    parm.setKeyframeExtrapolation(before, extrapolate)
            else:
                parm.set(value)
        except Exception as exc:
            errors.append({"path": parm.path(), "error": str(exc)})
    if errors:
        raise CompanionError(
            "ANIMATION_ROLLBACK_FAILED", "Inspect channel recovery journal", errors=errors
        )


def keyframes(ctx, job, tracks, expected):
    """Replace numeric channels with explicit linear/constant keys; no range/FPS changes."""
    validate_tracks(tracks)
    hou = ctx.hou
    backups, prepared = [], []
    for track in tracks:
        parm = hou.parm(track["path"])
        if parm is None:
            raise CompanionError("PARM_NOT_FOUND", track["path"])
        check_expected(hou, parm.node(), expected.get(parm.node().path()))
        if (
            parm.isLocked()
            or parm.getReferencedParm() != parm
            or parm.parmTemplate().type()
            not in (hou.parmTemplateType.Float, hou.parmTemplateType.Int)
        ):
            raise CompanionError(
                "UNSUPPORTED_CHANNEL",
                "Choose an unlocked, non-referencing numeric channel",
                path=parm.path(),
            )
        keys = []
        for spec in track["keys"]:
            key = hou.Keyframe()
            key.setFrame(spec["frame"])
            key.setValue(spec["value"])
            key.setExpression(track.get("interpolation", "linear") + "()", hou.exprLanguage.Hscript)
            keys.append(key)
        old_keys = parm.keyframes()
        backups.append(
            (
                parm,
                old_keys,
                parm.eval(),
                [parm.keyframeExtrapolation(v) for v in (True, False)] if old_keys else [],
            )
        )
        prepared.append((parm, keys))
    folder = ctx.ledger.root / job["job_id"]
    folder.mkdir(exist_ok=True, parents=True)
    journal = {
        "state": "prepared",
        "channels": [channel_state(p) for p, _, _, _ in backups],
        "guarantee": "handled rollback; not process-crash atomic",
    }
    atomic_json(folder / "animation-transaction.json", journal)
    with hou.undos.group("Companion keyframes " + job["job_id"][:8]):
        try:
            for parm, keys in prepared:
                ctx.ledger.checkpoint(job["job_id"])
                parm.deleteAllKeyframes()
                parm.setKeyframes(keys)
        except Exception:
            restore_channels(backups)
            journal["state"] = "rolled_back"
            atomic_json(folder / "animation-transaction.json", journal)
            raise
    after = [channel_state(p) for p, _ in prepared]
    journal.update(state="applied", after=after)
    atomic_json(folder / "animation-transaction.json", journal)
    ctx.state.setdefault("animation", {})[job["job_id"]] = {
        "backups": backups,
        "after": digest(after),
        "scene_id": ctx.ledger.scene_id,
        "fps": hou.fps(),
    }
    return {
        "animation_id": job["job_id"],
        "channels": after,
        "restore_operation": "animation.restore",
        "hip_saved": False,
        "frame": hou.frame(),
        "fps": hou.fps(),
    }


def restore(ctx, job, animation_id):
    """Restore a prior keyframe batch only if its channels are still unchanged."""
    state = ctx.state.setdefault("animation", {})
    record = state.get(animation_id)
    if not record or record["scene_id"] != ctx.ledger.scene_id:
        raise CompanionError("ANIMATION_EXPIRED", "Animation receipt is unavailable")
    backups = record["backups"]
    if (
        ctx.hou.fps() != record["fps"]
        or digest([channel_state(p) for p, _, _, _ in backups]) != record["after"]
    ):
        raise CompanionError("STALE_ANIMATION", "Channels changed after this receipt")
    with ctx.hou.undos.group("Restore companion animation"):
        restore_channels(backups)
    del state[animation_id]
    return {"restored": animation_id, "hip_saved": False}


def plugin():
    key = object_schema(
        {"frame": {"type": "number"}, "value": {"type": "number"}}, ["frame", "value"]
    )
    track = object_schema(
        {
            "path": PATH,
            "keys": {"type": "array", "items": key, "minItems": 1, "maxItems": 256},
            "interpolation": {"type": "string", "enum": ["linear", "constant"]},
        },
        ["path", "keys"],
    )
    return PluginSpec(
        "animation",
        "0.1.0",
        (
            OperationSpec(
                "animation.control",
                "scene",
                object_schema(
                    {
                        "path": PATH,
                        "name": PATH,
                        "label": PATH,
                        "expected": PATH,
                        "value": {"type": "number"},
                    },
                    ["path", "name", "label", "expected"],
                ),
                control,
                control.__doc__,
            ),
            OperationSpec(
                "animation.keyframes",
                "scene",
                object_schema(
                    {
                        "tracks": {"type": "array", "items": track, "minItems": 1, "maxItems": 64},
                        "expected": {"type": "object"},
                    },
                    ["tracks", "expected"],
                ),
                keyframes,
                keyframes.__doc__,
            ),
            OperationSpec(
                "animation.restore",
                "scene",
                object_schema({"animation_id": PATH}, ["animation_id"]),
                restore,
                restore.__doc__,
            ),
        ),
    )
