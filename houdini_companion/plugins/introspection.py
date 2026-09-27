"""Bounded graph, parameter, node-type and geometry access for programmatic review."""

import fnmatch
import math
from collections import deque
from itertools import islice

from ..errors import CompanionError
from ..observation import require_node
from ..registry import OperationSpec, PluginSpec


def object_schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


PATH = {"type": "string", "minLength": 1}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 256}


def graph(context, job, path="/obj", depth=2, limit=128):
    pending = deque([(require_node(context.hou, path), 0)])
    nodes, edges = [], []
    truncated = False
    while pending and len(nodes) < limit:
        context.ledger.checkpoint(job["job_id"])
        node, level = pending.popleft()
        nodes.append(
            {
                "path": node.path(),
                "id": node.sessionId(),
                "type": node.type().name(),
                "errors": list(node.errors())[:8],
                "warnings": list(node.warnings())[:8],
            }
        )
        for c in node.inputConnections()[:256]:
            if len(edges) >= 1024:
                truncated = True
                break
            edges.append(
                {
                    "target": node.path(),
                    "input": c.inputIndex(),
                    "source": c.inputNode().path() if c.inputNode() else None,
                    "output": c.outputIndex(),
                }
            )
        if level < depth:
            children = node.children()
            capacity = max(0, limit - len(nodes) - len(pending))
            pending.extend((child, level + 1) for child in children[:capacity])
            truncated |= len(children) > capacity
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated or bool(pending),
        "depth": depth,
        "frame": context.hou.frame(),
        "scope": "bounded network structure; use inspect for mutation tokens",
    }


def parameters(context, job, path, pattern="*", limit=128):
    node = require_node(context.hou, path)
    matches = [p for p in node.parms() if fnmatch.fnmatchcase(p.name(), pattern)]
    values = []
    for p in matches[:limit]:
        t = p.parmTemplate()
        row = {
            "name": p.name(),
            "label": t.label(),
            "type": t.type().name(),
            "raw": p.rawValue()[:2048],
            "animated_or_expression": bool(p.keyframes()),
        }
        if hasattr(t, "menuItems"):
            row["menu_items"] = list(t.menuItems())[:128]
        if hasattr(t, "minValue"):
            row.update(
                min=t.minValue(),
                max=t.maxValue(),
                min_strict=t.minIsStrict(),
                max_strict=t.maxIsStrict(),
            )
        values.append(row)
    return {
        "path": path,
        "parameters": values,
        "matched": len(matches),
        "truncated": len(matches) > limit,
    }


def node_types(context, job, category="Sop", pattern="*", limit=128):
    categories = context.hou.nodeTypeCategories()
    if category not in categories:
        raise CompanionError("CATEGORY", "Unknown node category", available=list(categories))
    matches = [
        (name, t)
        for name, t in categories[category].nodeTypes().items()
        if fnmatch.fnmatchcase(name, pattern)
    ]
    matches.sort(key=lambda item: item[0])
    return {
        "types": [
            {"name": name, "description": t.description(), "category": category}
            for name, t in matches[:limit]
        ],
        "matched": len(matches),
        "truncated": len(matches) > limit,
    }


def normalize(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [normalize(v) for v in value]
    return value[:2048] if isinstance(value, str) else value


def geometry_sample(context, job, path, offset=0, limit=64, attributes=None):
    node = require_node(context.hou, path)
    if not isinstance(node, context.hou.SopNode):
        raise CompanionError("SOP_REQUIRED", "Geometry sampling requires a SOP")
    geo = node.geometry().freeze()
    if node.errors():
        raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
    names = attributes or ["P"]
    attrs = []
    for name in names:
        attr = geo.findPointAttrib(name)
        if attr is None:
            raise CompanionError("ATTRIBUTE_NOT_FOUND", "Point attribute missing", attribute=name)
        if attr.size() > 64 or attr.isArrayType():
            raise CompanionError(
                "ATTRIBUTE_LIMIT", "Array or wide attributes require explicit Python access"
            )
        attrs.append(attr)
    rows = [
        {
            "number": point.number(),
            "values": {a.name(): normalize(point.attribValue(a)) for a in attrs},
        }
        for point in islice(geo.iterPoints(), offset, offset + limit)
    ]
    count = geo.intrinsicValue("pointcount")
    return {
        "path": path,
        "points": rows,
        "total_points": count,
        "offset": offset,
        "truncated": offset + len(rows) < count,
        "frame": context.hou.frame(),
    }


def plugin():
    return PluginSpec(
        "introspection",
        "0.2.0",
        (
            OperationSpec(
                "query.batch",
                "read",
                object_schema(
                    {
                        "queries": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 16,
                            "items": object_schema(
                                {"operation": {"type": "string"}, "params": {"type": "object"}},
                                ["operation", "params"],
                            ),
                        }
                    },
                    ["queries"],
                ),
                batch,
                "Execute up to 16 read operations in one UI dispatch; no recursive batches.",
            ),
            OperationSpec(
                "query.graph",
                "read",
                object_schema(
                    {
                        "path": PATH,
                        "depth": {"type": "integer", "minimum": 0, "maximum": 8},
                        "limit": LIMIT,
                    }
                ),
                graph,
                "Bounded nodes and connections without full parameter fingerprints.",
            ),
            OperationSpec(
                "query.parameters",
                "read",
                object_schema(
                    {"path": PATH, "pattern": {"type": "string"}, "limit": LIMIT}, ["path"]
                ),
                parameters,
                "Filter parameter metadata and values.",
            ),
            OperationSpec(
                "query.node_types",
                "read",
                object_schema(
                    {"category": {"type": "string"}, "pattern": {"type": "string"}, "limit": LIMIT}
                ),
                node_types,
                "Discover installed node types.",
            ),
            OperationSpec(
                "query.geometry",
                "read",
                object_schema(
                    {
                        "path": PATH,
                        "offset": {"type": "integer", "minimum": 0, "maximum": 50000},
                        "limit": LIMIT,
                        "attributes": {
                            "type": "array",
                            "maxItems": 16,
                            "items": {"type": "string"},
                        },
                    },
                    ["path"],
                ),
                geometry_sample,
                "Sample bounded point attributes from cooked geometry.",
            ),
        ),
        requires=("query",),
    )


def batch(context, job, queries):
    effects = context.registry.effects()
    for query in queries:
        operation = query["operation"]
        if operation == "query.batch" or effects.get(operation) != "read":
            raise CompanionError(
                "READ_REQUIRED", "Grouped queries allow only nonrecursive read operations"
            )
        context.registry.validate(operation, query["params"])
    return {
        "results": [
            {
                "operation": q["operation"],
                "result": context.call(q["operation"], job, **q["params"]),
            }
            for q in queries
        ]
    }
