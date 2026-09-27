import json

import pytest

from houdini_companion.cli import install, main
from houdini_companion.client import Client
from houdini_companion.core import CompanionError


def test_wait_timeout_returns_running_job_without_resubmission(monkeypatch):
    client = Client(descriptor={})
    actions = []

    def call(action, **fields):
        actions.append(action)
        return {"job_id": "one", "state": "running"}

    monkeypatch.setattr(client, "call", call)
    assert client.wait("one", timeout=0)["state"] == "running"
    assert actions == ["job"]


def test_submit_preserves_retry_identity_on_transport_error(monkeypatch):
    client = Client(descriptor={})

    def call(action, **fields):
        if action == "health":
            return {"session_id": "session", "scene_id": "scene"}
        raise CompanionError("TRANSPORT", "lost reply")

    monkeypatch.setattr(client, "call", call)
    with pytest.raises(CompanionError) as exc:
        client.submit("batch", {}, "stable-id")
    assert exc.value.details["request"]["request_id"] == "stable-id"


def test_installer_is_idempotent_and_preserves_other_configuration(tmp_path):
    repository = tmp_path / "repo"
    (repository / "houdini_plugin").mkdir(parents=True)
    prefs = tmp_path / "prefs"
    first = install(prefs, repository)
    assert first == install(prefs, repository)
    path = prefs / "packages" / "houdini_companion.json"
    path.write_text('{"existing":true}')
    with pytest.raises(CompanionError) as exc:
        install(prefs, repository)
    assert exc.value.code == "INSTALL_CONFLICT"
    assert json.loads(path.read_text()) == {"existing": True}


def test_schema_command_does_not_require_live_houdini(capsys):
    assert main(["schema"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"]
    assert result["result"]["operations"]["execute"] == "code"
