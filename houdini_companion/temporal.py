"""Portable time contracts and motion measurements; no Houdini imports."""

import math

from .errors import CompanionError


def frame_list(text, limit=32):
    """Comma list or inclusive start:end:step; repeated frames test determinism."""
    try:
        if ":" in text:
            start, end, step = map(float, text.split(":"))
            if not all(math.isfinite(v) for v in (start, end, step)) or step == 0:
                raise ValueError("finite range with nonzero step required")
            count = math.floor((end - start) / step + 1e-9) + 1
            if not 1 <= count <= limit:
                raise ValueError(f"range must contain 1–{limit} frames")
            values = [start + i * step for i in range(count)]
        else:
            values = [float(v) for v in text.split(",")]
        if not 1 <= len(values) <= limit or not all(math.isfinite(v) for v in values):
            raise ValueError(f"provide 1–{limit} finite frames")
        return values
    except (ValueError, OverflowError) as exc:
        raise CompanionError("INVALID_FRAMES", str(exc)) from exc


def displacement(previous, current, seconds):
    import numpy as np

    a = np.frombuffer(previous, dtype=np.float32).reshape(-1, 3)
    b = np.frombuffer(current, dtype=np.float32).reshape(-1, 3)
    if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        return {"comparable": False}
    distance = np.linalg.norm(b - a, axis=1)
    maximum = float(distance.max()) if len(distance) else 0.0
    return {
        "comparable": True,
        "moved_points": int(np.count_nonzero(distance > 1e-6)),
        "max_displacement": maximum,
        "max_average_speed": maximum / abs(seconds) if seconds else None,
        "scope": "corresponding point indices; requires stable point ordering; sampled interval speed",
    }


def validate_tracks(tracks):
    paths = [t["path"] for t in tracks]
    if len(paths) != len(set(paths)):
        raise CompanionError("DUPLICATE_TRACK", "A parameter may occur only once")
    for track in tracks:
        frames = [k["frame"] for k in track["keys"]]
        if any(a >= b for a, b in zip(frames, frames[1:], strict=False)):
            raise CompanionError("INVALID_KEYS", "Keyframes must be strictly increasing")
