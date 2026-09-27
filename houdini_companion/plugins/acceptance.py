"""Review receipts bind declarative checks to geometry and image evidence."""

from ..core import atomic_json, digest
from ..errors import CompanionError
from ..registry import OperationSpec, PluginSpec
from ..schema import COMMON_RENDER
from .introspection import PATH, object_schema

RULES = object_schema(
    {
        "min_points": {"type": "integer", "minimum": 1},
        "min_primitives": {"type": "integer", "minimum": 1},
        "max_warnings": {"type": "integer", "minimum": 0},
        "required_point_attributes": {"type": "array", "maxItems": 32, "items": {"type": "string"}},
        "min_coverage": {"type": "number", "minimum": 0, "maximum": 1},
    }
)


def evaluate(feedback, requirements):
    geo = feedback["geometry"]
    checks = {
        "nonempty": geo["points"] > 0 and geo["primitives"] > 0,
        "finite_points": geo["checks"]["nonfinite_point_count"] == 0,
        "nonzero_polygons": geo["checks"]["zero_area_count"] == 0,
        "complete_geometry_checks": geo["checks"]["complete"],
        "fresh": not feedback.get("stale", True),
        "images_visible": bool(feedback["images"])
        and all(not i["suspect_blank_or_dark"] for i in feedback["images"]),
    }
    for key, field in [("min_points", "points"), ("min_primitives", "primitives")]:
        if key in requirements:
            checks[key] = geo[field] >= requirements[key]
    if "max_warnings" in requirements:
        checks["max_warnings"] = len(feedback["warnings"]) <= requirements["max_warnings"]
    if "required_point_attributes" in requirements:
        checks["required_point_attributes"] = set(requirements["required_point_attributes"]) <= set(
            geo["attributes"]["point"]
        )
    if "min_coverage" in requirements:
        checks["min_coverage"] = all(
            i.get("alpha_coverage", 0) >= requirements["min_coverage"] for i in feedback["images"]
        )
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "scope": "declared geometry and image checks; artistic correctness requires visual review",
    }


def accept(context, job, path, requirements=None, views=None, resolution=384, expected=None):
    requirements = requirements or {}
    feedback = context.call(
        "snapshot",
        job,
        path=path,
        expected=expected,
        views=views or ["front", "right", "persp"],
        resolution=resolution,
    )
    evidence = {
        "requirements": requirements,
        "observation": feedback["observation"]["token"],
        "geometry_sha256": feedback["geometry_artifact"]["sha256"],
        "images": [{"view": i["view"], "sha256": i["sha256"]} for i in feedback["images"]],
    }
    result = {
        **evaluate(feedback, requirements),
        "evidence": evidence,
        "receipt_hash": digest(evidence),
        "feedback": feedback,
    }
    atomic_json(context.ledger.root / job["job_id"] / "acceptance.json", result)
    return result


def compare(context, job, before_job, after_job):
    def feedback(jid):
        result = context.ledger.get(jid).get("result", {})
        value = result.get("feedback", result)
        if "geometry" not in value or "geometry_artifact" not in value:
            raise CompanionError("REVIEW_REQUIRED", "Choose jobs with completed geometry feedback")
        return value

    before, after = feedback(before_job), feedback(after_job)
    return {
        "before_job": before_job,
        "after_job": after_job,
        "point_delta": after["geometry"]["points"] - before["geometry"]["points"],
        "primitive_delta": after["geometry"]["primitives"] - before["geometry"]["primitives"],
        "bounds_before": before["geometry"]["bounds"],
        "bounds_after": after["geometry"]["bounds"],
        "geometry_hash_equal": before["geometry_artifact"]["sha256"]
        == after["geometry_artifact"]["sha256"],
        "scope": "recorded evidence comparison; does not assert current scene state",
    }


def plugin():
    return PluginSpec(
        "acceptance",
        "0.2.0",
        (
            OperationSpec(
                "review.accept",
                "artifacts",
                object_schema(
                    {
                        "path": PATH,
                        "expected": {"type": ["string", "null"]},
                        "requirements": RULES,
                        **COMMON_RENDER,
                    },
                    ["path"],
                ),
                accept,
                "Render and evaluate hash-bound evidence against declared requirements.",
            ),
            OperationSpec(
                "review.compare",
                "read",
                object_schema({"before_job": PATH, "after_job": PATH}, ["before_job", "after_job"]),
                compare,
                "Compare two retained geometry review results.",
            ),
        ),
        requires=("review",),
    )
