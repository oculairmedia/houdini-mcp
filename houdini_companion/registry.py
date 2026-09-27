"""Plugin API v1. Trusted plugins register explicitly; the catalog is immutable.

Handlers run only through the UI dispatcher. Transport adapters consume JSON
contracts and never import Houdini. A plugin is trusted Python, not a sandbox.
"""

from __future__ import annotations

import copy
import importlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import CompanionError
from .schema import check_schema, validate_schema

API_VERSION = 1
EFFECTS = {"read", "artifacts", "scene", "code", "preview"}


class PluginContext(Protocol):
    """Host services available to handlers on the UI thread only.

    Store plugin state under its own name; state resets with the scene. Use
    ledger.checkpoint(job_id) between expensive phases for cooperative cancel.
    call composes another registered operation within the current job.
    """

    hou: Any
    ledger: Any
    state: dict

    def call(self, operation: str, job: dict, **params) -> dict: ...


@dataclass(frozen=True)
class OperationSpec:
    name: str
    effect: str
    schema: dict
    handler: Callable
    description: str = ""


@dataclass(frozen=True)
class PluginSpec:
    name: str
    version: str
    operations: tuple[OperationSpec, ...]
    requires: tuple[str, ...] = ()
    api_version: int = API_VERSION


class Registry:
    def __init__(self, plugins):
        self._plugins, self._operations = {}, {}
        pending = list(plugins)
        names = [p.name for p in pending]
        if len(names) != len(set(names)):
            raise CompanionError("PLUGIN_CONFLICT", "Duplicate plugin name")
        while pending:
            ready = next((p for p in pending if set(p.requires) <= self._plugins.keys()), None)
            if ready is None:
                raise CompanionError("PLUGIN_DEPENDENCY", "Missing dependency or dependency cycle")
            if ready.api_version != API_VERSION:
                raise CompanionError(
                    "PLUGIN_API", "Plugin API version is unsupported", plugin=ready.name
                )
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", ready.name) or not ready.version:
                raise CompanionError("PLUGIN_METADATA", "Plugin name and version required")
            for op in ready.operations:
                if op.name in self._operations:
                    raise CompanionError(
                        "OPERATION_CONFLICT", "Operation already registered", operation=op.name
                    )
                if (
                    not re.fullmatch(r"[a-z][a-z0-9_.]*", op.name)
                    or op.effect not in EFFECTS
                    or not callable(op.handler)
                    or op.schema.get("type") != "object"
                ):
                    raise CompanionError(
                        "PLUGIN_CONTRACT", "Invalid operation contract", operation=op.name
                    )
                check_schema(op.schema)
                json.dumps(op.schema, allow_nan=False)
                # Caller changes to a manifest cannot mutate the live contract.
                self._operations[op.name] = (
                    ready.name,
                    OperationSpec(
                        op.name, op.effect, copy.deepcopy(op.schema), op.handler, op.description
                    ),
                )
            self._plugins[ready.name] = ready
            pending.remove(ready)

    def effects(self):
        return {name: op.effect for name, (_, op) in self._operations.items()}

    def catalog(self):
        return {
            "plugin_api": API_VERSION,
            "plugins": [
                {"name": p.name, "version": p.version, "requires": list(p.requires)}
                for p in self._plugins.values()
            ],
            "operations": self.effects(),
            "parameters": {
                name: copy.deepcopy(op.schema) for name, (_, op) in self._operations.items()
            },
            "contracts": {
                name: {
                    "plugin": owner,
                    "effect": op.effect,
                    "description": op.description,
                    "execution": "houdini_ui_thread",
                    "result": "JSON object",
                }
                for name, (owner, op) in self._operations.items()
            },
        }

    def validate(self, name, params):
        if name not in self._operations:
            raise CompanionError("INVALID_OPERATION", "Operation is not enabled", operation=name)
        validate_schema(self._operations[name][1].schema, params)

    def dispatch(self, context, job):
        self.validate(job["operation"], job["params"])
        context.ledger.checkpoint(job["job_id"])
        result = self._operations[job["operation"]][1].handler(context, job, **job["params"])
        if not isinstance(result, dict):
            raise CompanionError("PLUGIN_RESULT", "Plugin must return a JSON object")
        try:
            encoded = json.dumps(result, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise CompanionError("PLUGIN_RESULT", "Result is not finite JSON") from exc
        if len(encoded.encode()) > 4 * 1024 * 1024:
            raise CompanionError(
                "PLUGIN_RESULT_LIMIT", "Result exceeds 4 MiB; return an artifact instead"
            )
        return result


BUILTINS = ("query", "scene", "review", "execution", "introspection", "acceptance")


def load_registry(extra_modules=()):
    """Only explicitly configured modules are imported; no directory scanning."""
    modules = [f"houdini_companion.plugins.{name}" for name in BUILTINS]
    modules.extend(extra_modules)
    return Registry([importlib.import_module(name).plugin() for name in modules])
