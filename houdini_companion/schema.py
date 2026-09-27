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
    from .core import CompanionError

    properties, required = CONTRACTS[operation]
    if set(params) - set(properties) or set(required) - set(params):
        raise CompanionError(
            "INVALID_PARAMS", "Unknown or missing operation parameters", operation=operation
        )
    types = {
        str: "string",
        bool: "boolean",
        int: "integer",
        float: "number",
        list: "array",
        dict: "object",
        type(None): "null",
    }
    for name, value in params.items():
        rule = properties[name]
        allowed = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        invalid = types.get(type(value)) not in allowed
        if not invalid and isinstance(value, (int, float)):
            invalid = value < rule.get("minimum", float("-inf")) or value > rule.get(
                "maximum", float("inf")
            )
        if not invalid and isinstance(value, str):
            invalid = len(value) > rule.get("maxLength", 512000)
        if invalid:
            raise CompanionError(
                "INVALID_PARAMS", "Parameter does not match its schema", parameter=name
            )
