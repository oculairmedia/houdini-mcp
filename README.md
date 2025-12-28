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

For production use or when Houdini runs on a different machine, use the Docker-based remote mode. This requires starting the hrpyc server in Houdini.

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

## SOP Workflow Tools

The Houdini MCP Server provides specialized tools for building and manipulating SOP (Surface Operator) networks:

### Network Discovery & Inspection

| Tool | Description | Use Case |
|------|-------------|----------|
| `list_children` | List child nodes with connection details | Discover existing network topology |
| `find_nodes` | Find nodes by name pattern or type | Locate specific nodes in large networks |
| `get_node_info` | Get node details, parameters, and connections | Inspect node state and wiring |
| `get_parameter_schema` | Get parameter metadata (types, ranges, menus) | Understand what parameters are available |
| `get_geo_summary` | Get geometry statistics and metadata | Verify results after operations |

### Network Construction & Modification

| Tool | Description | Use Case |
|------|-------------|----------|
| `create_node` | Create a new node | Build networks from scratch |
| `connect_nodes` | Wire nodes together | Create data flow connections |
| `disconnect_node_input` | Break a connection | Rewire existing networks |
| `set_node_flags` | Set display/render/bypass flags | Control node visibility and evaluation |
| `reorder_inputs` | Reorder node inputs | Reorganize merge node inputs |

### Parameter Management

| Tool | Description | Use Case |
|------|-------------|----------|
| `set_parameter` | Set a parameter value | Configure node behavior |
| `get_parameter_schema` | Discover parameter metadata | Understand parameter types and constraints |

### Scene Management

| Tool | Description |
|------|-------------|
| `check_connection` | Verify/establish Houdini connection |
| `get_scene_info` | Get current scene info (file, version, nodes) |
| `delete_node` | Delete a node by path |
| `execute_code` | Execute arbitrary Python with `hou` available |
| `save_scene` | Save current scene |
| `load_scene` | Load a .hip file |
| `new_scene` | Create empty scene |
| `serialize_scene` | Serialize scene structure for diffs |

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

## Tool Reference

### Quick Reference Table

| Category | Tool | Key Parameters | Returns | Notes |
|----------|------|----------------|---------|-------|
| **Discovery** | `list_children` | `node_path`, `recursive` | Children with input/output connections | Essential for understanding network topology |
| | `find_nodes` | `root_path`, `pattern`, `node_type` | Matching nodes | Supports glob patterns and type filtering |
| | `get_node_info` | `node_path`, `include_input_details`, `include_errors` | Node metadata, connections, cook state | Use `include_errors=True` for debugging |
| | `get_parameter_schema` | `node_path`, `parm_name` | Parameter metadata (type, range, menu) | Critical for intelligent parameter setting |
| | `get_geo_summary` | `node_path`, `max_sample_points`, `include_attributes` | Geometry stats, bbox, attributes | Verify results after operations |
| **Construction** | `create_node` | `node_type`, `parent_path`, `name` | Created node path | Start of any workflow |
| | `connect_nodes` | `src_path`, `dst_path`, `dst_input_index` | Connection result | Validates node category compatibility |
| | `disconnect_node_input` | `node_path`, `input_index` | Disconnection result | Returns previous source for rewiring |
| | `set_node_flags` | `node_path`, `display`, `render`, `bypass` | Flags set | Only sets non-None flags |
| | `reorder_inputs` | `node_path`, `new_order` | Reordering result | Useful for merge nodes |
| **Parameters** | `set_parameter` | `node_path`, `param_name`, `value` | Set result | Handles both scalar and vector params |
| | `get_parameter_schema` | `node_path`, `parm_name`, `max_parms` | Parameter metadata | Discovers types, ranges, menus, defaults |
| **Verification** | `get_geo_summary` | `node_path`, `max_sample_points` | Point/prim counts, bbox, attributes | Comprehensive geometry verification |
| | `get_node_info` | `node_path`, `include_errors=True` | Cook state, errors, warnings | Error introspection |

### Tool Categories

**Network Discovery**: `list_children`, `find_nodes`, `get_node_info`, `get_parameter_schema`
- Use these to understand existing networks before making changes
- Essential for inserting nodes without breaking connections

**Network Construction**: `create_node`, `connect_nodes`, `disconnect_node_input`, `set_node_flags`, `reorder_inputs`
- Build and modify SOP networks
- All validate inputs and handle errors gracefully

**Parameter Management**: `set_parameter`, `get_parameter_schema`
- `get_parameter_schema` tells you what parameters exist and how to set them
- `set_parameter` handles both scalar and vector parameters automatically

**Verification**: `get_geo_summary`, `get_node_info` (with `include_errors=True`)
- Always verify results after operations
- Check cook state before accessing geometry
- Use geometry summary to confirm expected changes

## Credits

- Based on hrpyc integration patterns from [OpenWebUI Houdini Pipeline](https://github.com/oculairmedia/Houdinipipeline)
- Inspired by [capoomgit/houdini-mcp](https://github.com/capoomgit/houdini-mcp)

## License

MIT
