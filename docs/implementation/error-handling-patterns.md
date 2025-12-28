# Error Handling Patterns in Houdini MCP

## Overview

This document describes the error handling patterns used throughout the Houdini MCP codebase. These patterns ensure consistent, graceful error handling across all 43+ MCP tools.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         MCP Tool                                │
│  @mcp.tool()                                                    │
│  def some_tool(...):                                            │
│      return tools.some_tool(...)                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Tool Implementation                          │
│  @handle_connection_errors("some_tool")  ◄── Decorator          │
│  def some_tool(...):                                            │
│      hou = ensure_connected(host, port)  ◄── Connection         │
│      # ... actual logic (no try/except needed)                  │
│      return {"status": "success", ...}                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Connection Layer                             │
│  connection.py                                                  │
│  - retry_with_backoff() decorator                               │
│  - connect() with exponential backoff + jitter                  │
│  - ensure_connected() for auto-reconnection                     │
│  - safe_execute() for timeout protection                        │
└─────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. `@handle_connection_errors` Decorator

**Location:** `houdini_mcp/tools/_common.py:82-124`

The primary error handling mechanism. Wraps tool functions with a three-tier error pattern:

```python
@handle_connection_errors("get_scene_info")
def get_scene_info(host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
    hou = ensure_connected(host, port)
    # ... actual logic without try/except boilerplate
    return {"status": "success", ...}
```

**Error Tiers:**

| Tier | Exception Type | Handling |
|------|---------------|----------|
| 1 | `HoudiniConnectionError` | Simple error response with message |
| 2 | `CONNECTION_ERRORS` tuple | Graceful recovery via `_handle_connection_error()` |
| 3 | Generic `Exception` | Log + error response with traceback |

### 2. `CONNECTION_ERRORS` Tuple

**Location:** `houdini_mcp/tools/_common.py:129-137`

Exceptions that indicate broken/timed-out connections:

```python
CONNECTION_ERRORS = (
    EOFError,              # Connection closed unexpectedly
    BrokenPipeError,       # Pipe broken
    ConnectionResetError,  # Connection reset by peer
    ConnectionRefusedError,# Connection refused
    ConnectionAbortedError,# Connection aborted
    TimeoutError,          # Operation timed out
    OSError,               # Various OS-level connection errors
)
```

### 3. `_handle_connection_error()` Function

**Location:** `houdini_mcp/tools/_common.py:140-194`

Handles connection errors gracefully:

1. Cleans up the broken connection (calls `disconnect()`)
2. Logs the error
3. Returns a user-friendly error response with context

**Response Format:**
```python
{
    "status": "error",
    "error_type": "connection_error",
    "exception": "TimeoutError",  # Exception class name
    "message": "Operation 'get_scene_info' timed out...",
    "operation": "get_scene_info",
    "recoverable": True,  # Indicates retry is possible
}
```

**Context-Specific Messages:**

| Exception | Message Focus |
|-----------|--------------|
| `TimeoutError` | Houdini may be busy with heavy computation |
| `EOFError` | Houdini may have crashed or RPC server stopped |
| `BrokenPipeError` | Connection was lost |
| Other | Generic connection error |

### 4. Connection Layer Error Handling

**Location:** `houdini_mcp/connection.py`

#### Retry with Exponential Backoff

```python
@retry_with_backoff(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,  # Prevents thundering herd
    retryable_exceptions=RETRYABLE_EXCEPTIONS
)
def connect_to_houdini():
    ...
```

**Key Parameters:**
- `max_retries=3` - Three attempts before failing
- `base_delay=1.0` - Start with 1 second delay
- `max_delay=30.0` - Cap delay at 30 seconds
- `jitter=True` - Add up to 10% random delay to prevent thundering herd

#### `ensure_connected()` Function

Auto-reconnects when connection is lost:

```python
def ensure_connected(host: str, port: int) -> Any:
    if not is_connected():
        logger.info("Connection lost or not established, reconnecting...")
        connect(host, port)
    return _hou
```

#### `safe_execute()` Function

Wraps RPC operations with timeout protection:

```python
result = safe_execute(
    func,
    *args,
    timeout=DEFAULT_OPERATION_TIMEOUT,  # 45 seconds
    operation_name="heavy_operation",
    **kwargs
)

if not result.success:
    if result.timed_out:
        # Handle timeout
    elif result.connection_lost:
        # Handle connection loss
```

## Standard Response Format

