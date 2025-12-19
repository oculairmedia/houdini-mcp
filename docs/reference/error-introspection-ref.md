# HDMCP-8 Quick Reference: Node Error Introspection

## Overview
Extended `get_node_info()` to optionally include cook state and error/warning information.

## Usage

### Basic (Backward Compatible)
```python
# Default - no error info
info = get_node_info("/obj/geo1/sphere1")
# Returns: standard node info (no cook_info)
```

### With Error Checking
```python
# Include cook state and errors
info = get_node_info("/obj/geo1/sphere1", include_errors=True)

# Access cook info
print(info["cook_info"]["cook_state"])  # "cooked", "error", "dirty", "uncooked"
print(info["cook_info"]["errors"])       # List of error dicts
print(info["cook_info"]["warnings"])     # List of warning dicts
```

### Force Cook First
```python
# Cook node before checking errors
info = get_node_info(
    "/obj/geo1/sphere1", 
    include_errors=True,
    force_cook=True
)
# Returns: fresh cook info with last_cook_time
```

## Return Format

### Without `include_errors` (default)
```json
{
  "status": "success",
  "path": "/obj/geo1/sphere1",
  "type": "sphere",
  "name": "sphere1",
  "children": [],
  "inputs": [],
  "outputs": []
}
```

### With `include_errors=True`
```json
{
  "status": "success",
  "path": "/obj/geo1/sphere1",
  "type": "sphere",
  "cook_info": {
    "cook_state": "error",
    "errors": [
      {
        "severity": "error",
        "message": "Invalid parameter value",
        "node_path": "/obj/geo1/sphere1"
      }
    ],
    "warnings": [
      {
        "severity": "warning",
        "message": "Performance warning",
        "node_path": "/obj/geo1/sphere1"
      }
    ]
  }
}
```

### With `force_cook=True`
```json
{
  "cook_info": {
    "cook_state": "cooked",
    "errors": [],
    "warnings": [],
    "last_cook_time": 1234567890.123
  }
}
```

## Cook States

| State | Meaning |
|-------|---------|
| `"cooked"` | Node successfully cooked |
| `"error"` | Cook failed with errors |
| `"dirty"` | Needs to be recooked |
| `"uncooked"` | Never been cooked |

## Common Patterns

### Check for Errors
```python
info = get_node_info(node_path, include_errors=True)
if info["cook_info"]["cook_state"] == "error":
    for err in info["cook_info"]["errors"]:
        print(f"Error: {err['message']}")
```

### Check for Warnings
```python
info = get_node_info(node_path, include_errors=True)
for warn in info["cook_info"]["warnings"]:
    print(f"Warning: {warn['message']}")
```

### Force Fresh Cook
```python
# Cook and immediately check for errors
info = get_node_info(
    node_path,
    include_errors=True,
    force_cook=True
)
```

### Combined with Parameters
```python
# Get params AND cook info
info = get_node_info(
    node_path,
    include_params=True,
    include_errors=True
)
# Returns both parameters and cook_info
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node_path` | str | Required | Full path to node |
| `include_params` | bool | True | Include parameter values |
| `include_input_details` | bool | True | Include input connections |
| `include_errors` | bool | False | Include cook state/errors |
| `force_cook` | bool | False | Cook before checking errors |

## Edge Cases

- **Empty errors/warnings**: Returns `[]` not `null`
- **Node not found**: Returns `{"status": "error", ...}`
- **force_cook without include_errors**: Silently ignored
- **Unknown cook state**: Falls back to lowercase string
- **Special characters**: Preserved in error messages

## Test Coverage

- ✓ 15 new tests for error introspection
- ✓ 24 total get_node_info tests (all passing)
- ✓ 98 total tests in test suite
- ✓ 100% backward compatibility

## Files Modified

- `houdini_mcp/tools.py` - Core implementation
- `houdini_mcp/server.py` - MCP tool exposure
- `tests/conftest.py` - Mock support
- `tests/test_node_errors.py` - New tests

## Demo

Run the demo script:
```bash
python3 hdmcp8_demo.py
```
