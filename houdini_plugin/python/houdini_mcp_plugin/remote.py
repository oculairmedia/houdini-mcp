"""Remote mode for Houdini MCP Plugin.

This module provides hrpyc server activation, allowing external MCP servers
to connect to Houdini via RPyC for remote control.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger("houdini_mcp_plugin.remote")

# Global state for remote mode
_hrpyc_server: Optional[Any] = None
_hrpyc_port: int = 18811


def start_hrpyc_server(port: int = 18811) -> dict:
    """Start the hrpyc server to allow remote connections.

    This enables external MCP servers (like the Docker-based server) to
    connect to this Houdini instance and execute commands.

    Args:
        port: Port to listen on (default: 18811)

    Returns:
        Dict with status and connection info
    """
    global _hrpyc_server, _hrpyc_port

    if _hrpyc_server is not None:
        return {
            "status": "already_running",
            "port": _hrpyc_port,
            "message": f"hrpyc server is already running on port {_hrpyc_port}",
        }

    try:
        import hrpyc

        # Start the hrpyc server
        _hrpyc_server = hrpyc.start_server(port=port)
        _hrpyc_port = port

        logger.info(f"Started hrpyc server on port {port}")

        # Get local IP for connection info
        import socket

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
            "port": port,
            "local_ip": local_ip,
            "message": f"hrpyc server started. Connect with: HOUDINI_HOST={local_ip} HOUDINI_PORT={port}",
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
        import hrpyc

        # hrpyc.stop_server() stops the server
        hrpyc.stop_server()
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
        "port": _hrpyc_port,
        "local_ip": local_ip,
        "connection_string": f"HOUDINI_HOST={local_ip} HOUDINI_PORT={_hrpyc_port}",
        "message": "hrpyc server is running and accepting remote connections.",
    }
