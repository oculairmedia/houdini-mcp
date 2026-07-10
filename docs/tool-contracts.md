# Tool Contracts and Common Pitfalls

This document clarifies the input/output contracts for Houdini MCP tools and documents common mistakes discovered through usage.

## execute_code

### The `hou` Module is Pre-Injected

**IMPORTANT:** The `hou` module is pre-injected as a global variable via RPyC. **Do NOT** use `import hou` or `from hou import ...` in your code.

#### ❌ Wrong:
```python
execute_code('''
import hou  # This will fail with ModuleNotFoundError
node = hou.node('/obj')
''')
```

#### ✅ Correct:
```python
execute_code('''
# hou is already available - use it directly
node = hou.node('/obj')
geo = node.createNode('geo', 'my_geo')
''')
```

### Why This Happens

The `execute_code` tool runs your code remotely in Houdini via RPyC. It injects the remote `hou` object directly into your execution namespace. The `hou` module is not installed in the Python environment where the MCP server runs, so attempting to import it will fail.

If you try to import `hou`, you'll now receive a helpful error message:

```json
{
  "status": "error",
  "message": "Code attempts to import hou module, but hou is already available",
  "hint": "The 'hou' module is pre-injected as a global variable by execute_code via RPyC. You can use 'hou' directly without importing it...",
  "suggested_fix": "# import hou  # Not needed - hou is pre-injected\n..."
}
```

## render_viewport

### Parameter Schema

The `render_viewport` tool accepts specific parameters. Do not use intuitive-but-wrong parameter names from prose descriptions.

#### ❌ Wrong Parameters:
```python
# These will raise TypeError
render_viewport(width=512, height=512)  # Use resolution=[512, 512]
render_viewport(camera_path="/obj/cam1")  # Use camera_position or camera_rotation
```

#### ✅ Correct Parameters:
```python
# Use resolution as a list
render_viewport(resolution=[512, 512])

# For camera control, use camera_position and/or camera_rotation
render_viewport(
    camera_position=[10.0, 5.0, 15.0],
    camera_rotation=[-30, 45, 0]
)

# Or use look_at to focus on a node
render_viewport(look_at="/obj/geo1")
```

### Complete Parameter List

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `camera_position` | `list[float]` (3 elements) | [x, y, z] world position | Auto-calculated |
| `camera_rotation` | `list[float]` (3 elements) | [rx, ry, rz] degrees | [-30, 45, 0] |
| `look_at` | `str` | Node path to center on | None |
| `resolution` | `list[int]` (2 elements) | [width, height] pixels | [512, 512] |
| `renderer` | `str` | "opengl" or "karma" | "opengl" |
| `output_format` | `str` | "png", "jpg", or "exr" | "png" |
| `auto_frame` | `bool` | Auto-frame visible geometry | True |
| `orthographic` | `bool` | Use orthographic projection | False |
| `karma_engine` | `str` | "cpu" or "gpu" (for Karma only) | "cpu" |

### Minimal Valid Examples

```python
# Most minimal: defaults, auto-frame everything
render_viewport()

# Explicit resolution
render_viewport(resolution=[1024, 768])

# Focus on specific node
render_viewport(look_at="/obj/geo1")

# Orthographic front view
render_viewport(camera_rotation=[0, 0, 0], orthographic=True)

# Top-down view
render_viewport(camera_rotation=[-90, 0, 0])

# Fast Karma GPU render
render_viewport(renderer="karma", karma_engine="gpu", resolution=[512, 512])
```

## render_quad_view

### Parameter Schema

Similar to `render_viewport`, but renders 4 canonical views (Front, Left, Top, Perspective) in one call.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `resolution` | `list[int]` | [width, height] for each view | [512, 512] |
| `renderer` | `str` | "opengl" or "karma" | "opengl" |
| `output_format` | `str` | "png", "jpg", or "exr" | "png" |
| `orthographic` | `bool` | Use ortho for Front/Left/Top | True |
| `include_perspective` | `bool` | Include perspective view | True |
| `karma_engine` | `str` | "cpu" or "gpu" (Karma only) | "cpu" |

### Minimal Valid Examples

```python
# Default: 4 views with orthographic projection
render_quad_view()

# Only 3 orthographic views (no perspective)
render_quad_view(include_perspective=False)

# Higher resolution with Karma
render_quad_view(resolution=[1024, 1024], renderer="karma")

# Fast GPU rendering
render_quad_view(renderer="karma", karma_engine="gpu")
```

## Schema Validation

All tool parameters are validated by Python's function signature checking. Passing unexpected keyword arguments will raise a `TypeError` immediately, before any RPC call to Houdini.

This is intentional - it catches typos and misunderstandings early, with clear error messages.

## Resolution Constraints

Both `render_viewport` and `render_quad_view` enforce resolution limits:

- **Minimum:** 64x64 pixels
- **Maximum:** 4096x4096 pixels

Attempting to render outside these bounds will return an error immediately.

## Common Patterns

### Using execute_code for Complex Operations

When other tools don't cover your use case, `execute_code` is the escape hatch. Remember:

1. `hou` is pre-injected - don't import it
2. Use `print()` for output - it will appear in `result["stdout"]`
3. Heavy geometry operations are blocked by default (use `allow_heavy_geometry=True` if needed)
4. Dangerous operations are blocked by default (use `allow_dangerous=True` if needed)

```python
result = execute_code('''
# Create a complete SOP chain
obj = hou.node('/obj')
geo = obj.createNode('geo', 'my_network')
sphere = geo.createNode('sphere')
xform = geo.createNode('xform')
xform.setFirstInput(sphere)
print(f"Created: {xform.path()}")
''')

print(result['stdout'])  # "Created: /obj/my_network/xform"
```

### Rendering the Current Scene

For quick previews, just call `render_viewport()` with defaults:

```python
# Auto-frame and render with defaults
result = render_viewport()
if result['status'] == 'success':
    image_data = result['image_base64']
    # Use the base64-encoded image
```

### Focusing on Specific Geometry

Use `look_at` to center the camera on a specific node:

```python
result = render_viewport(
    look_at="/obj/my_geo",
    orthographic=True,
    resolution=[1920, 1080]
)
```

## Testing Your Code

Before using a tool, check:

1. **Parameter names** - Use the exact names from the tool signature
2. **Parameter types** - Lists for resolution/position/rotation, not separate arguments
3. **Parameter values** - Within valid ranges (e.g., resolution 64-4096)

Python will catch incorrect parameter names immediately with a helpful `TypeError`.
