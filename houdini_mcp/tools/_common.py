"""Shared utilities for Houdini MCP tools.

This module contains common utilities used across all tool modules:
- Connection error handling
- Response size management
- JSON serialization helpers
- Dangerous code detection
- Node serialization
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..connection import (
    ensure_connected,
    is_connected,
    HoudiniConnectionError,
    disconnect,
    safe_execute,
    quick_health_check,
    DEFAULT_OPERATION_TIMEOUT,
)

# Re-export connection utilities for convenience
__all__ = [
    # Connection utilities
    "ensure_connected",
    "is_connected",
    "HoudiniConnectionError",
    "disconnect",
    "safe_execute",
    "quick_health_check",
    "DEFAULT_OPERATION_TIMEOUT",
    # Error handling
    "CONNECTION_ERRORS",
    "_handle_connection_error",
    # Code safety
    "DANGEROUS_PATTERNS",
    "_detect_dangerous_code",
    # Output utilities
    "_truncate_output",
    # Response size utilities
    "RESPONSE_SIZE_WARNING_THRESHOLD",
    "RESPONSE_SIZE_LARGE_THRESHOLD",
    "_estimate_response_size",
    "_add_response_metadata",
    # Serialization utilities
    "_json_safe_hou_value",
    "_node_to_dict",
    "_serialize_scene_state",
    "_get_scene_diff",
    "_flatten_parm_templates",
    # Exceptions
    "ExecutionTimeoutError",
    # Logging
    "logger",
]

logger = logging.getLogger("houdini_mcp.tools")


# RPyC and connection-related exceptions that indicate broken/timed-out connections
# These should return graceful error responses, not crash the MCP server
CONNECTION_ERRORS = (
    EOFError,  # Connection closed unexpectedly
    BrokenPipeError,  # Pipe broken
    ConnectionResetError,  # Connection reset by peer
    ConnectionRefusedError,  # Connection refused
    ConnectionAbortedError,  # Connection aborted
    TimeoutError,  # Operation timed out
    OSError,  # Various OS-level connection errors
)


def _handle_connection_error(e: Exception, operation: str) -> Dict[str, Any]:
    """
    Handle connection-related errors gracefully.

    Cleans up the broken connection and returns a proper error response.

    Args:
        e: The exception that occurred
        operation: Name of the operation that failed

    Returns:
        Error response dict
    """
    error_type = type(e).__name__
    error_msg = str(e)

    # Clean up the broken connection so next call can reconnect
    try:
        disconnect()
    except Exception:
        pass

    logger.error(f"Connection error during {operation}: {error_type}: {error_msg}")

    # Provide helpful messages based on error type
    if isinstance(e, TimeoutError):
        message = (
            f"Operation '{operation}' timed out. Houdini may be busy with a heavy computation. "
            "The connection has been reset - subsequent calls will reconnect automatically."
        )
    elif isinstance(e, EOFError):
        message = (
            f"Connection to Houdini closed unexpectedly during '{operation}'. "
            "Houdini may have crashed or the RPC server stopped. "
            "The connection has been reset - subsequent calls will attempt to reconnect."
        )
    elif isinstance(e, (BrokenPipeError, ConnectionResetError)):
        message = (
            f"Connection to Houdini was lost during '{operation}'. "
            "The connection has been reset - subsequent calls will reconnect automatically."
        )
    else:
        message = (
            f"Connection error during '{operation}': {error_type}: {error_msg}. "
            "The connection has been reset - subsequent calls will reconnect automatically."
        )

    return {
        "status": "error",
        "error_type": "connection_error",
        "exception": error_type,
        "message": message,
        "operation": operation,
        "recoverable": True,
    }


# Dangerous code patterns for safety scanning
DANGEROUS_PATTERNS: List[Tuple[str, str]] = [
    (r"\bhou\.exit\s*\(", "hou.exit() - will close Houdini"),
    (r"\bos\.remove\s*\(", "os.remove() - file deletion"),
    (r"\bos\.unlink\s*\(", "os.unlink() - file deletion"),
    (r"\bshutil\.rmtree\s*\(", "shutil.rmtree() - directory deletion"),
    (r"\bsubprocess\b", "subprocess - shell execution"),
    (r"\bos\.system\s*\(", "os.system() - shell execution"),
    (r'\bopen\s*\([^)]*["\'][wa]', "open() with write mode - file writing"),
    (r"\bhou\.hipFile\.clear\s*\(", "hou.hipFile.clear() - scene wipe"),
]


def _detect_dangerous_code(code: str) -> List[str]:
    """
    Scan code for potentially dangerous patterns.

    Args:
        code: Python code to scan

    Returns:
        List of detected dangerous pattern descriptions
    """
    detected: List[str] = []
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            detected.append(description)
    return detected


def _truncate_output(output: str, max_size: int) -> Tuple[str, bool]:
    """
    Truncate output if it exceeds max_size.

    Args:
        output: The output string to potentially truncate
        max_size: Maximum allowed size in bytes

    Returns:
        Tuple of (truncated_output, was_truncated)
    """
    if len(output) > max_size:
        truncated = output[:max_size]
        return truncated, True
    return output, False


# Response size thresholds (in bytes)
RESPONSE_SIZE_WARNING_THRESHOLD = 100 * 1024  # 100KB - warn above this
RESPONSE_SIZE_LARGE_THRESHOLD = 500 * 1024  # 500KB - considered large


def _estimate_response_size(data: Any, _depth: int = 0) -> int:
    """
    Estimate the JSON-serialized size of a response without full serialization.

    Uses a fast recursive estimation that avoids the overhead of actually
    serializing the entire structure to JSON (which would be done again
    by the MCP framework anyway).

    Args:
        data: The data structure to estimate size for
        _depth: Internal recursion depth counter

    Returns:
        Estimated size in bytes
    """
    # Prevent infinite recursion
    if _depth > 50:
        return 20

    if data is None:
        return 4  # "null"
    if isinstance(data, bool):
        return 5  # "true" or "false"
    if isinstance(data, int):
        return len(str(data))
    if isinstance(data, float):
        return len(str(data)) + 2  # Account for possible scientific notation
    if isinstance(data, str):
        return len(data) + 2  # quotes

    if isinstance(data, dict):
        # {"key": value, ...} - estimate key/value pairs + overhead
        size = 2  # {}
        for k, v in data.items():
            size += len(str(k)) + 4  # "key": + comma
            size += _estimate_response_size(v, _depth + 1)
        return size

    if isinstance(data, (list, tuple)):
        # [item, item, ...] - estimate items + overhead
        size = 2  # []
        for item in data:
            size += _estimate_response_size(item, _depth + 1) + 1  # comma
        return size

    # Fallback for other types
    return len(str(data)) + 2


def _add_response_metadata(result: Dict[str, Any], include_size: bool = True) -> Dict[str, Any]:
    """
    Add response metadata including size information.

    Args:
        result: The result dictionary to augment
        include_size: Whether to include size metadata

    Returns:
        The result dictionary with added metadata
    """
    if not include_size:
        return result

    size_bytes = _estimate_response_size(result)
    result["_response_size_bytes"] = size_bytes

    if size_bytes > RESPONSE_SIZE_LARGE_THRESHOLD:
        result["_response_size_warning"] = (
            f"Large response ({size_bytes // 1024}KB). "
            "Consider using compact=True, reducing max_results, or adding filters."
        )
    elif size_bytes > RESPONSE_SIZE_WARNING_THRESHOLD:
        result["_response_size_note"] = f"Response size: {size_bytes // 1024}KB"

    return result


def _json_safe_hou_value(
    hou: Any, value: Any, *, max_depth: int = 10, _seen: Optional[Set[int]] = None
) -> Any:
    """Convert Houdini (hou) values into JSON-serializable structures."""
    if max_depth <= 0:
        return str(value)

    if _seen is None:
        _seen = set()

    # Prevent infinite recursion
    try:
        value_id = id(value)
        if value_id in _seen:
            return "<recursion>"
        _seen.add(value_id)
    except Exception:
        pass

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", errors="replace")

    if isinstance(value, (list, tuple, set)):
        return [_json_safe_hou_value(hou, v, max_depth=max_depth - 1, _seen=_seen) for v in value]

    if isinstance(value, dict):
        return {
            str(k): _json_safe_hou_value(hou, v, max_depth=max_depth - 1, _seen=_seen)
            for k, v in value.items()
        }

    # Common hou objects (Node, Parm, etc.)
    path_attr = getattr(value, "path", None)
    if callable(path_attr):
        try:
            path = path_attr()
            if isinstance(path, str):
                return path
        except Exception:
            pass

    # Ramp parameters are a common source of non-serializable values.
    try:
        if hasattr(hou, "Ramp") and isinstance(value, hou.Ramp):
            try:
                basis = list(value.basis())
            except Exception:
                basis = []

            try:
                keys = list(value.keys())
            except Exception:
                keys = []

            try:
                values = list(value.values())
            except Exception:
                values = []

            return {
                "type": "hou.Ramp",
                "basis": [
                    _json_safe_hou_value(hou, b, max_depth=max_depth - 1, _seen=_seen)
                    for b in basis
                ],
                "keys": [
                    _json_safe_hou_value(hou, k, max_depth=max_depth - 1, _seen=_seen) for k in keys
                ],
                "values": [
                    _json_safe_hou_value(hou, v, max_depth=max_depth - 1, _seen=_seen)
                    for v in values
                ],
            }
    except Exception:
        pass

    try:
        module_name = type(value).__module__
        type_name = type(value).__name__

        if module_name.startswith("hou"):
            if type_name in {"Vector2", "Vector3", "Vector4", "Color"}:
                try:
                    return [float(x) for x in value]
                except Exception:
                    pass

            if type_name == "EnumValue":
                try:
                    name = value.name()
                    if isinstance(name, str):
                        return name
                except Exception:
                    pass
    except Exception:
        pass

    # Fallback: represent as string instead of throwing
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


class ExecutionTimeoutError(Exception):
    """Raised when code execution exceeds the timeout."""

    pass


def _node_to_dict(
    node: Any, include_params: bool = True, max_params: int = 100, hou: Any = None
) -> Dict[str, Any]:
    """
    Serialize a node to a dictionary.

    Args:
        node: Houdini node object
        include_params: Whether to include parameter values
        max_params: Maximum number of parameters to include
        hou: The hou module (optional, for value conversion)

    Returns:
        Dict representation of the node
    """
    result: Dict[str, Any] = {
        "path": node.path(),
        "type": node.type().name(),
        "name": node.name(),
    }

    if hou is None:
        hou = type("_HouSentinel", (), {})()

    if include_params:
        params: Dict[str, Any] = {}
        for i, parm in enumerate(node.parms()):
            if i >= max_params:
                break
            try:
                params[parm.name()] = _json_safe_hou_value(hou, parm.eval())
            except Exception:
                params[parm.name()] = "<unevaluable>"
        result["parameters"] = params

    # Recursively serialize children
    result["children"] = [
        _node_to_dict(
            child, include_params=False, hou=hou
        )  # Don't include params for children to reduce size
        for child in node.children()
    ]

    return result


def _serialize_scene_state(hou: Any, root_path: str = "/obj") -> List[Dict[str, Any]]:
    """
    Serialize the scene state for comparison.

    Uses hscript commands for fast path enumeration (800x faster than
    per-node RPC calls), falling back to the slow method for mocks.

    Args:
        hou: The hou module
        root_path: Root node path to serialize from

    Returns:
        List of node dictionaries with path, type, name, children
    """
    # Try fast hscript-based approach first (works with real Houdini)
    try:
        if hasattr(hou, "hscript"):
            return _serialize_scene_state_fast(hou, root_path)
    except Exception as e:
        logger.debug(f"Fast serialization failed, using fallback: {e}")

    # Fallback for mocks or if hscript fails
    obj = hou.node(root_path)
    if obj is None:
        return []
    return [_node_to_dict(child, hou=hou) for child in obj.children()]


def _serialize_scene_state_fast(hou: Any, root_path: str = "/obj") -> List[Dict[str, Any]]:
    """
    Fast scene serialization using hscript commands.

    This avoids per-node RPC calls by using hscript to get all paths
    and types in bulk operations. ~800x faster than per-node RPC.

    Args:
        hou: The hou module (must have hscript method)
        root_path: Root node path to serialize from

    Returns:
        List of node dictionaries with path, name, type, children
    """
    # Get recursive listing of all nodes
    result, _ = hou.hscript(f"opls -R {root_path}")
    if not result:
        return []

    # Parse hierarchical output into flat dict
    # Format:
    #   /obj:
    #   geo1
    #   cam1
    #   /obj/geo1:
    #   sphere1
    nodes_by_path: Dict[str, Dict[str, Any]] = {}
    children_by_parent: Dict[str, List[str]] = {}  # parent_path -> [child_paths]
    current_parent = root_path

    for line in result.strip().split("\n"):
        if line.endswith(":"):
            current_parent = line[:-1]
        elif line.strip():
            name = line.strip()
            full_path = f"{current_parent}/{name}"
            nodes_by_path[full_path] = {
                "path": full_path,
                "name": name,
                "type": "unknown",
                "children": [],
            }
            # Track parent-child relationships
            if current_parent not in children_by_parent:
                children_by_parent[current_parent] = []
            children_by_parent[current_parent].append(full_path)

    # Get types for immediate children of root
    type_result, _ = hou.hscript(f"optype {root_path}/*")
    if type_result:
        current_name = None
        for line in type_result.strip().split("\n"):
            if line.startswith("Name: "):
                current_name = line[6:]
            elif line.startswith("Op Type: ") and current_name:
                path = f"{root_path}/{current_name}"
                if path in nodes_by_path:
                    nodes_by_path[path]["type"] = line[9:]

    # Build tree using O(n) algorithm with children_by_parent index
    def build_tree(node_path: str) -> Dict[str, Any]:
        node = nodes_by_path.get(node_path)
        if node is None:
            return {
                "path": node_path,
                "name": node_path.split("/")[-1],
                "type": "unknown",
                "children": [],
            }
        # Recursively build children
        child_paths = children_by_parent.get(node_path, [])
        node["children"] = [build_tree(cp) for cp in child_paths]
        return node

    # Build result for immediate children of root
    root_children = children_by_parent.get(root_path, [])
    return [build_tree(path) for path in root_children]


def _get_scene_diff(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compare scene states and return the differences.

    Args:
        before: Scene state before operation
        after: Scene state after operation

    Returns:
        Dict with added, removed, and modified nodes
    """
    before_paths: Set[str] = {node["path"] for node in before}
    after_paths: Set[str] = {node["path"] for node in after}

    added = after_paths - before_paths
    removed = before_paths - after_paths

    # Find modified nodes (same path but different content)
    modified: List[str] = []
    before_by_path = {node["path"]: node for node in before}
    after_by_path = {node["path"]: node for node in after}

    for path in before_paths & after_paths:
        if before_by_path[path] != after_by_path[path]:
            modified.append(path)

    return {
        "added": list(added),
        "removed": list(removed),
        "modified": modified,
        "added_nodes": [n for n in after if n["path"] in added],
        "has_changes": bool(added or removed or modified),
    }


