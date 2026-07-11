"""MCP boundary integration tests for scene transactions."""

from __future__ import annotations

from houdini_mcp import server
from houdini_mcp.transaction_runtime import reset_transaction_runtime


def call_tool(tool, *args, **kwargs):
    """Call through FastMCP's FunctionTool or the raw function used by tests.

    The randomized full suite imports server under both the real decorator and a
    monkeypatched identity decorator, so module-level wrappers legitimately have
    either shape depending on test order.
    """
    return getattr(tool, "fn", tool)(*args, **kwargs)


def tool_source(tool):
    import inspect

    return inspect.getsource(getattr(tool, "fn", tool))


def test_create_node_wrapper_returns_transaction_metadata(mock_connection, monkeypatch, tmp_path):
    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))

    result = call_tool(server.create_node, "geo", name="transaction_geo")

    assert result["status"] == "success"
    assert result["node_path"] == "/obj/transaction_geo"
    metadata = result["_transaction"]
    assert metadata["transaction_id"]
    assert metadata["transaction_policy"] == "undoable"
    assert metadata["transaction_result"] == "committed"
    assert metadata["affected_paths"] == ["/obj"]
    assert metadata["scene_revision_before"] != metadata["scene_revision_after"]
    assert mock_connection.undos.closed_groups == [f"Houdini MCP {metadata['transaction_id']}"]


def test_parameter_wrapper_is_one_named_undo_action(mock_connection, monkeypatch, tmp_path):
    from tests.conftest import MockHouNode

    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))
    node = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo", params={"tx": 0.0})
    mock_connection.add_node(node)

    result = call_tool(server.set_parameter, "/obj/geo1", "tx", 4.0)

    assert result["status"] == "success"
    assert node._params["tx"] == 4.0
    assert len(mock_connection.undos.closed_groups) == 1
    assert result["_transaction"]["affected_paths"] == ["/obj/geo1"]


def test_undo_wrapper_refuses_intervening_scene_edit(mock_connection, monkeypatch, tmp_path):
    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))
    call_tool(server.create_node, "geo", name="agent_geo")
    # Simulate a human edit that changes both revision and undo stack top.
    mock_connection.node("/obj").createNode("geo", "human_geo")
    mock_connection.undos.closed_groups.append("Human edit")

    result = call_tool(server.undo_last_agent_action)

    assert result["status"] == "conflict"
    assert result["error"] == "transaction_conflict"
    assert mock_connection.undos.performed_undos == 0


def test_undo_wrapper_succeeds_when_agent_action_is_stack_top(
    mock_connection, monkeypatch, tmp_path
):
    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))
    created = call_tool(server.create_node, "geo", name="agent_geo")

    result = call_tool(server.undo_last_agent_action)

    assert result["status"] == "success"
    assert result["_transaction"]["transaction_id"] == created["_transaction"]["transaction_id"]
    assert result["_transaction"]["transaction_result"] == "undone"
    assert mock_connection.undos.performed_undos == 1


def test_checkpoint_entry_failure_releases_runtime_lock(mock_connection, monkeypatch, tmp_path):
    """A checkpoint failure must not deadlock the next MCP mutation."""
    import pytest

    from houdini_mcp.transaction_runtime import transaction_manager

    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))
    manager = transaction_manager("localhost", 18811)
    mock_connection.hipFile.saveAndBackup.side_effect = RuntimeError("checkpoint failed")

    with pytest.raises(RuntimeError, match="checkpoint failed"), manager.begin(["new_scene"]):
        pass

    assert manager.active is None
    # If the transaction-wide lock leaked, this call blocks forever in CI.
    result = call_tool(server.create_node, "geo", name="after_checkpoint_failure")
    assert result["status"] == "success"


def test_core_mutating_wrappers_are_transactional():
    """Static gate: core undoable wrappers may not bypass the runtime helper."""
    names = {
        "create_node",
        "delete_node",
        "set_parameter",
        "connect_nodes",
        "disconnect_node_input",
        "set_node_flags",
        "reorder_inputs",
        "create_material",
        "assign_material",
        "layout_children",
        "set_node_color",
        "set_node_position",
        "create_network_box",
    }
    missing = {
        name for name in names if "run_transactional" not in tool_source(getattr(server, name))
    }
    assert not missing, f"Mutating wrappers bypass transaction runtime: {sorted(missing)}"
