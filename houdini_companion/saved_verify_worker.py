"""Invoked only in a disposable hython process by save.verify."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    import hou

    from houdini_companion.core import atomic_json
    from houdini_companion.saved_scene import verify

    manifest, output = map(Path, sys.argv[1:3])
    try:
        result = verify(hou, json.loads(manifest.read_text(encoding="utf-8")))
    except Exception as exc:
        result = {"accepted": False, "reasons": [{"code": type(exc).__name__, "message": str(exc)}]}
    atomic_json(output, result)


if __name__ == "__main__":
    main()
