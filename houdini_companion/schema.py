"""Portable request contracts shared by CLI, MCP and the embedded dispatcher."""

COMMON_RENDER = {
    "views": {"type": "array"},
    "resolution": {"type": "integer", "minimum": 128, "maximum": 1600},
}
CONTRACTS = {
    "inspect": ({"path": {"type": ["string", "null"]}, "geometry": {"type": "boolean"}}, []),
    "validate_observation": (
        {"path": {"type": "string"}, "expected": {"type": "string"}},
        ["path", "expected"],
    ),
    "snapshot": (
        {
            "path": {"type": "string"},
            "expected": {"type": ["string", "null"]},
            "focus": {"type": ["array", "null"]},
            **COMMON_RENDER,
        },
        ["path"],
    ),
    "batch": (
        {
            "actions": {"type": "array"},
            "expected": {"type": "object"},
            "output": {"type": ["string", "null"]},
            "feedback": {"type": "boolean"},
            **COMMON_RENDER,
        },
        ["actions"],
    ),
    "execute": (
        {
            "code": {"type": "string", "maxLength": 256000},
            "expected": {"type": "object"},
            "output": {"type": ["string", "null"]},
            "feedback": {"type": "boolean"},
        },
        ["code"],
    ),
    "undo": ({"job_id": {"type": "string"}}, ["job_id"]),
    "preview": (
        {
            "path": {"type": "string"},
            "expected": {"type": "string"},
            "values": {"type": "object"},
            **COMMON_RENDER,
        },
        ["path", "expected", "values"],
    ),
    "apply_preview": (
        {"preview_id": {"type": "string"}, "feedback": {"type": "boolean"}},
        ["preview_id"],
    ),
    "discard_preview": ({"preview_id": {"type": "string"}}, ["preview_id"]),
}


def schemas():
    return {
        name: {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        for name, (properties, required) in CONTRACTS.items()
    }


def validate(operation, params):
    validate_schema(schemas()[operation], params)


def check_schema(rule, depth=0):
    """Reject unsupported keywords rather than silently weakening a plugin contract."""
    from .errors import CompanionError

    supported = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "description",
        "title",
    }
    if not isinstance(rule, dict) or depth > 32 or set(rule) - supported:
        raise CompanionError("PLUGIN_SCHEMA", "Unsupported schema keyword or excessive depth")
    kinds = rule.get("type", [])
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if not set(kinds) <= {"string", "boolean", "integer", "number", "array", "object", "null"}:
        raise CompanionError("PLUGIN_SCHEMA", "Unsupported parameter type")
    if "additionalProperties" in rule and not isinstance(rule["additionalProperties"], bool):
        raise CompanionError("PLUGIN_SCHEMA", "additionalProperties must be boolean")
    for child in rule.get("properties", {}).values():
        check_schema(child, depth + 1)
    if "items" in rule:
        check_schema(rule["items"], depth + 1)


def validate_schema(rule, value, path="$", depth=0):
    from .errors import CompanionError

    if depth > 32:
        raise CompanionError("INVALID_PARAMS", "Parameter nesting exceeds limit", parameter=path)
    types = {
        str: "string",
        bool: "boolean",
        int: "integer",
        float: "number",
        list: "array",
        dict: "object",
        type(None): "null",
    }
    allowed = rule.get("type", [])
    allowed = allowed if isinstance(allowed, list) else [allowed]
    actual = types.get(type(value))
    invalid = bool(
        allowed and actual not in allowed and not (actual == "integer" and "number" in allowed)
    )
    if "enum" in rule and value not in rule["enum"]:
        invalid = True
    if type(value) in (int, float):
        import math

        invalid |= (
            not math.isfinite(value)
            or value < rule.get("minimum", float("-inf"))
            or value > rule.get("maximum", float("inf"))
        )
    if isinstance(value, str):
        invalid |= not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", 512000)
    if isinstance(value, list):
        invalid |= not rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", 10000)
        if "items" in rule:
            for i, item in enumerate(value):
                validate_schema(rule["items"], item, f"{path}[{i}]", depth + 1)
    if isinstance(value, dict):
        properties = rule.get("properties", {})
        invalid |= bool(set(rule.get("required", [])) - value.keys())
        if rule.get("additionalProperties") is False:
            invalid |= bool(value.keys() - properties.keys())
        for key, item in value.items():
            if key in properties:
                validate_schema(properties[key], item, f"{path}.{key}", depth + 1)
    if invalid:
        raise CompanionError(
            "INVALID_PARAMS", "Parameter does not match its schema", parameter=path
        )
