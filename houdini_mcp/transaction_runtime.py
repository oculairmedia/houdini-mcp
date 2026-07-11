"""Server-side transaction runtime shared by mutating MCP wrappers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .connection import ensure_connected
from .tools._common import _serialize_scene_state
from .tools.transactions import TransactionConflict, TransactionManager, TransactionRecord

_manager: TransactionManager | None = None
_manager_endpoint: tuple[str, int] | None = None


def _scene_revision(hou: Any) -> str:
    state = _serialize_scene_state(hou, "/obj")
    payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def transaction_manager(host: str, port: int) -> TransactionManager:
    global _manager, _manager_endpoint
    endpoint = (host, port)
    if _manager is None or _manager_endpoint != endpoint:
        hou = ensure_connected(host, port)
        checkpoint_dir = Path(
            os.getenv(
                "HOUDINI_MCP_CHECKPOINT_DIR",
                str(Path(tempfile.gettempdir()) / "houdini-mcp-checkpoints"),
            )
        )
        audit_path = Path(
            os.getenv(
                "HOUDINI_MCP_TRANSACTION_AUDIT",
                str(Path(tempfile.gettempdir()) / "houdini-mcp-transactions.jsonl"),
            )
        )
        _manager = TransactionManager(
            hou,
            lambda: _scene_revision(hou),
            checkpoint_dir=checkpoint_dir,
            audit_path=audit_path,
        )
        _manager_endpoint = endpoint
    return _manager


def _record_metadata(record: TransactionRecord) -> dict[str, Any]:
    return {
        "transaction_id": record.transaction_id,
        "transaction_policy": record.policy.value,
        "transaction_result": record.result,
        "scene_revision_before": record.before_revision,
        "scene_revision_after": record.after_revision,
        "transaction_duration_ms": record.duration_ms,
        "affected_paths": list(dict.fromkeys(record.affected_paths)),
        "external_side_effects": record.side_effects,
        "checkpoint_path": record.checkpoint_path,
    }


@contextmanager
def transactional_tool(
    tool: str,
    *,
    host: str,
    port: int,
    affected_paths: list[str] | None = None,
    caller: str = "mcp-agent",
    session_id: str = "mcp",
) -> Iterator[dict[str, Any]]:
    manager = transaction_manager(host, port)
    with manager.begin(
        [tool], affected_paths=affected_paths, caller=caller, session_id=session_id
    ) as transaction:
        result: dict[str, Any] = {}
        yield result
    result["_transaction"] = _record_metadata(transaction.record)


def run_transactional(
    tool: str,
    operation: Any,
    *,
    host: str,
    port: int,
    affected_paths: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any]
    with transactional_tool(tool, host=host, port=port, affected_paths=affected_paths) as container:
        result = operation()
        container.update(result)
    return container


def undo_last_agent_action(host: str, port: int) -> dict[str, Any]:
    try:
        record = transaction_manager(host, port).undo_last_agent_action()
        return {"status": "success", "_transaction": _record_metadata(record)}
    except TransactionConflict as conflict:
        return {
            "status": "conflict",
            "error": "transaction_conflict",
            "message": str(conflict),
        }


def reset_transaction_runtime() -> None:
    """Test hook; production retains one manager per configured endpoint."""
    global _manager, _manager_endpoint
    _manager = None
    _manager_endpoint = None
