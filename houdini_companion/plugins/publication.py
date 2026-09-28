from ..registry import OperationSpec, PluginSpec
from ..rendering import image_metrics
from ..review_player import publish_files
from .introspection import PATH, object_schema
from .render_sequence import get


def publish(ctx, job, render_id, destination, title="Houdini review", annotations=None):
    """Publish integrity-checked synchronized images to a new local evaluation folder."""
    folder, data = get(ctx, render_id)
    return publish_files(folder, data, destination, title, annotations or [], image_metrics)


def plugin():
    return PluginSpec(
        "publication",
        "0.1.0",
        (
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
