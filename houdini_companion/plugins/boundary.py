from ..errors import CompanionError
from ..observation import check_expected, require_node
from ..registry import OperationSpec, PluginSpec
from ..state_guard import StateGuard
from .introspection import PATH, object_schema


def boundary(
    ctx,
    job,
    path,
    before,
    after,
    id_attribute="id",
    tolerance=0.01,
    allow_birth_death=False,
    render_id=None,
    image_tolerance=0.08,
):
    """Compare stable point ids and optional fixed-camera images across a boundary."""
    import numpy as np

    from ..continuity import compare_images, compare_points, image_pixels
    from .render_sequence import file_ok, get

    node = require_node(ctx.hou, path)
    values = []
    with StateGuard(ctx.hou) as state:
        for frame in (before, after):
            geo = node.geometryAtFrame(frame)
            if geo.intrinsicValue("pointcount") > 1_000_000:
                raise CompanionError(
                    "GEOMETRY_BUDGET", "Correspondence is limited to one million points"
                )
            if node.errors():
                raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
            attr = geo.findPointAttrib(id_attribute)
            if attr is None or attr.size() != 1:
                raise CompanionError(
                    "IDENTITY_REQUIRED", "A scalar int/string point identity is required"
                )
            if attr.dataType() == ctx.hou.attribData.Int:
                ids = list(geo.pointIntAttribValues(id_attribute))
            elif attr.dataType() == ctx.hou.attribData.String:
                ids = list(geo.pointStringAttribValues(id_attribute))
            else:
                raise CompanionError("IDENTITY_REQUIRED", "Identity must be int or string")
            xyz = (
                np.frombuffer(geo.pointFloatAttribValuesAsString("P"), dtype=np.float32)
                .reshape(-1, 3)
                .copy()
            )
            values.append((ids, xyz))
        result = compare_points(*values[0], *values[1], tolerance, allow_birth_death)
        if render_id:
            folder, data = get(ctx, render_id)
            if data["path"] != path or before not in data["frames"] or after not in data["frames"]:
                raise CompanionError(
                    "UNALIGNED_EVIDENCE", "Render source and sampled frames must match"
                )
            ctx.hou.setFrame(data["anchor_frame"])
            node.geometry()
            check_expected(ctx.hou, node, data["expected"])
            rows = [data["rows"][data["frames"].index(f)] for f in (before, after)]
            if any(row is None for row in rows):
                raise CompanionError("INCOMPLETE_REVIEW", "Render both samples first")
            image_results = []
            for a, b in zip(rows[0]["images"], rows[1]["images"], strict=True):
                if not file_ok(folder, a, True) or not file_ok(folder, b, True):
                    raise CompanionError("ARTIFACT_CORRUPT", "Image evidence changed")
                image_results.append(
                    compare_images(
                        image_pixels(folder / a["name"]), image_pixels(folder / b["name"])
                    )
                )
            result["images"] = image_results
            if any(i["mean_absolute_difference"] > image_tolerance for i in image_results):
                result["accepted"] = False
                result["reasons"].append("IMAGE_DISCONTINUITY")
        node.geometry()
    return {**result, "frames": [before, after], "state_receipt": state.receipt}


def plugin():
    return PluginSpec(
        "boundary",
        "0.1.0",
        (
            OperationSpec(
                "timeline.boundary",
                "read",
                object_schema(
                    {
                        "path": PATH,
                        "before": {"type": "number"},
                        "after": {"type": "number"},
                        "id_attribute": PATH,
                        "tolerance": {"type": "number", "minimum": 0},
                        "allow_birth_death": {"type": "boolean"},
                        "render_id": PATH,
                        "image_tolerance": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    ["path", "before", "after"],
                ),
                boundary,
                boundary.__doc__,
            ),
        ),
        requires=("render_sequence",),
    )
