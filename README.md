# Houdini MCP Server

An MCP (Model Context Protocol) server for controlling SideFX Houdini via `hrpyc`, enabling AI assistants like Claude, Cursor, and Letta agents to interact with Houdini sessions.

## Architecture

```
+-----------------+      MCP (HTTP)       +------------------+      hrpyc:18811      +-------------+
|  Claude/Cursor  | <------------------> |   MCP Server     | <------------------> |   Houdini   |
|  Letta Agents   |                      |  (Python/FastMCP)|                      |   Session   |
+-----------------+                      +------------------+                      +-------------+
```

## Features

- **Full hou module access** - Execute any Houdini Python code remotely
- **Scene management** - Create, load, save scenes
- **Node operations** - Create, delete, modify nodes and parameters
- **Scene serialization** - Diff scene states before/after operations
- **Connection management** - Auto-reconnect on connection loss

## Prerequisites

1. **Houdini with RPC enabled** - Start Houdini's RPC server:
   - In Houdini: `Windows > Python Shell`, then run:
     ```python
     import hrpyc
     hrpyc.start_server(port=18811)
     ```
   - Or add to your `123.py` startup script for automatic startup

2. **Network access** - The MCP server must be able to reach Houdini's RPC port (default: 18811)

## Installation

### Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/oculairmedia/houdini-mcp.git
cd houdini-mcp

# Copy and configure environment
cp .env.example .env
# Edit .env with your Houdini host IP

# Run with Docker Compose
docker compose up -d
```

### Local Development

```bash
# Clone and install
git clone https://github.com/oculairmedia/houdini-mcp.git
cd houdini-mcp
pip install -r requirements.txt

# Run
HOUDINI_HOST=192.168.50.90 python -m houdini_mcp
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOUDINI_HOST` | `localhost` | Houdini machine IP/hostname |
| `HOUDINI_PORT` | `18811` | hrpyc server port |
| `MCP_PORT` | `3055` | MCP server HTTP port |
| `MCP_TRANSPORT` | `http` | Transport type (http, stdio, sse) |
| `LOG_LEVEL` | `INFO` | Logging level |

## MCP Tools

| Tool | Description |
|------|-------------|
| `check_connection` | Verify/establish Houdini connection |
| `get_scene_info` | Get current scene info (file, version, nodes) |
| `create_node` | Create a node (type, parent, name) |
| `delete_node` | Delete a node by path |
| `get_node_info` | Get node details and parameters |
| `set_parameter` | Set a parameter value |
| `execute_code` | Execute arbitrary Python with `hou` available |
| `save_scene` | Save current scene |
| `load_scene` | Load a .hip file |
| `new_scene` | Create empty scene |
| `serialize_scene` | Serialize scene structure for diffs |

## Usage Examples

### With Claude/Cursor

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "houdini": {
      "url": "http://localhost:3055"
    }
  }
}
```

### With Letta

Add as an MCP server in Letta's configuration to give agents Houdini control.

### Example Prompts

- "Create a sphere at the origin with radius 2"
- "List all nodes in /obj"
- "Set the camera's focal length to 50mm"
- "Execute this Houdini Python code: ..."

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt pytest

# Run tests
pytest tests/

# Run server locally
python -m houdini_mcp
```

## Troubleshooting

### Connection refused
- Verify Houdini is running with hrpyc server started
- Check firewall allows port 18811
- Verify HOUDINI_HOST is correct

### Authentication errors
- hrpyc uses no authentication by default
- Ensure you're on a trusted network

## Credits

- Based on hrpyc integration patterns from [OpenWebUI Houdini Pipeline](https://github.com/oculairmedia/Houdinipipeline)
- Inspired by [capoomgit/houdini-mcp](https://github.com/capoomgit/houdini-mcp)

## License

MIT
