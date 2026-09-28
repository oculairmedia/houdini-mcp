"""Portable polygon topology/orientation analysis; no six-face-solid assumption."""

from collections import defaultdict

import numpy as np

from .errors import CompanionError


def analyze(points, faces, profile="surface", weld_tolerance=1e-6):
    if profile not in {"surface", "open_cards", "closed_solids", "walkway"}:
        raise CompanionError("PROFILE", "Unknown geometry profile")
    xyz = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    reasons = []
    invalid = int(np.sum(~np.isfinite(xyz).all(axis=1)))
    if invalid:
        return {
            "accepted": False,
            "profile": profile,
            "reasons": ["NONFINITE_POINTS"],
            "nonfinite_points": invalid,
        }
    if not len(xyz) or not faces:
        return {"accepted": False, "profile": profile, "reasons": ["EMPTY_GEOMETRY"]}
    if len(xyz) > 1_000_000 or sum(map(len, faces)) > 2_000_000:
        raise CompanionError("GEOMETRY_BUDGET", "Reduce geometry below the profile budget")
    _, welded = np.unique(
        np.round(xyz / weld_tolerance).astype(np.float64), axis=0, return_inverse=True
    )
    lengths = np.asarray([len(face) for face in faces], dtype=np.int64)
    flat = np.asarray([p for face in faces for p in face], dtype=np.int64)
    if np.any(lengths < 3) or np.any(flat < 0) or np.any(flat >= len(xyz)):
        raise CompanionError("TOPOLOGY", "Invalid polygon indices")
    starts = np.r_[0, np.cumsum(lengths)[:-1]]
    next_indices = np.arange(len(flat)) + 1
    next_indices[np.cumsum(lengths) - 1] = starts
    reference = xyz.mean(axis=0)
    vertices = xyz[flat] - reference
    anchors = np.repeat(vertices[starts], lengths, axis=0)
    following = vertices[next_indices]
    areas = np.add.reduceat(np.cross(vertices - anchors, following - anchors), starts)
    degenerate = int(np.count_nonzero(np.linalg.norm(areas, axis=1) <= 1e-12))
    volumes = (
        np.einsum(
            "ij,ij->i", vertices[starts], np.add.reduceat(np.cross(vertices, following), starts)
        )
        / 6
    )
    edges = defaultdict(list)
    parent = list(range(len(faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, face in enumerate(faces):
        ids = welded[face].tolist()
        for a, b in zip(ids, ids[1:] + ids[:1], strict=True):
            edges[min(a, b), max(a, b)].append((i, a < b))
    boundary = nonmanifold = inconsistent = 0
    for uses in edges.values():
        boundary += len(uses) == 1
        nonmanifold += len(uses) > 2
        if len(uses) == 2:
            inconsistent += uses[0][1] == uses[1][1]
        for other, _ in uses[1:]:
            parent[find(other)] = find(uses[0][0])
    components = defaultdict(float)
    for i, volume in enumerate(volumes):
        components[find(i)] += volume
    # HOM uses clockwise exterior winding, hence negative conventional signed volume.
    inward = (
        int(sum(v >= -1e-12 for v in components.values()))
        if not boundary and not nonmanifold
        else None
    )
    if degenerate:
        reasons.append("DEGENERATE_POLYGONS")
    if profile == "closed_solids":
        if boundary:
            reasons.append("OPEN_BOUNDARY")
        if nonmanifold:
            reasons.append("NONMANIFOLD")
        if inconsistent:
            reasons.append("INCONSISTENT_WINDING")
        if inward:
            reasons.append("INWARD_OR_ZERO_VOLUME")
    return {
        "accepted": not reasons,
        "profile": profile,
        "reasons": reasons,
        "points": len(xyz),
        "polygons": len(faces),
        "nonfinite_points": 0,
        "degenerate_polygons": int(degenerate),
        "boundary_edges": int(boundary),
        "nonmanifold_edges": int(nonmanifold),
        "inconsistent_edges": int(inconsistent),
        "inward_components": inward,
        "components": len(components),
        "scope": "Welded polygon topology and component signed volume; no self-intersection proof",
    }


def from_hou(geo, profile="surface", probes=()):
    if (
        geo.intrinsicValue("pointcount") > 1_000_000
        or geo.intrinsicValue("vertexcount") > 2_000_000
    ):
        raise CompanionError("GEOMETRY_BUDGET", "Reduce geometry below the profile budget")
    if any(p.type().name() != "Polygon" or not p.isClosed() for p in geo.prims()):
        raise CompanionError(
            "POLYGONS_REQUIRED", "Profile requires closed polygon primitives; unpack/convert first"
        )
    xyz = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), dtype=np.float32).reshape(-1, 3)
    faces = [[v.point().number() for v in p.vertices()] for p in geo.prims()]
    result = analyze(xyz, faces, profile)
    if profile == "walkway":
        if not probes:
            raise CompanionError("PROBES_REQUIRED", "Walking profile requires explicit ray probes")
        import hou

        hits = []
        for index, probe in enumerate(probes):
            hit = geo.intersect(
                hou.Vector3(probe["origin"]),
                hou.Vector3(probe["direction"]),
                hou.Vector3(),
                hou.Vector3(),
                hou.Vector3(),
                min_hit=0.001,
                max_hit=probe["distance"],
                tolerance=0.001,
            )
            if hit >= 0:
                hits.append({"probe": index, "primitive": hit})
        result["clearance_hits"] = hits
        if hits:
            result["reasons"].append("CLEARANCE_HIT")
            result["accepted"] = False
        result["scope"] += "; supplied ray probes only, not continuous collision detection"
    return result
