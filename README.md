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

- **43 MCP tools** across 15 modular categories
- **Full hou module access** - Execute any Houdini Python code remotely
- **Scene management** - Create, load, save scenes
- **Node operations** - Create, delete, modify nodes and parameters
- **Rendering** - Viewport renders, quad views, Karma GPU/CPU support
- **Pane screenshots** - Capture NetworkEditor, SceneViewer, and other panes
- **Scene serialization** - Diff scene states before/after operations
- **Connection management** - Auto-reconnect with exponential backoff + jitter
- **Error handling** - Consistent error responses with recovery hints
- **Response optimization** - Size limits, truncation, AI summarization
- **In-memory caching** - Node type cache with TTL for performance

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

### Option 1: Houdini Plugin (stdio mode)

The Houdini plugin runs the MCP server directly inside Houdini, using stdio transport. This is the simplest setup with no network configuration required.

**Installation:**

1. Copy the `houdini_plugin` folder to your Houdini packages directory:
   ```bash
   # Windows
   copy houdini_plugin %USERPROFILE%\Documents\houdini20.5\packages\houdini_mcp
   
   # Linux/Mac
   cp -r houdini_plugin ~/houdini20.5/packages/houdini_mcp
   ```

2. Copy the package JSON:
   ```bash
   # Windows
   copy houdini_plugin\houdini_mcp.json %USERPROFILE%\Documents\houdini20.5\packages\
   
   # Linux/Mac
   cp houdini_plugin/houdini_mcp.json ~/houdini20.5/packages/
   ```

3. Install FastMCP in Houdini's Python:
   ```bash
   # Windows (from Houdini's Python)
   hython -m pip install fastmcp
   
   # Or from Houdini's Python Shell
   import subprocess
   subprocess.run(["pip", "install", "fastmcp"])
   ```

4. Restart Houdini and find the "Houdini MCP" shelf

**Usage:**
- Click "Start MCP" on the shelf to start the server
- Configure your MCP client (Claude Desktop, Cursor, etc.) to use stdio transport
- Click "Stop MCP" to stop the server

**MCP Client Configuration (stdio mode):**
```json
{
  "mcpServers": {
    "houdini": {
      "command": "hython",
      "args": ["-c", "from houdini_mcp_plugin import start_server; start_server(use_thread=False)"]
    }
  }
}
```

### Option 2: Docker (Remote mode)

For production use or when Houdini runs on a different machine, use the Docker-based remote mode. This connects to Houdini via hrpyc/RPyC.

**Step 1: Start hrpyc in Houdini**

If you have the Houdini MCP plugin installed:
- Click "Start Remote" on the Houdini MCP shelf
- Note the IP and port shown in the dialog

Or manually in Houdini's Python Shell:
```python
import hrpyc
hrpyc.start_server(port=18811)
```

**Step 2: Run the Docker MCP server**

```bash
# Clone the repository
git clone https://github.com/oculairmedia/houdini-mcp.git
cd houdini-mcp

# Copy and configure environment
cp .env.example .env
# Edit .env with your Houdini host IP (from Step 1)

# Run with Docker Compose
docker compose up -d
```

**Step 3: Configure your MCP client**

```json
{
  "mcpServers": {
    "houdini": {
      "url": "http://localhost:3055"
    }
  }
}
```

**Benefits of Remote Mode:**
- Houdini can run on a different machine (e.g., render farm)
- MCP server runs in Docker for easy deployment
- Full tool set with advanced features
- Server-side processing capabilities

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

## Tool Categories (43 Tools)

The server is organized into 15 modular tool categories in `houdini_mcp/tools/`:

### Scene & Nodes (`scene.py`, `nodes.py`)
| Tool | Description |
|------|-------------|
| `get_scene_info` | Get current scene info (file, version, nodes) |
| `serialize_scene` | Serialize scene structure for diffs |
| `new_scene` | Create empty scene |
| `save_scene` | Save current scene |
| `load_scene` | Load a .hip file |
| `create_node` | Create a new node |
| `delete_node` | Delete a node by path |
| `get_node_info` | Get node details, parameters, connections, errors |
| `list_children` | List child nodes with connection details |
| `find_nodes` | Find nodes by name pattern or type |
| `list_node_types` | List available node types by category |

### Wiring & Layout (`wiring.py`, `layout.py`)
| Tool | Description |
|------|-------------|
| `connect_nodes` | Wire nodes together |
| `disconnect_node_input` | Break a connection |
| `reorder_inputs` | Reorder node inputs |
| `set_node_flags` | Set display/render/bypass flags |
| `layout_children` | Auto-layout child nodes |
| `set_node_position` | Set node position in network |
| `set_node_color` | Set node color |
| `create_network_box` | Create network box around nodes |

