from __future__ import annotations

import hashlib
import time
from pathlib import Path

from ..core import CompanionError, atomic_json
from ..observation import (
    INCLUDE,
    check_expected,
    fingerprint,
    geometry_summary,
    require_node,
)
from ..rendering import artifact, render_snapshot
from . import BasePlugin, make_plugin


class Handlers(BasePlugin):
    def op_snapshot(self, job, path, views=None, resolution=640, expected=None, focus=None):
        hou = self.hou
        node = require_node(hou, path)
        if not isinstance(node, hou.SopNode):
            raise CompanionError("SOP_REQUIRED", "Choose a SOP output for feedback")
        before = check_expected(hou, node, expected) if expected else fingerprint(hou, node)
        self.ledger.phase(job["job_id"], "cooking")
        started = time.perf_counter()
        frozen = node.geometry().freeze()
        cook_ms = round((time.perf_counter() - started) * 1000, 2)
        if node.errors():
            raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
        if fingerprint(hou, node)["token"] != before["token"]:
            raise CompanionError("STALE_INPUT", "Inputs changed while cooking")
        directory = self.ledger.root / job["job_id"]
        directory.mkdir(parents=True, exist_ok=True)
        geometry_path = directory / "geometry.bgeo.sc"
        frozen.saveToFile(str(geometry_path))
        self.ledger.phase(job["job_id"], "diagnostics")
        result = {
            "observation": before,
            "geometry": geometry_summary(frozen),
            "geometry_artifact": artifact(geometry_path, "geometry"),
            "cook_ms": cook_ms,
            "errors": list(node.errors()),
            "warnings": list(node.warnings()),
        }
        self.ledger.checkpoint(job["job_id"])
        self.ledger.phase(job["job_id"], "rendering")
        result.update(
            render_snapshot(
                hou,
                geometry_path,
                directory,
                views or ["front", "right", "persp"],
                resolution,
                lambda: self.ledger.checkpoint(job["job_id"]),
                focus=focus,
            )
        )
        result["stale"] = fingerprint(hou, node)["token"] != before["token"]
        checks = result["geometry"]["checks"]
        result["verification"] = (
            "issues_found"
            if checks["nonfinite_point_count"]
            or checks["zero_area_count"]
            or any(i["suspect_blank_or_dark"] for i in result["images"])
            else "passed_basic_checks"
            if checks["complete"]
            else "passed_sampled_checks"
        )
        atomic_json(directory / "feedback.json", result)
        return result

    def op_preview(self, job, path, expected, values, views=None, resolution=640):
        """Preview a leaf SOP with frozen direct inputs and immutable quoted includes.

        References beyond direct inputs and parameter animation are rejected. This
        intentionally excludes arbitrary subnet/simulation/asset cloning.
        """
        hou = self.hou
        node = require_node(hou, path)
        before = check_expected(hou, node, expected)
        if len(self.previews) >= 8:
            raise CompanionError("PREVIEW_LIMIT", "Discard or apply an existing preview first")
        builtin_wrangle = (
            node.type().name().split("::")[0] == "attribwrangle" and node.matchesCurrentDefinition()
        )
        if not isinstance(node, hou.SopNode) or (
            not builtin_wrangle and (node.children() or node.type().definition() is not None)
        ):
            raise CompanionError("UNSUPPORTED_PREVIEW", "Preview supports built-in leaf SOPs")
        if any(p.keyframes() for p in node.parms()):
            raise CompanionError(
                "UNSUPPORTED_PREVIEW", "Animated or expression parameters need explicit staging"
            )
        inputs = {n for n in node.inputs() if n is not None}
        references = {
            ref
            for ref in node.references(include_children=False)
            if ref is not None and ref != node and not ref.path().startswith(node.path() + "/")
        }
        if references - inputs:
            raise CompanionError(
                "UNSUPPORTED_PREVIEW", "Node references dependencies outside its direct inputs"
            )
        if not isinstance(values, dict) or not values:
            raise CompanionError("INVALID_PREVIEW", "Supply parameter values to preview")
        if node.type().name().split("::")[0] in {
            "python",
            "file",
            "dopimport",
            "dopimportfield",
            "dopimportrecords",
        }:
            raise CompanionError(
                "UNSUPPORTED_PREVIEW", "This SOP can access unstaged external state"
            )
        directory = self.ledger.root / job["job_id"]
        directory.mkdir(parents=True, exist_ok=True)
        staged_sources = {}
        baseline = self.op_snapshot(job, path, views, resolution, expected)
        for entry in [baseline["geometry_artifact"], *baseline["images"]]:
            old_name = entry["name"]
            entry["name"] = "before_" + old_name
            (directory / old_name).replace(directory / entry["name"])

        def stage_text(text, relative=None):
            def replacement(match):
                source = Path(hou.expandString(match.group(1)))
                if not source.is_absolute():
                    if relative is None:
                        raise CompanionError(
                            "UNRESOLVED_INCLUDE",
                            "Relative includes require an explicit source root",
                        )
                    source = relative / source
                source = source.resolve()
                if str(source) not in staged_sources:
                    if (
                        len(staged_sources) >= 64
                        or not source.is_file()
                        or source.stat().st_size > 1024 * 1024
                    ):
                        raise CompanionError(
                            "UNSUPPORTED_INCLUDE", f"Cannot stage include: {source}"
                        )
                    target = directory / (
                        hashlib.sha256(str(source).encode()).hexdigest()[:12] + "_" + source.name
                    )
                    staged_sources[str(source)] = str(target)
                    target.write_text(
                        stage_text(source.read_text(encoding="utf-8"), source.parent),
                        encoding="utf-8",
                    )
                return '#include "' + Path(staged_sources[str(source)]).as_posix() + '"'

            return INCLUDE.sub(replacement, text)

        with hou.undos.disabler():
            container = hou.node("/obj").createNode("geo", "__companion_preview")
            container.setDisplayFlag(False)
            container.setUserData("houdini_companion_owner", job["job_id"])
            try:
                clone = hou.copyNodesTo((node,), container)[0]
                for index, upstream in enumerate(node.inputs()):
                    if upstream is None:
                        continue
                    frozen_path = directory / f"input_{index}.bgeo.sc"
                    upstream.geometry().freeze().saveToFile(str(frozen_path))
                    input_file = container.createNode("file", f"input_{index}")
                    input_file.parm("file").set(str(frozen_path))
                    clone.setInput(index, input_file)
                for name, value in values.items():
                    parm = clone.parmTuple(name) if isinstance(value, list) else clone.parm(name)
                    if parm is None:
                        raise CompanionError("PARM_NOT_FOUND", f"Unknown parameter: {name}")
                    parm.set(value)
                for parm in clone.parms():
                    if parm.parmTemplate().type() == hou.parmTemplateType.String:
                        text = parm.evalAsString()
                        if INCLUDE.search(text):
                            parm.set(stage_text(text))
                # Resolve the copied wrangle's generated internal state before
                # recording the observation. The live source remains guarded.
                clone.cook(force=True)
                result = self.op_snapshot(job, clone.path(), views, resolution)
            finally:
                container.destroy()
        check_expected(hou, node, expected)
        self.previews[job["job_id"]] = {
            "path": path,
            "expected": expected,
            "values": values,
            "scene_id": self.ledger.scene_id,
        }
        result.update(
            preview_id=job["job_id"],
            before_feedback=baseline,
            source_observation=before,
            staged_sources=staged_sources,
            apply_scope="parameter values; original source files unchanged",
        )
        atomic_json(directory / "feedback.json", result)
        return result

    def op_apply_preview(self, job, preview_id, feedback=True):
        preview = self.previews.get(preview_id)
        if not preview or preview["scene_id"] != self.ledger.scene_id:
            raise CompanionError("PREVIEW_EXPIRED", "Preview is unavailable in this scene")
        result = self.context.call(
            "batch",
            job,
            actions=[{"op": "set", "path": preview["path"], "values": preview["values"]}],
            expected={preview["path"]: preview["expected"]},
            output=preview["path"],
            feedback=feedback,
        )
        del self.previews[preview_id]
        return result

    def op_discard_preview(self, job, preview_id):
        self.previews.pop(preview_id, None)
        return {"discarded": preview_id}


def plugin():
    return make_plugin(
        "review",
        Handlers,
        ("snapshot", "preview", "apply_preview", "discard_preview"),
        requires=("scene",),
    )
