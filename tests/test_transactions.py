"""Transaction safety, policy coverage, checkpoints, conflicts, and audit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from houdini_mcp.tools.transactions import (
    MUTATING_TOOL_POLICIES,
    TransactionConflict,
    TransactionManager,
    TransactionPolicy,
)

EXPECTED_MUTATING_TOOLS = {
    "assign_material",
    "connect_nodes",
    "create_material",
    "create_network_box",
    "create_node",
    "create_render_node",
    "delete_node",
    "disconnect_node_input",
    "execute_code",
    "layout_children",
    "load_scene",
    "new_scene",
    "render_quad_view",
    "render_viewport",
    "reorder_inputs",
    "save_scene",
    "set_node_color",
    "set_node_flags",
    "set_node_position",
    "set_parameter",
    "set_render_settings",
}


def manager(mock_connection, tmp_path: Path, revision):
    return TransactionManager(
        mock_connection,
        revision,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_path=tmp_path / "transactions.jsonl",
        checkpoint_retention=2,
    )


def test_every_mutating_tool_has_an_explicit_policy():
    assert set(MUTATING_TOOL_POLICIES) == EXPECTED_MUTATING_TOOLS
    assert all(isinstance(policy, TransactionPolicy) for policy in MUTATING_TOOL_POLICIES.values())


def test_failed_multistep_transaction_closes_group_then_undoes(mock_connection, tmp_path):
    revision = ["before"]
    tx_manager = manager(mock_connection, tmp_path, lambda: revision[0])

    with (
        pytest.raises(ValueError, match="step two"),
        tx_manager.begin(["create_node", "set_parameter"], affected_paths=["/obj/geo1"]),
    ):
        revision[0] = "mutated"
        raise ValueError("step two failed")

    assert mock_connection.undos.open_groups == []
    assert mock_connection.undos.performed_undos == 1
    assert tx_manager.history[-1].result == "rolled_back"
    assert tx_manager.active is None


def test_undo_refuses_intervening_human_edit(mock_connection, tmp_path):
    revision = ["before"]
    tx_manager = manager(mock_connection, tmp_path, lambda: revision[0])
    with tx_manager.begin(["set_parameter"], affected_paths=["/obj/geo1"]):
        revision[0] = "agent-after"

    revision[0] = "human-after"
    with pytest.raises(TransactionConflict, match="changed after"):
        tx_manager.undo_last_agent_action()
    assert mock_connection.undos.performed_undos == 0


def test_undo_last_agent_action_when_revision_matches(mock_connection, tmp_path):
    revision = ["before"]
    tx_manager = manager(mock_connection, tmp_path, lambda: revision[0])
    with tx_manager.begin(["set_node_position"], affected_paths=["/obj/geo1"]):
        revision[0] = "agent-after"

    record = tx_manager.undo_last_agent_action()
    assert record.result == "undone"
    assert mock_connection.undos.performed_undos == 1


def test_checkpoint_is_atomic_and_retention_bounded(mock_connection, tmp_path, monkeypatch):
    tx_manager = manager(mock_connection, tmp_path, lambda: "scene")

    def save(path):
        Path(path).write_text("hip", encoding="utf-8")

    mock_connection.hipFile.save.side_effect = save
    for index in range(3):
        with tx_manager.begin(
            ["load_scene"],
            policy=TransactionPolicy.CHECKPOINT_REQUIRED,
            affected_paths=[f"scene-{index}"],
        ):
            pass

    files = list((tmp_path / "checkpoints").glob("mcp-*.hip"))
    assert len(files) == 2
    assert not list((tmp_path / "checkpoints").glob("*.tmp"))


def test_external_side_effect_is_not_claimed_rolled_back(mock_connection, tmp_path):
    tx_manager = manager(mock_connection, tmp_path, lambda: "scene")
    with (
        pytest.raises(RuntimeError),
        tx_manager.begin(["render_viewport"], affected_paths=["/tmp/output.png"]) as tx,
    ):
        tx.add_external_side_effect("rendered /tmp/output.png")
        raise RuntimeError("post-render failure")

    record = tx_manager.history[-1]
    assert record.result == "failed"
    assert record.side_effects == ["rendered /tmp/output.png"]
    assert mock_connection.undos.performed_undos == 0


def test_audit_contains_attribution_paths_duration_and_result(mock_connection, tmp_path):
    tx_manager = manager(mock_connection, tmp_path, lambda: "rev")
    with tx_manager.begin(
        ["connect_nodes"],
        affected_paths=["/obj/a", "/obj/b"],
        caller="mcp-agent",
        session_id="session-42",
    ):
        pass

    row = json.loads((tmp_path / "transactions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["transaction_id"]
    assert row["caller"] == "mcp-agent"
    assert row["session_id"] == "session-42"
    assert row["tools"] == ["connect_nodes"]
    assert row["affected_paths"] == ["/obj/a", "/obj/b"]
    assert row["duration_ms"] >= 0
    assert row["result"] == "committed"


def test_undo_never_runs_while_group_is_open(mock_connection, tmp_path):
    tx_manager = manager(mock_connection, tmp_path, lambda: "rev")
    with tx_manager.begin(["create_node"]), pytest.raises(TransactionConflict, match="active"):
        tx_manager.undo_last_agent_action()
    assert mock_connection.undos.performed_undos == 0
