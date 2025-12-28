"""Houdini MCP Plugin - In-process MCP server for Houdini.

Provides two modes of operation:

1. **stdio mode** (free tier): MCP server runs in-process inside Houdini
   - Use start_server() / stop_server()
   - Communicates via stdio transport
   - No network configuration required

2. **remote mode** (for Docker MCP server): hrpyc listener for remote connections
   - Use start_hrpyc_server() / stop_hrpyc_server()
   - External MCP servers connect via RPyC
   - Enables advanced server-side processing
"""

__version__ = "0.1.0"

from .connection import LocalHoudiniConnection, get_connection
from .server import start_server, stop_server, is_server_running
from .remote import (
    start_hrpyc_server,
    stop_hrpyc_server,
    is_hrpyc_running,
    get_hrpyc_status,
)

__all__ = [
    # Connection
    "LocalHoudiniConnection",
    "get_connection",
    # stdio mode (MCP server in Houdini)
    "start_server",
    "stop_server",
    "is_server_running",
    # remote mode (hrpyc for external MCP server)
    "start_hrpyc_server",
    "stop_hrpyc_server",
    "is_hrpyc_running",
    "get_hrpyc_status",
]
