"""Transaction primitives for recoverable, attributable Houdini mutations."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class TransactionPolicy(StrEnum):
    UNDOABLE = "undoable"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


MUTATING_TOOL_POLICIES: dict[str, TransactionPolicy] = {
    "assign_material": TransactionPolicy.UNDOABLE,
    "connect_nodes": TransactionPolicy.UNDOABLE,
    "create_material": TransactionPolicy.UNDOABLE,
    "create_network_box": TransactionPolicy.UNDOABLE,
    "create_node": TransactionPolicy.UNDOABLE,
    "create_render_node": TransactionPolicy.UNDOABLE,
    "delete_node": TransactionPolicy.UNDOABLE,
    "disconnect_node_input": TransactionPolicy.UNDOABLE,
    "execute_code": TransactionPolicy.CHECKPOINT_REQUIRED,
    "layout_children": TransactionPolicy.UNDOABLE,
    "load_scene": TransactionPolicy.CHECKPOINT_REQUIRED,
    "new_scene": TransactionPolicy.CHECKPOINT_REQUIRED,
    "render_quad_view": TransactionPolicy.EXTERNAL_SIDE_EFFECT,
    "render_viewport": TransactionPolicy.EXTERNAL_SIDE_EFFECT,
    "reorder_inputs": TransactionPolicy.UNDOABLE,
    "save_scene": TransactionPolicy.EXTERNAL_SIDE_EFFECT,
    "set_node_color": TransactionPolicy.UNDOABLE,
    "set_node_flags": TransactionPolicy.UNDOABLE,
    "set_node_position": TransactionPolicy.UNDOABLE,
    "set_parameter": TransactionPolicy.UNDOABLE,
    "set_render_settings": TransactionPolicy.UNDOABLE,
}


@dataclass
class TransactionRecord:
    transaction_id: str
    caller: str
    session_id: str
    policy: TransactionPolicy
    tools: list[str]
    affected_paths: list[str]
    started_at: float
    duration_ms: int = 0
    result: str = "active"
    before_revision: str = ""
    after_revision: str = ""
    side_effects: list[str] = field(default_factory=list)
    checkpoint_path: str | None = None


class TransactionConflict(RuntimeError):
    """Raised when undo would overwrite an intervening scene edit."""


class SceneTransaction(AbstractContextManager["SceneTransaction"]):
    def __init__(
        self,
        manager: TransactionManager,
        *,
        tools: list[str],
        policy: TransactionPolicy,
        affected_paths: list[str],
        caller: str,
        session_id: str,
    ) -> None:
        self.manager = manager
        self.record = TransactionRecord(
            transaction_id=str(uuid.uuid4()),
            caller=caller,
            session_id=session_id,
            policy=policy,
            tools=tools,
            affected_paths=affected_paths,
            started_at=time.monotonic(),
        )
        self._undo_context: Any = None

    def __enter__(self) -> SceneTransaction:
        if self.manager.active is not None:
            raise RuntimeError("A scene transaction is already active")
        self.record.before_revision = self.manager.revision()
        if self.record.policy == TransactionPolicy.CHECKPOINT_REQUIRED:
            self.record.checkpoint_path = str(
                self.manager.create_checkpoint(self.record.transaction_id)
            )
        try:
            if self.record.policy == TransactionPolicy.UNDOABLE:
                self._undo_context = self.manager.hou.undos.group(
                    f"Houdini MCP {self.record.transaction_id}"
                )
                self._undo_context.__enter__()
        except Exception:
            self.manager.active = None
            raise
        self.manager.active = self
        return self

    def add_tool(self, tool: str, *paths: str) -> None:
        self.record.tools.append(tool)
        self.record.affected_paths.extend(path for path in paths if path)

    def add_external_side_effect(self, description: str) -> None:
        self.record.side_effects.append(description)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            if self._undo_context is not None:
                self._undo_context.__exit__(exc_type, exc, traceback)
        except Exception:
            self.record.result = "unknown_consistency"
            self.manager._finish(self.record)
            raise
        finally:
            self.manager.active = None

        if exc_type is not None:
            self.record.result = (
                "rolled_back" if self.record.policy == TransactionPolicy.UNDOABLE else "failed"
            )
            # The undo group is closed now; never undo while code may still run.
            if self.record.policy == TransactionPolicy.UNDOABLE:
                self.manager.hou.undos.performUndo()
            self.manager._finish(self.record)
            return False

        self.record.result = "committed"
        self.record.after_revision = self.manager.revision()
        self.manager._finish(self.record)
        return False


class TransactionManager:
    def __init__(
        self,
        hou: Any,
        revision: Callable[[], str],
        *,
        checkpoint_dir: Path,
        audit_path: Path,
        checkpoint_retention: int = 3,
    ) -> None:
        self.hou = hou
        self.revision = revision
        self.checkpoint_dir = checkpoint_dir
        self.audit_path = audit_path
        self.checkpoint_retention = max(1, checkpoint_retention)
        self.active: SceneTransaction | None = None
        self.history: list[TransactionRecord] = []

    def begin(
        self,
        tools: list[str],
        *,
        policy: TransactionPolicy | None = None,
        affected_paths: list[str] | None = None,
        caller: str = "agent",
        session_id: str = "default",
    ) -> SceneTransaction:
        resolved = policy or MUTATING_TOOL_POLICIES[tools[0]]
        return SceneTransaction(
            self,
            tools=list(tools),
            policy=resolved,
            affected_paths=list(affected_paths or []),
            caller=caller,
            session_id=session_id,
        )

    def create_checkpoint(self, transaction_id: str) -> Path:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        destination = self.checkpoint_dir / f"mcp-{transaction_id}.hip"
        temporary = destination.with_suffix(".hip.tmp")
        self.hou.hipFile.save(str(temporary))
        os.replace(temporary, destination)
        checkpoints = sorted(
            self.checkpoint_dir.glob("mcp-*.hip"), key=lambda path: path.stat().st_mtime
        )
        for stale in checkpoints[: -self.checkpoint_retention]:
            stale.unlink(missing_ok=True)
        return destination

    def undo_last_agent_action(self) -> TransactionRecord:
        if self.active is not None:
            raise TransactionConflict("Cannot undo while a transaction is active")
        committed = next(
            (record for record in reversed(self.history) if record.result == "committed"), None
        )
        if committed is None:
            raise TransactionConflict("No committed agent transaction to undo")
        if committed.policy != TransactionPolicy.UNDOABLE:
            raise TransactionConflict("Latest transaction is not Houdini-undoable")
        if self.revision() != committed.after_revision:
            raise TransactionConflict("Scene changed after the agent transaction")
        self.hou.undos.performUndo()
        committed.result = "undone"
        self._append_audit(committed)
        return committed

    def _finish(self, record: TransactionRecord) -> None:
        record.duration_ms = max(0, int((time.monotonic() - record.started_at) * 1000))
        if not record.after_revision:
            record.after_revision = self.revision()
        self.history.append(record)
        self._append_audit(record)

    def _append_audit(self, record: TransactionRecord) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), default=str, sort_keys=True) + "\n")