### Parameters (`parameters.py`)
| Tool | Description |
|------|-------------|
| `set_parameter` | Set a parameter value |
| `get_parameter_schema` | Get parameter metadata (types, ranges, menus) |

### Geometry & Materials (`geometry.py`, `materials.py`)
| Tool | Description |
|------|-------------|
| `get_geo_summary` | Get geometry statistics and metadata |
| `create_material` | Create a new material |
| `assign_material` | Assign material to geometry |
| `get_material_info` | Get material parameters and shaders |

### Rendering (`rendering.py`)
| Tool | Description |
|------|-------------|
| `render_viewport` | Render viewport with camera control |
| `render_quad_view` | Render Front/Left/Top/Perspective views |
| `list_render_nodes` | List all ROPs in /out |
| `get_render_settings` | Get ROP configuration |
| `set_render_settings` | Modify ROP settings |
| `create_render_node` | Create new ROP with settings |

### Pane Screenshots (`pane_screenshot.py`)
| Tool | Description |
|------|-------------|
| `capture_pane_screenshot` | Capture any Houdini pane as PNG |
| `list_visible_panes` | List capturable panes |
| `capture_multiple_panes` | Batch capture multiple panes |
| `render_node_network` | Navigate to node and capture network |

### Code Execution (`code.py`, `hscript.py`)
| Tool | Description |
|------|-------------|
| `execute_code` | Execute Python with `hou` available |
| `execute_hscript` | Execute HScript commands |

### Error Handling (`errors.py`)
| Tool | Description |
|------|-------------|
| `find_error_nodes` | Find all nodes with cook errors |

### Help & Summarization (`help.py`, `summarization.py`)
| Tool | Description |
|------|-------------|
| `get_houdini_help` | Get help for node types |
| `summarize_response` | AI-summarize large responses |
| `estimate_tokens` | Estimate token count |
| `get_summarization_status` | Get summarization config |

### Infrastructure (`_common.py`, `cache.py`)
- **Error handling**: `@handle_connection_errors` decorator
- **Connection retry**: Exponential backoff with jitter
- **Response size**: Thresholds, truncation, metadata
- **Caching**: Node type cache with TTL
- **Parallel execution**: `semaphore_gather`, `batch_items`

## Common Patterns

### Creating SOP Chains

Build a complete SOP network from scratch:

```python
# 1. Create geo container
geo = create_node("geo", "/obj", "my_geo")

# 2. Create SOP nodes
sphere = create_node("sphere", geo["node_path"], "sphere1")
xform = create_node("xform", geo["node_path"], "xform1")
color = create_node("color", geo["node_path"], "color1")
out = create_node("null", geo["node_path"], "OUT")

# 3. Wire nodes together
connect_nodes(sphere["node_path"], xform["node_path"])
connect_nodes(xform["node_path"], color["node_path"])
connect_nodes(color["node_path"], out["node_path"])

# 4. Set display flag
set_node_flags(out["node_path"], display=True, render=True)
```

### Inserting Nodes Into Existing Chains

Insert a new node between existing connections:

```python
# 1. Discover existing network
children = list_children("/obj/geo1")
# Find grid and noise nodes from children

# 2. Get current connections
noise_info = get_node_info("/obj/geo1/noise1", include_input_details=True)
# See that noise is connected to grid

# 3. Create new node
mountain = create_node("mountain", "/obj/geo1", "mountain1")

# 4. Rewire: grid → mountain → noise
disconnect_node_input("/obj/geo1/noise1", 0)  # Break noise ← grid
connect_nodes("/obj/geo1/grid1", "/obj/geo1/mountain1")  # grid → mountain
connect_nodes("/obj/geo1/mountain1", "/obj/geo1/noise1")  # mountain → noise
```

### Setting Parameters Intelligently

Use parameter schema to set values correctly:

```python
# 1. Discover parameter metadata
schema = get_parameter_schema("/obj/geo1/sphere1", parm_name="rad")
param = schema["parameters"][0]

# 2. Check parameter type
if param["type"] == "vector":
    # Set vector parameter correctly
    set_parameter("/obj/geo1/sphere1", "rad", [3.0, 3.0, 3.0])
elif param["type"] == "menu":
    # Use menu items
    first_option = param["menu_items"][0]["value"]
    set_parameter("/obj/geo1/sphere1", "type", first_option)
```

### Verifying Results

Always verify geometry after operations:

