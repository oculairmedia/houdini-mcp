"""Auto-start the companion after Houdini's UI is ready (Houdini 20.5 / Python 3.11)."""

import os

if os.environ.get("HOUDINI_COMPANION_AUTOSTART", "1") == "1":
    try:
        from houdini_companion.runtime import start

        start()
    except Exception as exc:
        print(f"Houdini companion did not start: {exc}")
