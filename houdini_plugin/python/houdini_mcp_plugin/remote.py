"""Remote mode for Houdini MCP Plugin.

This module provides hrpyc server activation, allowing external MCP servers
to connect to Houdini via RPyC for remote control.
"""

import logging
import os
import socket
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("houdini_mcp_plugin.remote")

# Global state for remote mode
_hrpyc_server: Optional[Any] = None
_hrpyc_port: int = 18811
_hrpyc_host: str = "127.0.0.1"


def _wait_for_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True when a TCP listener accepts connections."""
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def start_hrpyc_server(port: int = 18811) -> dict:
    """Start the hrpyc server to allow remote connections.

    This enables external MCP servers (like the Docker-based server) to
    connect to this Houdini instance and execute commands.

    Args:
        port: Port to listen on (default: 18811)

    Returns:
        Dict with status and connection info
    """
    global _hrpyc_server, _hrpyc_port, _hrpyc_host

    if _hrpyc_server is not None:
        return {
            "status": "already_running",
            "port": _hrpyc_port,
            "host": _hrpyc_host,
            "message": f"hrpyc server is already running on {_hrpyc_host}:{_hrpyc_port}",
        }

    try:
        import hrpyc

        bind_host = os.getenv("HOUDINI_RPC_BIND_HOST", "127.0.0.1")
        _hrpyc_server = hrpyc.ThreadedServer(
            hrpyc.SlaveService,
            hostname=bind_host,
            port=port,
            reuse_addr=True,
            auto_register=False,
        )
        _hrpyc_server.logger.quiet = True
        thread = threading.Thread(target=_hrpyc_server.start, daemon=True)
        thread.start()

        if not _wait_for_port(bind_host, port):
            close = getattr(_hrpyc_server, "close", None)
            if close is not None:
                close()
            _hrpyc_server = None
            return {
                "status": "error",
                "message": f"Failed to start hrpyc server on {bind_host}:{port} (port may be in use).",
            }

        _hrpyc_port = port
        _hrpyc_host = bind_host

        logger.info(f"Started hrpyc server on {bind_host}:{port}")

        # Get local IP for connection info
        try:
            # Get the machine's IP address
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "localhost"

        return {
            "status": "success",
            "host": bind_host,
            "port": port,
            "local_ip": local_ip,
            "message": f"hrpyc server started. Connect with: HOUDINI_HOST={bind_host} HOUDINI_PORT={port}",
        }

    except ImportError as e:
        logger.error(f"hrpyc module not available: {e}")
        return {
            "status": "error",
            "message": "hrpyc module not available. Make sure Houdini's Python environment includes hrpyc.",
        }
    except Exception as e:
        logger.error(f"Failed to start hrpyc server: {e}")
        return {
            "status": "error",
            "message": f"Failed to start hrpyc server: {e}",
        }


def stop_hrpyc_server() -> dict:
    """Stop the hrpyc server.

    Returns:
        Dict with status
    """
    global _hrpyc_server

    if _hrpyc_server is None:
        return {
            "status": "not_running",
            "message": "hrpyc server is not running",
        }

    try:
        close = getattr(_hrpyc_server, "close", None)
        if close is None:
            return {
                "status": "error",
                "message": "hrpyc server object cannot be stopped; restart Houdini to clear this listener.",
            }

        close()
        _hrpyc_server = None

        logger.info("Stopped hrpyc server")
        return {
            "status": "success",
            "message": "hrpyc server stopped",
        }

    except Exception as e:
        logger.error(f"Failed to stop hrpyc server: {e}")
        return {
            "status": "error",
            "message": f"Failed to stop hrpyc server: {e}",
        }


def is_hrpyc_running() -> bool:
    """Check if hrpyc server is running.

    Returns:
        True if running, False otherwise
    """
    return _hrpyc_server is not None


def get_hrpyc_status() -> dict:
    """Get hrpyc server status.

    Returns:
        Dict with status information
    """
    if not is_hrpyc_running():
        return {
            "running": False,
            "message": "hrpyc server is not running. Use start_hrpyc_server() to enable remote connections.",
        }

    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    return {
        "running": True,
        "host": _hrpyc_host,
        "port": _hrpyc_port,
        "local_ip": local_ip,
        "connection_string": f"HOUDINI_HOST={_hrpyc_host} HOUDINI_PORT={_hrpyc_port}",
        "message": "hrpyc server is running and accepting remote connections.",
    }