All tools return consistent response dictionaries:

### Success Response
```python
{
    "status": "success",
    # ... operation-specific data
}
```

### Error Response
```python
{
    "status": "error",
    "message": "Human-readable error description",
    # Optional fields:
    "error_type": "connection_error" | "validation_error" | ...,
    "exception": "ExceptionClassName",
    "operation": "tool_name",
    "recoverable": True | False,
    "traceback": "...",  # Only for unexpected errors
}
```

## Validation Helpers

### `validate_resolution()`

**Location:** `houdini_mcp/tools/_common.py:202-230`

Validates render resolution dimensions:

```python
def render_viewport(resolution: Optional[List[int]] = None, ...):
    if resolution is None:
        resolution = [512, 512]
    
    # Returns error dict if invalid, None if valid
    if error := validate_resolution(resolution):
        return error
    
    # Continue with valid resolution...
```

## Usage Patterns

### Pattern 1: Simple Tool with Decorator

```python
@handle_connection_errors("list_children")
def list_children(
    node_path: str,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    hou = ensure_connected(host, port)
    
    node = hou.node(node_path)
    if node is None:
        return {"status": "error", "message": f"Node not found: {node_path}"}
    
    children = [child.name() for child in node.children()]
    return {"status": "success", "children": children}
```

### Pattern 2: Tool with Input Validation

```python
@handle_connection_errors("render_viewport")
def render_viewport(
    resolution: Optional[List[int]] = None,
    ...
) -> Dict[str, Any]:
    hou = ensure_connected(host, port)
    
    if resolution is None:
        resolution = [512, 512]
    
    # Validate early, return error if invalid
    if error := validate_resolution(resolution):
        return error
    
    # ... proceed with rendering
```

### Pattern 3: Tool with Multiple Error Sources

```python
@handle_connection_errors("execute_code")
def execute_code(
    code: str,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    # Check for dangerous patterns BEFORE connecting
    dangerous = _detect_dangerous_code(code)
    if dangerous:
        return {
            "status": "error",
            "message": f"Dangerous code pattern detected: {dangerous}",
        }
    
    hou = ensure_connected(host, port)
    
    try:
        exec(code, {"hou": hou})
        return {"status": "success"}
    except Exception as e:
        # Decorator handles connection errors
        # This catches code execution errors specifically
        return {
            "status": "error",
            "message": f"Code execution failed: {e}",
        }
```

## Testing Error Handling

### Mock Setup

Tests use `MockHouModule` and `MockHouNode` from `tests/conftest.py`:

```python
@pytest.fixture
def mock_connection(monkeypatch):
    mock_hou = MockHouModule()
    monkeypatch.setattr("houdini_mcp.tools._common.ensure_connected", lambda *a, **kw: mock_hou)
    return mock_hou
```

### Testing Connection Errors

```python
def test_handles_connection_timeout(self, mock_connection):
    from houdini_mcp.tools import get_scene_info
    
    # Simulate timeout
    mock_connection.node.side_effect = TimeoutError("Connection timed out")
    
    result = get_scene_info()
    
    assert result["status"] == "error"
    assert result["error_type"] == "connection_error"
    assert result["recoverable"] is True
```

### Testing Validation Errors

```python
def test_validates_resolution(self, mock_connection):
    from houdini_mcp.tools import render_viewport
    
    result = render_viewport(resolution=[10, 10])  # Too small
    
    assert result["status"] == "error"
    assert "at least 64x64" in result["message"]
```

## Best Practices

1. **Always use the decorator** - Don't write try/except for connection errors in tool functions
2. **Validate early** - Check inputs before connecting to Houdini
3. **Return dicts, don't raise** - Tools should return error dicts, not raise exceptions
4. **Include `recoverable` flag** - Help clients know if they can retry
5. **Log at appropriate levels** - Use `logger.error()` for unexpected errors, `logger.warning()` for recoverable ones
6. **Clean up connections** - The decorator handles this, but be aware of the pattern

## Files Reference

| File | Purpose |
|------|---------|
| `houdini_mcp/tools/_common.py` | Core error handling utilities |
| `houdini_mcp/connection.py` | Connection management with retry logic |
| `tests/conftest.py` | Mock infrastructure for testing |
| `tests/test_tools.py` | Tests for error handling decorator |

## Related Documentation

- [Error Introspection](./error-introspection.md) - Node-level error/warning detection
- [Connection Module](../reference/quick-reference.md) - Connection API reference
