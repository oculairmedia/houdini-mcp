# get_geo_summary - Quick Reference

## Basic Usage

```python
get_geo_summary(
    node_path: str,
    max_sample_points: int = 100,
    include_attributes: bool = True,
    include_groups: bool = True
)
```

## Common Use Cases

### 1. Verify geometry after operation
```python
# After creating a sphere
result = get_geo_summary("/obj/geo1/sphere1")
assert result["status"] == "success"
assert result["point_count"] > 0
assert result["cook_state"] == "cooked"
```

### 2. Quick point/prim count
```python
# Just get the counts
result = get_geo_summary(
    "/obj/geo1/grid1",
    max_sample_points=0,
    include_attributes=False,
    include_groups=False
)
print(f"Points: {result['point_count']}, Prims: {result['primitive_count']}")
```

### 3. Check bounding box
```python
result = get_geo_summary("/obj/geo1/box1")
bbox = result["bounding_box"]
print(f"Size: {bbox['size']}")
print(f"Center: {bbox['center']}")
```

### 4. Inspect attributes
```python
result = get_geo_summary("/obj/geo1/mountain1")
for attr in result["attributes"]["point"]:
    print(f"{attr['name']}: {attr['type']} x {attr['size']}")
```

### 5. Sample first 10 points
```python
result = get_geo_summary("/obj/geo1/noise1", max_sample_points=10)
for pt in result["sample_points"]:
    print(f"Point {pt['index']}: {pt['P']}")
```

## Return Structure

```javascript
{
  "status": "success",
  "node_path": "/obj/geo1/sphere1",
  "cook_state": "cooked",
  "point_count": 482,
  "primitive_count": 480,
  "vertex_count": 1920,
  "bounding_box": {
    "min": [-1, -1, -1],
    "max": [1, 1, 1],
    "size": [2, 2, 2],
    "center": [0, 0, 0]
  },
  "attributes": {
    "point": [{"name": "P", "type": "float", "size": 3}],
    "primitive": [],
    "vertex": [],
    "detail": []
  },
  "groups": {
    "point": ["top"],
    "primitive": ["front"]
  },
  "sample_points": [
    {"index": 0, "P": [0, 1, 0], "N": [0, 1, 0]}
  ]
}
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node_path` | str | *required* | Path to SOP node (e.g., "/obj/geo1/sphere1") |
| `max_sample_points` | int | 100 | Max points to sample (0-10000). Set to 0 to skip sampling. |
| `include_attributes` | bool | True | Include attribute metadata |
| `include_groups` | bool | True | Include group names |

## Cook States

| State | Meaning |
|-------|---------|
| `"cooked"` | Node successfully cooked, data is current |
| `"dirty"` | Node needs recooking (tool auto-cooks) |
| `"uncooked"` | Node never cooked (tool auto-cooks) |
| `"error"` | Cook failed, check node errors |
| `"unknown"` | Could not determine state |

## Error Handling

### Node not found
```python
result = get_geo_summary("/obj/geo1/nonexistent")
# {"status": "error", "message": "Node not found: /obj/geo1/nonexistent"}
```

### Not a SOP / No geometry
```python
result = get_geo_summary("/obj/cam1")
# {"status": "error", "message": "Node /obj/cam1 has no geometry..."}
```

### Empty geometry (not an error!)
```python
result = get_geo_summary("/obj/geo1/empty")
# {
#   "status": "success",
#   "point_count": 0,
#   "primitive_count": 0,
#   "vertex_count": 0
# }
```

## Edge Cases

### Massive geometry (>1M points)
```python
result = get_geo_summary("/obj/geo1/huge_mesh", max_sample_points=100)
# {
#   "status": "success",
#   "point_count": 1500000,
#   "warning": "Geometry has 1500000 points (>1M). Sampling limited to 100 points.",
#   "sample_points": [...100 points...]
# }
```

### Uncooked geometry
```python
# Tool automatically cooks before reading
result = get_geo_summary("/obj/geo1/dirty_node")
# cook_state will be "cooked" after auto-cook succeeds
```

### No bounding box
```python
result = get_geo_summary("/obj/geo1/points_only")
# {"bounding_box": null}
```

## Optimization Tips

1. **Skip sampling for counts only**: Set `max_sample_points=0`
2. **Skip metadata**: Set `include_attributes=False, include_groups=False`
3. **Limit samples**: Use lower `max_sample_points` for large geometry
4. **Batch checks**: Call once and cache result for multiple checks

## FastMCP Tool Invocation

Via MCP protocol:
```json
{
  "name": "get_geo_summary",
  "arguments": {
    "node_path": "/obj/geo1/sphere1",
    "max_sample_points": 50,
    "include_attributes": true,
    "include_groups": true
  }
}
```
