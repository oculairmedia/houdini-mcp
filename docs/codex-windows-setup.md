# Codex Desktop on Windows

This note documents a working Windows setup for using Houdini MCP from Codex Desktop with a live Houdini 21.0 session.

## Tested Environment

- Windows 11
- Houdini 21.0.671
- Codex Desktop
- Python 3.14 for the external MCP stdio process
- Houdini `hrpyc` remote listener on `127.0.0.1:18811`

## Recommended Architecture

Run the MCP server outside Houdini with normal Python, and let it connect to Houdini through `hrpyc`.

Do not run the FastMCP stdio server under `hython`. Houdini's `haio` event loop can break FastMCP tool listing with `NotImplementedError` from `get_task_factory`.

```text
Codex Desktop
  -> stdio MCP server running in normal Python
    -> RPyC 5.x client
      -> Houdini hrpyc listener on 127.0.0.1:18811
```

## Python Dependencies

Install the server dependencies into the normal Python used by Codex:

```powershell
python -m pip install --user fastmcp rpyc==5.3.1
```

`rpyc` must stay on the 5.x line because Houdini's bundled `hrpyc` is not compatible with RPyC 6.x.

## Houdini Setup

Install the Houdini plugin package into the user Houdini preferences directory:

```text
%USERPROFILE%\Documents\houdini21.0\python\houdini_mcp_plugin
%USERPROFILE%\Documents\houdini21.0\toolbar\houdini_mcp.shelf
%USERPROFILE%\Documents\houdini21.0\packages\houdini_mcp.json
```

Example package file:

```json
{
  "enable": true,
  "env": [
    {
      "PYTHONPATH": [
        {
          "value": "C:/Users/<user>/Documents/houdini21.0/python",
          "method": "prepend"
        }
      ]
    },
    {
      "HOUDINI_TOOLBAR_PATH": [
        {
          "value": "C:/Users/<user>/Documents/houdini21.0/toolbar",
          "method": "prepend"
        }
      ]
    }
  ]
}
```

Restart Houdini, open the Houdini MCP shelf, and click **Start Remote**. Use port `18811`.

## Codex Config

Create a small launcher script, for example `run_houdini_mcp.py`:

```python
import os
import sys

REPO = r"C:\Users\<user>\Documents\Codex\tools\houdini-mcp"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ["MCP_TRANSPORT"] = "stdio"
os.environ.setdefault("HOUDINI_HOST", "127.0.0.1")
os.environ.setdefault("HOUDINI_PORT", "18811")

from houdini_mcp.server import run_server

run_server(transport="stdio")
```

Add the server to `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers.houdini]
command = 'C:\Users\<user>\AppData\Local\Programs\Python\Python314\python.exe'
args = ['C:\Users\<user>\Documents\Codex\run_houdini_mcp.py']
```

Restart Codex Desktop after editing the config.

## Validation

Verify that the stdio server exposes tools:

```powershell
@'
import asyncio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

async def main():
    transport = StdioTransport(
        command=r"C:\Users\<user>\AppData\Local\Programs\Python\Python314\python.exe",
        args=[r"C:\path\to\run_houdini_mcp.py"],
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        print(len(tools))
        print([tool.name for tool in tools[:8]])

asyncio.run(main())
'@ | python -
```

Expected result: the server lists Houdini tools, including `get_scene_info`, `create_node`, `execute_code`, and `ping_houdini`.

From Codex, `ping_houdini`, `check_connection`, and `get_scene_info` should succeed after the Houdini shelf's **Start Remote** command is running.

## Troubleshooting

- If `ping_houdini` succeeds but `get_scene_info` times out, close any modal dialogs in Houdini and try again.
- If direct RPyC connections hang, prefer testing through MCP first. A stale test client can leave an established socket open.
- If the Houdini shelf reports that `hrpyc.stop_server` is missing, update the plugin. Houdini's `hrpyc` exposes `ThreadedServer`, not a module-level `stop_server()`.
- If FastMCP prints a banner over stdio, disable it with `show_banner=False`; MCP stdio stdout must stay JSON-RPC only.
