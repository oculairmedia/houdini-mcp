"""Allow running as: python -m houdini_mcp"""

import os
from .server import run_server

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "3055"))
    transport = os.getenv("MCP_TRANSPORT", "http")
    run_server(transport=transport, port=port)
