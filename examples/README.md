# Houdini MCP Server - Example Workflows

This directory contains comprehensive examples demonstrating how to use the Houdini MCP Server for common SOP workflow patterns.

## Prerequisites

1. Houdini running with hrpyc server (port 18811)
2. Houdini MCP Server running (port 3055)
3. Python 3.8+ with `requests` library

## Examples

### 1. Build from Scratch (`build_from_scratch.py`)

**Demonstrates**: Building a complete SOP network from nothing

**Network**: sphere → xform → color → OUT

**Key Concepts**:
- Creating geo container at /obj
- Creating SOP nodes sequentially
- Wiring nodes together in order
- Setting parameters on each node
- Setting display flags
- Verifying with `get_geo_summary`

**Run**:
```bash
python build_from_scratch.py
```

**Expected Output**:
- Creates `/obj/example_geo` with 4 SOP nodes
- Final display shows red sphere translated up by 3.0 units
- Geometry summary confirms point count, bounding box, and attributes

---

### 2. Augment Existing Scene (`augment_existing_scene.py`)

**Demonstrates**: Inserting a node into an existing network

**Initial Network**: grid → noise  
**Final Network**: grid → mountain → noise

**Key Concepts**:
- Using `list_children` to discover network topology
- Using `get_node_info` to inspect current connections
- Creating new node
- Disconnecting and rewiring connections
- Verifying geometry changed with before/after comparison

**Run**:
```bash
python augment_existing_scene.py
```

**Expected Output**:
- Creates initial grid → noise network
- Successfully inserts mountain node in between
- Geometry summary shows increased Y-size due to mountain effect
- Network structure verified with `list_children`

---

### 3. Parameter Workflow (`parameter_workflow.py`)

**Demonstrates**: Intelligent parameter discovery and setting

**Workflow**: Discover → Set → Verify

**Key Concepts**:
- Using `get_parameter_schema` to discover ALL parameters
- Querying SPECIFIC parameter metadata
- Understanding parameter types (float, vector, menu, toggle)
- Setting parameters based on schema information
- Verifying parameters with `get_node_info`
- Confirming geometry reflects parameter changes

**Run**:
```bash
python parameter_workflow.py
```

**Expected Output**:
- Displays comprehensive parameter schema for sphere node
- Shows parameter types, defaults, ranges, and menu items
- Sets multiple parameter types correctly
- Verifies all parameters set successfully
- Geometry summary confirms changes

---

### 4. Error Handling (`error_handling.py`)

**Demonstrates**: Robust error detection and recovery

**Scenarios**:
1. Missing input connection (noise without input)
2. Invalid parameter type (scalar instead of vector)
3. Incompatible node connection (SOP to OBJ)
4. Safe geometry access pattern

**Key Concepts**:
- Using `get_node_info(include_errors=True)` for error detection
- Checking cook state before accessing geometry
- Validating parameter types with schema
- Handling connection validation errors
- Error introspection to guide fixes

**Run**:
```bash
python error_handling.py
```

**Expected Output**:
- Demonstrates 4 error scenarios
- Shows error detection with `cook_info`
- Shows how to fix each error type
- Verifies fixes with cook state checking

---

## Common Patterns Demonstrated

### Pattern 1: Build from Scratch
```python
# Create parent
geo = create_node("geo", "/obj", "my_geo")

# Create children
node1 = create_node("sphere", geo["node_path"])
node2 = create_node("xform", geo["node_path"])

# Wire
connect_nodes(node1["node_path"], node2["node_path"])

# Set params
set_parameter(node1["node_path"], "rad", [2.0, 2.0, 2.0])

# Verify
summary = get_geo_summary(node2["node_path"])
```

### Pattern 2: Insert into Existing Network
```python
# Discover
children = list_children("/obj/geo1")
noise_info = get_node_info("/obj/geo1/noise1", include_input_details=True)

# Create
mountain = create_node("mountain", "/obj/geo1")

# Rewire
disconnect_node_input("/obj/geo1/noise1", 0)
connect_nodes("/obj/geo1/grid1", mountain["node_path"])
connect_nodes(mountain["node_path"], "/obj/geo1/noise1")
```

### Pattern 3: Safe Parameter Setting
```python
# Discover schema
schema = get_parameter_schema(node_path, parm_name="rad")
param = schema["parameters"][0]

# Set based on type
if param["type"] == "vector":
    set_parameter(node_path, "rad", [3.0, 3.0, 3.0])
elif param["type"] == "menu":
    set_parameter(node_path, "type", param["menu_items"][0]["value"])
```

### Pattern 4: Safe Geometry Access
```python
# Check cook state first
node_info = get_node_info(node_path, include_errors=True, force_cook=True)
cook_state = node_info["cook_info"]["cook_state"]

# Only access if cooked
if cook_state == "cooked":
    geo = get_geo_summary(node_path)
elif cook_state == "error":
    # Handle errors
    for err in node_info["cook_info"]["errors"]:
        print(f"Error: {err['message']}")
```

## Integration Tests

The workflows demonstrated in these examples are also tested in:
- `tests/integration/test_workflow_examples.py`

Run integration tests:
```bash
pytest tests/integration/test_workflow_examples.py -v
```

## Tips for Using These Examples

1. **Start with `build_from_scratch.py`** - Simplest example, demonstrates core concepts

2. **Study `augment_existing_scene.py`** - Most common real-world scenario (modifying existing networks)

3. **Master `parameter_workflow.py`** - Essential for intelligent parameter handling

4. **Review `error_handling.py`** - Critical for robust production code

5. **Combine patterns** - Real workflows often need multiple patterns:
   - Discover existing network (`list_children`)
   - Insert new node (`create_node`)
   - Discover parameter schema (`get_parameter_schema`)
   - Set parameters intelligently (`set_parameter`)
   - Verify results (`get_geo_summary`)
   - Check for errors (`get_node_info` with `include_errors=True`)

## Modifying Examples

All examples use `MCP_URL = "http://localhost:3055"`. If your MCP server runs on a different host/port:

```python
# Change this line in each example
MCP_URL = "http://your-host:your-port"
```

## Troubleshooting

### Connection refused
- Ensure Houdini is running with `hrpyc.start_server(port=18811)`
- Ensure MCP server is running: `python -m houdini_mcp`

### Examples fail with errors
- Check that Houdini hrpyc server is accessible
- Verify MCP server logs for connection issues
- Ensure no conflicting node names from previous runs (use unique names or clear scene)

### Geometry verification fails
- Cook state might be "dirty" - examples force cook where needed
- Some operations may need additional time for Houdini to update
- Check Houdini session for actual node state

## Next Steps

After running these examples:

1. Study the integration tests to see how to test workflows
2. Review the main README for full tool reference
3. Check HDMCP implementation documents for advanced patterns
4. Build your own workflows combining these patterns

## Questions?

See the main README.md or open an issue on GitHub.
