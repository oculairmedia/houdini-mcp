"""The authoritative operation implementation, executed on Houdini's UI thread."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import time
from pathlib import Path

from .core import CompanionError, atomic_json
from .observation import (
    INCLUDE,
    check_expected,
    fingerprint,
    geometry_summary,
    inspect_node,
    require_node,
)
from .rendering import artifact, render_snapshot


class BoundedOutput(io.StringIO):
    def write(self, text):
        remaining = max(0, 16000 - self.tell())
        super().write(text[:remaining])
        return len(text)


class Operations:
    def __init__(self, hou, ledger):
        self.hou = hou
        self.ledger = ledger
        self.previews = {}
        self.undo_records = {}

    def execute(self, job):
        self.ledger.checkpoint(job["job_id"])
        method = getattr(self, "op_" + job["operation"])
        result = method(job, **job["params"])
        # Validate serialization before the job can be called successful.
        json.dumps(result, allow_nan=False)
        return result

    def op_inspect(self, job, path=None, geometry=False):
        if path:
            return inspect_node(self.hou, path, geometry)
        selected = self.hou.selectedNodes()
        return {
            "selection": [inspect_node(self.hou, n.path(), geometry) for n in selected[:16]],
            "selected_count": len(selected),
            "hip_path": self.hou.hipFile.path(),
            "frame": self.hou.frame(),
        }

    def op_validate_observation(self, job, path, expected):
        actual = fingerprint(self.hou, require_node(self.hou, path))
        return {"stale": actual["token"] != expected, "observation": actual}

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

    def _validate_actions(self, actions, expected):
        if not isinstance(actions, list) or not 1 <= len(actions) <= 128:
            raise CompanionError("INVALID_BATCH", "Provide 1–128 actions")
        if not isinstance(expected, dict):
            raise CompanionError(
                "INVALID_BATCH", "expected must map existing paths to observation tokens"
            )
        aliases = set()
        schemas = {
            "create": {"op", "parent", "type", "name", "as"},
            "set": {"op", "path", "values"},
            "connect": {"op", "path", "input", "source", "output"},
            "flags": {"op", "path", "display", "render"},
            "delete": {"op", "path"},
        }
        for action in actions:
            if not isinstance(action, dict) or action.get("op") not in schemas:
                raise CompanionError("INVALID_BATCH", "Unknown action")
            if set(action) - schemas[action["op"]]:
                raise CompanionError("INVALID_BATCH", "Unknown action fields")
            if action["op"] == "create":
                if not all(
                    isinstance(action.get(k), str) and action[k] for k in ("parent", "type", "name")
                ):
                    raise CompanionError("INVALID_BATCH", "Create needs parent, type and name")
                if "/" in action["name"]:
                    raise CompanionError("INVALID_BATCH", "Node name cannot contain a slash")
            if action["op"] == "set" and not isinstance(action.get("values"), dict):
                raise CompanionError("INVALID_BATCH", "Set needs a values object")
            for key in ("path", "parent", "source"):
                path = action.get(key)
                if path is None:
                    continue
                if not isinstance(path, str):
                    raise CompanionError("INVALID_BATCH", "Paths must be strings")
                if path.startswith("$"):
                    if path[1:] not in aliases:
                        raise CompanionError("INVALID_BATCH", f"Unknown alias: {path}")
                else:
                    node = require_node(self.hou, path)
                    # Root creation is explicitly named and fails on name collisions.
                    if key == "parent" and path in {"/obj", "/out"}:
                        continue
                    if path not in expected:
                        raise CompanionError(
                            "EXPECTED_REQUIRED", f"Observation token required: {path}"
                        )
                    check_expected(self.hou, node, expected[path])
            alias = action.get("as")
            if alias:
                if not isinstance(alias, str) or alias in aliases or not alias.isidentifier():
                    raise CompanionError("INVALID_BATCH", "Aliases must be unique identifiers")
                aliases.add(alias)

    def _apply_actions(self, actions):
        hou, aliases, changed = self.hou, {}, []

        def resolve(path):
            return aliases[path[1:]] if path.startswith("$") else require_node(hou, path)

        for action in actions:
            op = action["op"]
            if op == "create":
                parent = resolve(action["parent"])
                if parent.node(action["name"]) is not None:
                    raise CompanionError("NAME_COLLISION", f"Node already exists: {action['name']}")
                node = parent.createNode(action["type"], action["name"])
                if action.get("as"):
                    aliases[action["as"]] = node
            else:
                node = resolve(action["path"])
                if op == "set":
                    # Validate parameter names before setting any on this node.
                    for name in action["values"]:
                        if node.parm(name) is None and node.parmTuple(name) is None:
                            raise CompanionError("PARM_NOT_FOUND", f"Unknown parameter: {name}")
                    for name, value in action["values"].items():
                        parm = node.parmTuple(name) if isinstance(value, list) else node.parm(name)
                        parm.set(value)
                elif op == "connect":
                    node.setInput(
                        int(action["input"]),
                        resolve(action["source"]) if action.get("source") else None,
                        int(action.get("output", 0)),
                    )
                elif op == "flags":
                    if "display" in action:
                        node.setDisplayFlag(bool(action["display"]))
                    if "render" in action:
                        node.setRenderFlag(bool(action["render"]))
                elif op == "delete":
                    changed.append({"path": node.path(), "op": op})
                    node.destroy()
                    continue
            changed.append({"path": node.path(), "op": op})
        return changed, {name: node.path() for name, node in aliases.items()}

    def op_batch(
        self, job, actions, expected=None, output=None, feedback=True, views=None, resolution=640
    ):
        hou = self.hou
        self._validate_actions(actions, expected or {})
        label = "Houdini Companion " + job["job_id"]
        try:
            with hou.undos.group(label):
                changed, aliases = self._apply_actions(actions)
                resolved_output = (
                    aliases[output[1:]] if output and output.startswith("$") else output
                )
                if resolved_output:
                    self.ledger.phase(job["job_id"], "cooking")
                    node = require_node(hou, resolved_output)
                    node.cook(force=False)
                    if node.errors():
                        raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
        except Exception as exc:
            labels = hou.undos.undoLabels()
            rolled_back = bool(labels and labels[0] == label)
            if rolled_back:
                hou.undos.performUndo()
            raise CompanionError(
                "BATCH_FAILED",
                str(exc),
                rollback="undone" if rolled_back else "not_available",
                consistency="verify_target" if not rolled_back else "restored",
            ) from exc
        self.undo_records[job["job_id"]] = {"label": label, "scene_id": self.ledger.scene_id}
        result = {
            "changed": changed,
            "aliases": aliases,
            "undo_job_id": job["job_id"],
            "undo_scope": "Houdini undoable changes only; external side effects excluded",
        }
        if resolved_output:
            try:
                result["inspection"] = inspect_node(
                    hou,
                    resolved_output,
                    geometry=isinstance(hou.node(resolved_output), hou.SopNode),
                )
                if feedback:
                    result["feedback"] = self.op_snapshot(job, resolved_output, views, resolution)
            except Exception as exc:
                result["feedback_error"] = str(exc)
                result["verification"] = "incomplete"
        return result

    def op_undo(self, job, job_id):
        record = self.undo_records.get(job_id)
        if not record or record["scene_id"] != self.ledger.scene_id:
            raise CompanionError("UNDO_UNAVAILABLE", "No undo record in the current scene")
        labels = self.hou.undos.undoLabels()
        if not labels or labels[0] != record["label"]:
            raise CompanionError(
                "UNDO_CONFLICT", "A newer action is on the undo stack; it will not be undone"
            )
        self.hou.undos.performUndo()
        del self.undo_records[job_id]
        return {"undone_job_id": job_id, "external_side_effects_undone": False}

    def op_execute(self, job, code, output=None, feedback=True, expected=None):
        if not isinstance(code, str) or len(code.encode()) > 256000:
            raise CompanionError("CODE_LIMIT", "Code must be text under 256 KB")
        for path, token in (expected or {}).items():
            check_expected(self.hou, require_node(self.hou, path), token)
        stdout, stderr = BoundedOutput(), BoundedOutput()
        namespace = {"hou": self.hou, "__name__": "__companion_job__"}
        label = "Houdini Companion " + job["job_id"]
        try:
            with (
                self.hou.undos.group(label),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exec(compile(code, "<companion-job>", "exec"), namespace)
        except Exception as exc:
            raise CompanionError(
                "CODE_FAILED",
                str(exc),
                stdout=stdout.getvalue(),
                stderr=stderr.getvalue(),
                consistency="unknown; arbitrary code may have external side effects",
            ) from exc
        self.undo_records[job["job_id"]] = {"label": label, "scene_id": self.ledger.scene_id}
        value = namespace.get("result")
        try:
            if len(json.dumps(value, allow_nan=False)) > 100000:
                value = {"truncated": True, "repr": repr(value)[:8000]}
        except (TypeError, ValueError):
            value = {"repr": repr(value)[:8000]}
        result = {
            "value": value,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "undo_job_id": job["job_id"],
            "execution_policy": "trusted Python; no sandbox or atomicity guarantee",
        }
        if output and feedback:
            try:
                result["feedback"] = self.op_snapshot(job, output)
            except Exception as exc:
                result.update(feedback_error=str(exc), verification="incomplete")
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
        result = self.op_batch(
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
