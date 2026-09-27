"""Host execution context. Feature semantics live in registered plugins."""

from .registry import load_registry


class Operations:
    def __init__(self, hou, ledger, registry=None):
        self.hou, self.ledger = hou, ledger
        self.registry = registry or load_registry()
        self.state = {}

    @property
    def previews(self):
        return self.state.setdefault("previews", {})

    @property
    def undo_records(self):
        return self.state.setdefault("undo_records", {})

    def execute(self, job):
        return self.registry.dispatch(self, job)

    def call(self, operation, job, **params):
        """Internal composition shares one job identity and cancellation state."""
        return self.registry.dispatch(self, {**job, "operation": operation, "params": params})

    def reset(self):
        self.state.clear()
