"""Houdini MCP Plugin - In-process MCP server for Houdini."""

__version__ = "0.1.0"

from .connection import LocalHoudiniConnection, get_connection
from .server import start_server, stop_server, is_server_running

__all__ = [
    "LocalHoudiniConnection",
    "get_connection",
    "start_server",
    "stop_server",
    "is_server_running",
]
