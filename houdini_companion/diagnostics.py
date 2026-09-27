"""Full frozen-geometry checks: bulk points and native parallel polygon queries."""

import hashlib
import json
import time

from .errors import CompanionError

AUDIT_VEX = r"""
string kind = primintrinsic(0, "typename", @primnum);
string topology = kind + ":" + itoa(int(primintrinsic(0, "closed", @primnum))) + ":";
foreach (int pt; primpoints(0, @primnum)) topology += itoa(pt) + ",";
s@audit_topology = topology;
i@audit_polygon = kind == "Poly" && primintrinsic(0, "closed", @primnum);
i@audit_zero = 0;
i@audit_normal = 0;
if (i@audit_polygon) {
    i@audit_zero = primintrinsic(0, "measuredarea", @primnum) <= 1e-9;
    if (haspointattrib(0, "N")) {
        vector normal = prim_normal(0, @primnum, 0.5, 0.5);
        foreach (int pt; primpoints(0, @primnum)) {
            vector n = point(0, "N", pt);
            if (!isfinite(n.x) || !isfinite(n.y) || !isfinite(n.z) || dot(normal, n) < 0.999)
                i@audit_normal = 1;
        }
    }
}
"""


def point_checks(buffer):
    import numpy as np

    points = np.frombuffer(buffer, dtype=np.float32).reshape(-1, 3)
    invalid = np.flatnonzero(~np.isfinite(points).all(axis=1))
    return {"nonfinite_point_count": len(invalid), "nonfinite_points": invalid[:20].tolist()}


def semantic_hash(geo, topology):
    """Hash topology and all scalar/tuple attributes, excluding serialization metadata."""
    h = hashlib.sha256()
    h.update(topology)
    for location in ("point", "vertex", "prim"):
        attributes = getattr(geo, location + "Attribs")()
        for attribute in sorted(attributes, key=lambda a: a.name()):
            if attribute.isArrayType():
                raise CompanionError(
                    "UNSUPPORTED_ATTRIBUTE",
                    "Iteration comparison does not support array attributes",
                )
            kind = attribute.dataType().name()
            h.update(json.dumps((location, attribute.name(), kind, attribute.size())).encode())
            if kind in ("Float", "Int"):
                h.update(getattr(geo, location + kind + "AttribValuesAsString")(attribute.name()))
            elif kind == "String":
                h.update(
                    json.dumps(
                        getattr(geo, location + "StringAttribValues")(attribute.name())
                    ).encode()
                )
            else:
                raise CompanionError("UNSUPPORTED_ATTRIBUTE", "Unsupported attribute type: " + kind)
    for attribute in sorted(geo.globalAttribs(), key=lambda a: a.name()):
        h.update(
            json.dumps((attribute.name(), geo.attribValue(attribute)), sort_keys=True).encode()
        )
    return h.hexdigest()


def audit(hou, geometry_path, checkpoint=lambda: None):
    """Never cooks or modifies the live source. Non-polygons are explicitly excluded."""
    import numpy as np

    started = time.perf_counter()
    container = None
    with hou.undos.disabler():
        try:
            container = hou.node("/obj").createNode("geo", "__companion_audit")
            container.setDisplayFlag(False)
            source = container.createNode("file", "frozen")
            source.parm("file").set(str(geometry_path))
            g = source.geometry()
            points = point_checks(g.pointFloatAttribValuesAsString("P"))
            checkpoint()
            node = container.createNode("attribwrangle", "polygon_checks")
            node.setInput(0, source)
            node.parm("class").set(1)
            node.parm("snippet").set(AUDIT_VEX)
            checked = node.geometry()
            if node.errors():
                raise CompanionError("AUDIT_FAILED", "; ".join(node.errors()))
            fields = {}
            for name in ("polygon", "zero", "normal"):
                values = np.frombuffer(
                    checked.primIntAttribValuesAsString("audit_" + name), dtype=np.int32
                )
                indices = np.flatnonzero(values)
                fields[name] = (len(indices), indices[:20].tolist())
            bbox = g.boundingBox()
            bounds = [list(bbox.minvec()), list(bbox.maxvec())]
            checks = {
                **points,
                "points_checked": g.intrinsicValue("pointcount"),
                "primitives_visited": g.intrinsicValue("primitivecount"),
                "polygons_checked": fields["polygon"][0],
                "excluded_non_polygons": g.intrinsicValue("primitivecount") - fields["polygon"][0],
                "zero_area_count": fields["zero"][0],
                "zero_area_primitives": fields["zero"][1],
                "normal_mismatch_count": fields["normal"][0],
                "normal_mismatch_primitives": fields["normal"][1],
                "point_normals_available": g.findPointAttrib("N") is not None,
                "complete": True,
                "scope": "all point positions and closed polygons; point N alignment when present",
                "topology_policy": "surface cards allowed; no watertightness or self-intersection claim",
            }
            return {
                "semantic_sha256": semantic_hash(
                    g, "\n".join(checked.primStringAttribValues("audit_topology")).encode()
                ),
                "semantic_scope": "ordered primitive topology, all point/vertex/primitive tuple attributes and detail attributes; excludes file metadata and groups",
                "points": checks["points_checked"],
                "primitives": checks["primitives_visited"],
                "bounds": bounds
                if np.isfinite(bounds).all() and checks["points_checked"]
                else None,
                "checks": checks,
                "attributes": {
                    "point": [a.name() for a in g.pointAttribs()],
                    "primitive": [a.name() for a in g.primAttribs()],
                    "detail": [a.name() for a in g.globalAttribs()],
                },
                "diagnostics_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        finally:
            if container is not None:
                container.destroy()


def valid(geometry):
    c = geometry["checks"]
    return (
        geometry["primitives"] > 0
        and c["complete"]
        and not any(
            c[k] for k in ("nonfinite_point_count", "zero_area_count", "normal_mismatch_count")
        )
    )
