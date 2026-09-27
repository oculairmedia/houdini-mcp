from __future__ import annotations

from ..core import CompanionError
from ..observation import (
    check_expected,
    inspect_node,
    require_node,
)
from . import BasePlugin, make_plugin


class Handlers(BasePlugin):
    def _validate_actions(self, actions, expected):
        if not isinstance(actions, list) or not 1 <= len(actions) <= 128:
            raise CompanionError("INVALID_BATCH", "Provide 1â€“128 actions")
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
                    result["feedback"] = self.context.call(
                        "snapshot",
                        job,
                        path=resolved_output,
                        views=views or ["front", "right", "persp"],
                        resolution=resolution,
                    )
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


def plugin():
    return make_plugin("scene", Handlers, ("batch", "undo"), requires=("query",))
