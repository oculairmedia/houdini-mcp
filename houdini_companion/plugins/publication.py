import json
from pathlib import Path

from ..core import atomic_json, digest
from ..errors import CompanionError
from ..registry import OperationSpec, PluginSpec
from ..rendering import image_metrics
from ..review_player import publish_files
from .introspection import PATH, object_schema
from .render_sequence import get, validate_review


def publish(ctx, job, render_id, destination, title="Houdini review", annotations=None):
    """Publish integrity-checked synchronized images to a new local evaluation folder."""
    if len(ctx.state.get("reviews", {})) >= 16:
        raise CompanionError("REVIEW_LIMIT", "Promote/discard a reviewed candidate first")
    folder, data = get(ctx, render_id)
    state = validate_review(ctx, folder, data)
    result = publish_files(folder, data, destination, title, annotations or [], image_metrics)
    public = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    receipt = {
        "review_id": job["job_id"],
        "manifest": result["manifest"],
        "manifest_digest": digest(public),
        "path": data["path"],
        "session_id": data["session_id"],
        "scene_id": data["scene_id"],
    }
    atomic_json(ctx.ledger.root / job["job_id"] / "review-receipt.json", receipt)
    ctx.state.setdefault("reviews", {})[job["job_id"]] = receipt
    return {
        **result,
        "review_id": job["job_id"],
        "state_receipt": state,
        "scope": "Complete, source-aligned sampled evidence; not aesthetic approval",
    }


def plugin():
    return PluginSpec(
        "publication",
        "0.2.0",
        (
            OperationSpec(
                "review.release",
                "artifacts",
                object_schema({"review_id": PATH}, ["review_id"]),
                release,
            ),
            OperationSpec(
                "review.publish",
                "artifacts",
                object_schema(
                    {
                        "render_id": PATH,
                        "destination": PATH,
                        "title": {"type": "string", "maxLength": 200},
                        "annotations": {
                            "type": "array",
                            "maxItems": 300,
                            "items": object_schema(
                                {
                                    "frame": {"type": "number"},
                                    "text": {"type": "string", "maxLength": 2000},
                                },
                                ["frame", "text"],
                            ),
                        },
                    },
                    ["render_id", "destination"],
                ),
                publish,
                publish.__doc__,
            ),
        ),
        requires=("render_sequence",),
    )


def release(ctx, job, review_id):
    """Unpin a review receipt without deleting the artist's published files."""
    if review_id not in ctx.state.get("reviews", {}):
        raise CompanionError("REVIEW_NOT_FOUND", review_id)
    del ctx.state["reviews"][review_id]
    return {"released": review_id, "published_files_deleted": False}
