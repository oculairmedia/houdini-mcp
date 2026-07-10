"""Backwards-compatibility tests for the existing module-level remote API.

The manual/direct hrpyc mode and the historic ``start_hrpyc_server`` /
``stop_hrpyc_server`` / ``is_hrpyc_running`` / ``get_hrpyc_status`` functions
must keep working (houdini-mcp-00p acceptance #5).
"""

from __future__ import annotations

import socket

import houdini_mcp_plugin.remote as remote
import pytest


@pytest.fixture(autouse=True)
def _reset_remote_state():
    """Ensure global remote state is clean before/after each test."""
    remote.reset_listener()
    yield
    remote.reset_listener()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestLegacyModuleApi:
    def test_start_and_stop_roundtrip(self, monkeypatch, fake_hrpyc, fake_hou):
        monkeypatch.setattr(remote, "_import_hrpyc", lambda: fake_hrpyc)
        monkeypatch.setattr(remote, "_import_hou", lambda: fake_hou)
        port = _free_port()

        status = remote.start_hrpyc_server(port=port)
        assert status["status"] == "success"
        assert status["port"] == port
        assert remote.is_hrpyc_running() is True

        got = remote.get_hrpyc_status()
        assert got["running"] is True
        assert got["port"] == port

        stopped = remote.stop_hrpyc_server()
        assert stopped["status"] == "success"
        assert remote.is_hrpyc_running() is False

    def test_start_is_idempotent_legacy(self, monkeypatch, fake_hrpyc, fake_hou):
        monkeypatch.setattr(remote, "_import_hrpyc", lambda: fake_hrpyc)
        monkeypatch.setattr(remote, "_import_hou", lambda: fake_hou)
        port = _free_port()

        remote.start_hrpyc_server(port=port)
        again = remote.start_hrpyc_server(port=port)
        assert again["status"] == "already_running"

    def test_get_status_when_stopped(self):
        status = remote.get_hrpyc_status()
        assert status["running"] is False

    def test_default_bind_is_loopback(self, monkeypatch, fake_hrpyc, fake_hou):
        monkeypatch.setattr(remote, "_import_hrpyc", lambda: fake_hrpyc)
        monkeypatch.setattr(remote, "_import_hou", lambda: fake_hou)
        monkeypatch.delenv("HOUDINI_RPC_BIND_HOST", raising=False)
        port = _free_port()

        status = remote.start_hrpyc_server(port=port)
        assert status["status"] == "success"
        assert status["host"] == "127.0.0.1"

    def test_env_bind_host_wildcard_refused_without_optin(self, monkeypatch, fake_hrpyc, fake_hou):
        monkeypatch.setattr(remote, "_import_hrpyc", lambda: fake_hrpyc)
        monkeypatch.setattr(remote, "_import_hou", lambda: fake_hou)
        monkeypatch.setenv("HOUDINI_RPC_BIND_HOST", "0.0.0.0")
        monkeypatch.delenv("HOUDINI_RPC_TRUSTED_NETWORK", raising=False)
        monkeypatch.delenv("HOUDINI_RPC_TOKEN", raising=False)
        port = _free_port()

        status = remote.start_hrpyc_server(port=port)
        assert status["status"] == "error"
        assert remote.is_hrpyc_running() is False

    def test_self_test_exposed_at_module_level(self, monkeypatch, fake_hrpyc, fake_hou):
        monkeypatch.setattr(remote, "_import_hrpyc", lambda: fake_hrpyc)
        monkeypatch.setattr(remote, "_import_hou", lambda: fake_hou)
        port = _free_port()
        remote.start_hrpyc_server(port=port)

        report = remote.self_test_hrpyc()
        assert report["reachable"] is True
        assert report["houdini_version"]