```python
# Get comprehensive geometry summary
summary = get_geo_summary(
    "/obj/geo1/OUT",
    max_sample_points=10,
    include_attributes=True
)

# Check cook state
if summary["cook_state"] != "cooked":
    # Handle errors
    node_info = get_node_info("/obj/geo1/OUT", include_errors=True)
    errors = node_info["cook_info"]["errors"]
    # Fix errors...

# Verify geometry metrics
assert summary["point_count"] > 0
assert summary["primitive_count"] > 0

# Check bounding box
bbox = summary["bounding_box"]
# Verify expected size/position
```

## Error Handling Best Practices

### Check Cook State Before Reading Geometry

```python
# 1. Check cook state first
node_info = get_node_info(
    node_path,
    include_errors=True,
    force_cook=True
)

cook_state = node_info["cook_info"]["cook_state"]

# 2. Handle different states
if cook_state == "error":
    # Examine errors
    errors = node_info["cook_info"]["errors"]
    for err in errors:
        print(f"Error: {err['message']}")
    # Fix errors...
elif cook_state == "cooked":
    # Safe to access geometry
    geo = get_geo_summary(node_path)
```

### Validate Parameter Types

```python
# Always check parameter schema before setting
schema = get_parameter_schema(node_path, parm_name="rad")
param = schema["parameters"][0]

if param["type"] == "vector":
    # Use list/tuple for vector parameters
    set_parameter(node_path, "rad", [5.0, 5.0, 5.0])
else:
    # Use scalar for single parameters
    set_parameter(node_path, "rad", 5.0)
```

### Handle Connection Errors

```python
# Connection validation
result = connect_nodes(src_path, dst_path)

if result["status"] == "error":
    if "incompatible" in result["message"].lower():
        # Different node categories (e.g., SOP vs OBJ)
        print("Can't connect nodes of different types")
    elif "not found" in result["message"].lower():
        # Node doesn't exist
        print("Source or destination node not found")
```

### Debugging with Error Introspection

```python
# Use include_errors=True to diagnose issues
node_info = get_node_info(
    node_path,
    include_errors=True,
    force_cook=True
)

cook_info = node_info["cook_info"]

# Check for errors
if cook_info["errors"]:
    print(f"Node has {len(cook_info['errors'])} errors:")
    for error in cook_info["errors"]:
        print(f"  - {error['message']}")

# Check for warnings
if cook_info["warnings"]:
    print(f"Node has {len(cook_info['warnings'])} warnings:")
    for warning in cook_info["warnings"]:
        print(f"  - {warning['message']}")
```

## Example Workflows

Complete working examples are available in the `examples/` directory:

- **`build_from_scratch.py`** - Build sphere → xform → color → OUT from scratch
- **`augment_existing_scene.py`** - Insert mountain between grid → noise
- **`parameter_workflow.py`** - Discover → set → verify parameters
- **`error_handling.py`** - Detect → fix → verify errors

Run examples:

```bash
cd examples
python build_from_scratch.py
python augment_existing_scene.py
python parameter_workflow.py
python error_handling.py
```

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

- "Create a sphere → transform → color → OUT network"
- "Insert a mountain node between the grid and noise"
- "Discover what parameters are available on the sphere node"
- "Check if the noise node has any cook errors"
- "Set the sphere radius to 3.0 using the parameter schema"

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

## Project Structure

```
houdini_mcp/
├── server.py              # FastMCP server with 43 tool wrappers
├── connection.py          # RPyC connection with retry/backoff
└── tools/                 # Modular tool implementations
    ├── _common.py         # Shared utilities, error handling
    ├── cache.py           # Node type caching with TTL
    ├── code.py            # Python/HScript execution
    ├── errors.py          # Error node detection
    ├── geometry.py        # Geometry introspection
    ├── help.py            # Houdini help access
    ├── hscript.py         # HScript command execution
    ├── layout.py          # Node layout tools
    ├── materials.py       # Material creation/assignment
    ├── nodes.py           # Node CRUD operations
    ├── pane_screenshot.py # Pane capture tools
    ├── parameters.py      # Parameter get/set
    ├── rendering.py       # Viewport/Karma rendering
    ├── scene.py           # Scene management
    ├── summarization.py   # AI response summarization
    └── wiring.py          # Node connection tools

houdini_plugin/            # Houdini plugin for stdio mode
├── python/houdini_mcp_plugin/
├── toolbar/               # Shelf tools
└── houdini_mcp.json       # Package descriptor

tests/                     # 418 tests (406 passing)
docs/                      # Implementation documentation
examples/                  # Working example scripts
```

## Credits

- Based on hrpyc integration patterns from [OpenWebUI Houdini Pipeline](https://github.com/oculairmedia/Houdinipipeline)
- Inspired by [capoomgit/houdini-mcp](https://github.com/capoomgit/houdini-mcp)

## License

MIT
