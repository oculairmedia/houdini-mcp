"""Remote mode for the Houdini MCP Plugin (backwards-compatible facade).

This module preserves the historic module-level API
(``start_hrpyc_server`` / ``stop_hrpyc_server`` / ``is_hrpyc_running`` /
``get_hrpyc_status``) while delegating to the testable
:class:`houdini_mcp_plugin.listener.RemoteListener`.

The manual/direct hrpyc workflow (running ``import hrpyc;
hrpyc.start_server(port=...)`` in Houdini's Python shell) remains fully
supported and untouched — this facade is an *additional*, safer entry point.

Security: binds to ``127.0.0.1`` by default. Non-loopback binds (via
``HOUDINI_RPC_BIND_HOST``) require an explicit trusted-network opt-in
(``HOUDINI_RPC_TRUSTED_NETWORK=1``) or an authentication token
(``HOUDINI_RPC_TOKEN``). See :mod:`houdini_mcp_plugin.listener`.
"""

from __future__ import annotations

import logging
from typing import Any

from .listener import ListenerConfig, RemoteListener

logger = logging.getLogger("houdini_mcp_plugin.remote")

# A single process-wide listener instance backs the module-level API.
_listener: RemoteListener | None = None


def _import_hrpyc() -> Any:
    """Import the real ``hrpyc`` module (overridable in tests)."""
    import hrpyc  # noqa: PLC0415 - only available inside Houdini

    return hrpyc


def _import_hou() -> Any:
    """Import the real ``hou`` module (overridable in tests)."""
    try:
        import hou  # noqa: PLC0415 - only available inside Houdini

        return hou
    except ImportError:
        return None


def _get_listener() -> RemoteListener:
    global _listener
    if _listener is None:
        _listener = RemoteListener(hrpyc=_import_hrpyc(), hou=_import_hou())
    return _listener


def reset_listener() -> None:
    """Stop and drop the current listener (used by tests and hard resets)."""
    global _listener
    if _listener is not None:
        try:
            _listener.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error during listener reset: %s", exc)
    _listener = None


def start_hrpyc_server(port: int | None = None) -> dict:
    """Start the hrpyc listener for remote connections (backwards-compatible).

    Bind host / security options are read from the environment
    (``HOUDINI_RPC_BIND_HOST``, ``HOUDINI_RPC_TRUSTED_NETWORK``,
    ``HOUDINI_RPC_TOKEN``). ``port`` overrides ``HOUDINI_RPC_BIND_PORT`` when
    provided.
    """
    listener = _get_listener()
    cfg = ListenerConfig.from_env()
    if port is not None:
        cfg.port = port
    return listener.start(cfg)


def stop_hrpyc_server() -> dict:
    """Stop the hrpyc listener."""
    return _get_listener().stop()


def is_hrpyc_running() -> bool:
    """Return True if the hrpyc listener is running."""
    global _listener
    return _listener is not None and _listener.is_running()


def get_hrpyc_status() -> dict:
    """Return the current hrpyc listener status."""
    if _listener is None:
        return {"running": False, "message": "hrpyc listener is not running."}
    return _listener.status()


def self_test_hrpyc() -> dict:
    """Run a reachability + capability self-test on the hrpyc listener."""
    if _listener is None:
        return {
            "running": False,
            "reachable": False,
            "stale": False,
            "warnings": ["hrpyc listener is not running."],
            "guidance": ["Start the listener before running a self-test."],
        }
    return _listener.self_test()


def reload_hrpyc_server(port: int | None = None) -> dict:
    """Restart the hrpyc listener with current environment configuration."""
    listener = _get_listener()
    cfg = ListenerConfig.from_env()
    if port is not None:
        cfg.port = port
    return listener.reload(cfg)
