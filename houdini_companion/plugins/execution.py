from __future__ import annotations

import contextlib
import io
import json

from ..core import CompanionError
from ..observation import (
    check_expected,
    require_node,
)
from . import BasePlugin, make_plugin


class BoundedOutput(io.StringIO):
    def write(self, text):
        remaining = max(0, 16000 - self.tell())
        super().write(text[:remaining])
        return len(text)


class Handlers(BasePlugin):
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
                result["feedback"] = self.context.call("snapshot", job, path=output)
            except Exception as exc:
                result.update(feedback_error=str(exc), verification="incomplete")
        return result


def plugin():
    return make_plugin("execution", Handlers, ("execute",), requires=("review",))