def _flatten_parm_templates(hou: Any, parm_templates: List[Any], max_depth: int = 20) -> List[Any]:
    """
    Flatten nested parameter templates into a single list.

    Args:
        hou: The hou module
        parm_templates: List of parameter templates to flatten
        max_depth: Maximum recursion depth

    Returns:
        Flattened list of parameter templates
    """
    flattened: List[Any] = []

    def walk(templates: List[Any], depth: int) -> None:
        if depth > max_depth:
            return

        for template in templates:
            try:
                template_type = template.type()
            except Exception:
                template_type = None

            is_folder_like = False
            try:
                is_folder_like = template_type in (
                    hou.parmTemplateType.Folder,
                    hou.parmTemplateType.FolderSet,
                )
            except Exception:
                is_folder_like = False

            is_multiparm = False
            try:
                is_multiparm = template_type in (
                    hou.parmTemplateType.MultiParmBlock,
                    hou.parmTemplateType.MultiParm,
                )
            except Exception:
                is_multiparm = False

            flattened.append(template)

            if (is_folder_like or is_multiparm) and hasattr(template, "parmTemplates"):
                try:
                    child_templates = list(template.parmTemplates())
                except Exception:
                    child_templates = []
                walk(child_templates, depth + 1)

    walk(parm_templates, 0)

    # De-dup while preserving order (folders can appear in multiple lists)
    seen_ids: Set[int] = set()
    unique: List[Any] = []
    for template in flattened:
        template_id = id(template)
        if template_id in seen_ids:
            continue
        seen_ids.add(template_id)
        unique.append(template)

    return unique
