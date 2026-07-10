"""Failure-mode, security-enforcement, self-test and reconnect tests.

Part of houdini-mcp-00p. Uses hermetic fakes (see ``conftest.py``).
"""

from __future__ import annotations

import socket

import pytest
from houdini_mcp_plugin.listener import (
    ListenerConfig,
    RemoteListener,
    SecurityError,
)

# ---------------------------------------------------------------------------
# Bind failures
# ---------------------------------------------------------------------------


class TestBindFailure:
    def test_start_reports_error_on_bind_failure(self, fake_hrpyc_bind_fail, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc_bind_fail, hou=fake_hou)
        result = listener.start(ListenerConfig(host="127.0.0.1", port=free_port))

        assert result["status"] == "error"
        assert result["running"] is False
        assert "in use" in result["message"].lower() or "bind" in result["message"].lower()
        # State stays clean: not running, so a later stop is a no-op.
        assert listener.is_running() is False

    def test_wrong_port_already_taken_surfaces_as_error(self, fake_hrpyc, fake_hou):
        # Occupy a port with a real socket, then ask the listener to bind it.
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        taken_port = holder.getsockname()[1]
        try:
            listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
            result = listener.start(
                ListenerConfig(host="127.0.0.1", port=taken_port, reuse_addr=False)
            )
            assert result["status"] == "error"
            assert listener.is_running() is False
        finally:
            holder.close()

    def test_missing_hrpyc_module_is_reported(self, fake_hou, free_port):
        listener = RemoteListener(hrpyc=None, hou=fake_hou)
        result = listener.start(ListenerConfig(host="127.0.0.1", port=free_port))
        assert result["status"] == "error"
        assert "hrpyc" in result["message"].lower()


# ---------------------------------------------------------------------------
# Security enforcement at start()
# ---------------------------------------------------------------------------


class TestSecurityEnforcement:
    def test_wildcard_bind_refused_without_opt_in(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        result = listener.start(ListenerConfig(host="0.0.0.0", port=free_port))

        assert result["status"] == "error"
        assert result["error_type"] == "security"
        assert listener.is_running() is False
        # No server was ever created -> no silent exposure.
        assert fake_hrpyc.servers == []

    def test_wildcard_bind_raises_when_strict(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        with pytest.raises(SecurityError):
            listener.start(ListenerConfig(host="0.0.0.0", port=free_port), raise_on_policy=True)

    def test_wildcard_bind_allowed_with_trusted_network(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        result = listener.start(
            ListenerConfig(host="0.0.0.0", port=free_port, trusted_network=True)
        )
        assert result["status"] == "success"
        assert result["security"]["loopback_only"] is False
        assert result["security"]["exposure"] == "network"

    def test_wildcard_bind_allowed_with_token(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        result = listener.start(ListenerConfig(host="0.0.0.0", port=free_port, token="hunter2"))
        assert result["status"] == "success"
        assert result["security"]["authenticated"] is True


# ---------------------------------------------------------------------------
# Self-test / status / capability / version + loopback warning
# ---------------------------------------------------------------------------


class TestSelfTestAndStatus:
    def test_status_when_stopped(self, fake_hrpyc, fake_hou):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        status = listener.status()
        assert status["running"] is False

    def test_status_when_running_reports_endpoint(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        listener.start(ListenerConfig(host="127.0.0.1", port=free_port))
        status = listener.status()
        assert status["running"] is True
        assert status["host"] == "127.0.0.1"
        assert status["port"] == free_port
        assert status["bound_port"] == free_port

    def test_self_test_reports_reachable_and_versions(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        listener.start(ListenerConfig(host="127.0.0.1", port=free_port))
        report = listener.self_test()

        assert report["reachable"] is True
        assert report["houdini_version"] == "20.5.487"
        assert report["houdini_version_tuple"] == [20, 5, 487]
        assert report["plugin_version"]  # non-empty
        assert report["protocol"]  # e.g. rpyc/hrpyc protocol descriptor
        assert "bound_endpoints" in report

    def test_self_test_warns_on_loopback_only(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        listener.start(ListenerConfig(host="127.0.0.1", port=free_port))
        report = listener.self_test()

        assert report["loopback_only"] is True
        warnings_text = " ".join(report["warnings"]).lower()
        assert "loopback" in warnings_text
        # Remote clients (e.g. Docker gateway) cannot reach loopback.
        assert any("firewall" in g.lower() or "bind" in g.lower() for g in report["guidance"])

    def test_self_test_no_loopback_warning_when_wildcard(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        listener.start(ListenerConfig(host="0.0.0.0", port=free_port, trusted_network=True))
        report = listener.self_test()
        assert report["loopback_only"] is False
        # Firewall guidance still present (port must be open).
        assert report["guidance"]

    def test_self_test_when_stopped_reports_unreachable(self, fake_hrpyc, fake_hou):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        report = listener.self_test()
        assert report["reachable"] is False
        assert report["running"] is False

    def test_self_test_detects_stale_listener(self, fake_hrpyc, fake_hou, free_port):
        """A listener whose socket died out from under us is detected."""
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        listener.start(ListenerConfig(host="127.0.0.1", port=free_port))

        # Simulate the underlying server dying (stale reference).
        fake_hrpyc.servers[0].close()

        report = listener.self_test()
        assert report["reachable"] is False
        assert report["stale"] is True


# ---------------------------------------------------------------------------
# Reconnect / restart after stale
# ---------------------------------------------------------------------------


class TestReconnect:
    def test_restart_after_stale_listener_succeeds(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        listener.start(ListenerConfig(host="127.0.0.1", port=free_port))

        # Underlying listener dies.
        fake_hrpyc.servers[0].close()
        assert listener.self_test()["stale"] is True

        # A reload should recover cleanly on a fresh port.
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        new_port = s.getsockname()[1]
        s.close()

        result = listener.reload(ListenerConfig(host="127.0.0.1", port=new_port))
        assert result["status"] == "success"
        assert listener.self_test()["reachable"] is True

    def test_stop_clears_stale_state(self, fake_hrpyc, fake_hou, free_port):
        listener = RemoteListener(hrpyc=fake_hrpyc, hou=fake_hou)
        listener.start(ListenerConfig(host="127.0.0.1", port=free_port))
        fake_hrpyc.servers[0].close()

        result = listener.stop()
        # Stop must succeed even if the server was already dead.
        assert result["status"] in ("success", "not_running")
        assert listener.is_running() is False
