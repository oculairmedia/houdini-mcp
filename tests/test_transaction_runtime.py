"""MCP boundary integration tests for scene transactions."""

from __future__ import annotations

from houdini_mcp import server
from houdini_mcp.transaction_runtime import reset_transaction_runtime


def test_create_node_wrapper_returns_transaction_metadata(mock_connection, monkeypatch, tmp_path):
    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))

    result = server.create_node.fn("geo", name="transaction_geo")

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

    result = server.set_parameter.fn("/obj/geo1", "tx", 4.0)

    assert result["status"] == "success"
    assert node._params["tx"] == 4.0
    assert len(mock_connection.undos.closed_groups) == 1
    assert result["_transaction"]["affected_paths"] == ["/obj/geo1"]


def test_undo_wrapper_refuses_intervening_scene_edit(mock_connection, monkeypatch, tmp_path):
    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))
    server.create_node.fn("geo", name="agent_geo")
    # Simulate a human edit that changes both revision and undo stack top.
    mock_connection.node("/obj").createNode("geo", "human_geo")
    mock_connection.undos.closed_groups.append("Human edit")

    result = server.undo_last_agent_action.fn()

    assert result["status"] == "conflict"
    assert result["error"] == "transaction_conflict"
    assert mock_connection.undos.performed_undos == 0


def test_undo_wrapper_succeeds_when_agent_action_is_stack_top(
    mock_connection, monkeypatch, tmp_path
):
    reset_transaction_runtime()
    monkeypatch.setenv("HOUDINI_MCP_TRANSACTION_AUDIT", str(tmp_path / "audit.jsonl"))
    created = server.create_node.fn("geo", name="agent_geo")

    result = server.undo_last_agent_action.fn()

    assert result["status"] == "success"
    assert result["_transaction"]["transaction_id"] == created["_transaction"]["transaction_id"]
    assert result["_transaction"]["transaction_result"] == "undone"
    assert mock_connection.undos.performed_undos == 1


def test_core_mutating_wrappers_are_transactional():
    """Static gate: core undoable wrappers may not bypass the runtime helper."""
    import inspect

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
        name
        for name in names
        if "run_transactional" not in inspect.getsource(getattr(server, name).fn)
    }
    assert not missing, f"Mutating wrappers bypass transaction runtime: {sorted(missing)}"
