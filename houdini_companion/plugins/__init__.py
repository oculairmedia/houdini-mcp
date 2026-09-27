"""Built-in plugins share the public registry contract with explicit extensions."""

from ..registry import OperationSpec, PluginSpec
from ..schema import schemas

EFFECTS = {
    "inspect": "read",
    "validate_observation": "read",
    "snapshot": "artifacts",
    "batch": "scene",
    "undo": "scene",
    "execute": "code",
    "preview": "preview",
    "apply_preview": "scene",
    "discard_preview": "preview",
}


class BasePlugin:
    def __init__(self, context):
        self.context = context
        self.hou, self.ledger = context.hou, context.ledger
        self.undo_records = context.state.setdefault("undo_records", {})
        self.previews = context.state.setdefault("previews", {})


def make_plugin(name, handlers, operations, requires=(), extra=()):
    contracts = schemas()

    def bind(operation):
        def invoke(context, job, **params):
            return getattr(handlers(context), "op_" + operation)(job, **params)

        return invoke

    specs = tuple(
        OperationSpec(
            op, EFFECTS[op], contracts[op], bind(op), getattr(handlers, "op_" + op).__doc__ or op
        )
        for op in operations
    )
    return PluginSpec(name, "0.2.0", specs + tuple(extra), requires)
