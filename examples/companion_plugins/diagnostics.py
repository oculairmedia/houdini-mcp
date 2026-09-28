"""Example trusted extension: explicitly enable this importable module at startup."""

from houdini_companion.registry import OperationSpec, PluginContext, PluginSpec


def frame(context: PluginContext, job: dict) -> dict:
    context.ledger.checkpoint(job["job_id"])
    return {"frame": context.hou.frame(), "houdini": context.hou.applicationVersionString()}


def plugin():
    return PluginSpec(
        "example.diagnostics",
        "1.0.0",
        (
            OperationSpec(
                "example.frame",
                "read",
                {"type": "object", "properties": {}, "additionalProperties": False},
                frame,
                "Return the live frame without inspecting any geometry.",
            ),
        ),
    )
