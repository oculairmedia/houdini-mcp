"""Explicit point identity and image continuity, independent of point-index order."""

import numpy as np

from .errors import CompanionError


def compare_points(before_ids, before, after_ids, after, tolerance, allow_birth_death=False):
    if len(set(before_ids)) != len(before_ids) or len(set(after_ids)) != len(after_ids):
        raise CompanionError("DUPLICATE_ID", "Correspondence ids must be unique per point")
    left = dict(zip(before_ids, np.asarray(before, dtype=float), strict=True))
    right = dict(zip(after_ids, np.asarray(after, dtype=float), strict=True))
    if any(not np.isfinite(p).all() for p in [*left.values(), *right.values()]):
        raise CompanionError("NONFINITE_POINTS", "Cannot compare nonfinite positions")
    common = sorted(left.keys() & right.keys(), key=str)
    born, died = (
        sorted(right.keys() - left.keys(), key=str),
        sorted(left.keys() - right.keys(), key=str),
    )
    distances = [float(np.linalg.norm(right[k] - left[k])) for k in common]
    maximum = max(distances, default=0.0)
    reasons = []
    if not common:
        reasons.append("NO_CORRESPONDENCE")
    if maximum > tolerance:
        reasons.append("POSITION_JUMP")
    if (born or died) and not allow_birth_death:
        reasons.append("IDENTITY_SET_CHANGED")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "matched": len(common),
        "born_count": len(born),
        "died_count": len(died),
        "born_ids": born[:32],
        "died_ids": died[:32],
        "max_displacement": maximum,
        "tolerance": tolerance,
        "scope": "Declared point identity at two sampled times; no continuous-path proof",
    }


def compare_images(before, after):
    a, b = np.asarray(before, dtype=float), np.asarray(after, dtype=float)
    if a.shape != b.shape:
        raise CompanionError("IMAGE_SHAPE", "Aligned images require the same dimensions")
    delta = np.abs(a - b) / 255.0
    return {
        "mean_absolute_difference": float(delta.mean()),
        "changed_pixel_fraction": float(np.mean(np.max(delta, axis=-1) > 0.1)),
    }


def image_pixels(path):
    try:
        from PySide2.QtGui import QImage
    except ImportError:
        from PySide6.QtGui import QImage
    image = QImage(str(path)).convertToFormat(QImage.Format_RGBA8888)
    if image.isNull():
        raise CompanionError("IMAGE_DECODE", str(path))
    buffer = image.bits()
    if hasattr(buffer, "setsize"):
        buffer.setsize(image.sizeInBytes())
    return (
        np.frombuffer(buffer, dtype=np.uint8)
        .reshape(image.height(), image.width(), 4)[:, :, :3]
        .copy()
    )
