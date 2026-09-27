import base64
from unittest.mock import Mock

import pytest

from houdini_mcp import companion_tools, tools


@pytest.mark.parametrize(
    "code,policy,reason",
    [
        ("hou.node('/obj').createNode('geo')", "read-only", "read_only_violation"),
        ("import os\nos.system('echo unexpected')", "normal", "dangerous_pattern"),
        ("print('x')", "privileged", "privileged_without_config"),
    ],
)
def test_legacy_policy_is_not_lost_in_companion_backend(monkeypatch, code, policy, reason):
    connection = Mock()
    monkeypatch.setattr(companion_tools, "client", lambda: connection)
    monkeypatch.delenv("HOUDINI_MCP_ALLOW_BYPASS", raising=False)
    adapter = companion_tools.ToolAdapter(tools)
    result = adapter.execute_code(code, policy=policy)
    assert result["status"] == "error"
    assert result["message"] == reason
    connection.run.assert_not_called()


def test_unmigrated_tool_never_falls_back_to_legacy(monkeypatch):
    monkeypatch.setattr(companion_tools, "client", Mock())
    legacy = Mock()
    legacy.save_scene = lambda _file_path=None, _host="localhost", _port=18811: pytest.fail(
        "legacy called"
    )
    result = companion_tools.ToolAdapter(legacy).save_scene()
    assert result["error"]["code"] == "UNMIGRATED_TOOL"


@pytest.mark.asyncio
async def test_feedback_returns_native_mcp_images(monkeypatch):
    from fastmcp import Client, FastMCP

    connection = Mock()
    connection.call.return_value = {
        "job_id": "one",
        "state": "succeeded",
        "result": {"images": [{"name": "persp.png"}]},
    }
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR1kAAAAASUVORK5CYII="
    )
    connection.artifact.return_value = png
    monkeypatch.setattr(companion_tools, "client", lambda: connection)
    server = FastMCP("companion-test")
    companion_tools.register(server)
    async with Client(server) as client:
        result = await client.call_tool("companion_feedback", {"job_id": "one"})
    assert any(getattr(item, "type", None) == "image" for item in result.content)
