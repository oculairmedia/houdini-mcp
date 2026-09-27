"""Disposable live test of typed animation, temporal evidence, rejection and restore."""

import json
import uuid
from pathlib import Path

from houdini_companion.client import Client


def main():
    c = Client()
    name = "__temporal_test_" + uuid.uuid4().hex[:8]
    root = "/obj/" + name

    def run(op, params):
        result = c.run(op, params, timeout=1)
        while result["state"] in {"queued", "running"}:
            result = c.wait(result["job_id"], timeout=10)
        if result["state"] != "succeeded":
            raise RuntimeError(result)
        return result["result"]

    before = run("timeline.inspect", {})["time"]
    try:
        run(
            "batch",
            {
                "actions": [
                    {"op": "create", "parent": "/obj", "type": "geo", "name": name, "as": "geo"},
                    {"op": "flags", "path": "$geo", "display": False},
                    {"op": "create", "parent": "$geo", "type": "box", "name": "box", "as": "box"},
                    {
                        "op": "create",
                        "parent": "$geo",
                        "type": "xform",
                        "name": "motion",
                        "as": "motion",
                    },
                    {"op": "connect", "path": "$motion", "input": 0, "source": "$box"},
                ],
                "feedback": False,
            },
        )
        path = root + "/motion"
        obs = run("timeline.inspect", {"path": path})["observation"]
        authored = run(
            "animation.keyframes",
            {
                "tracks": [
                    {
                        "path": path + "/tx",
                        "keys": [{"frame": 1, "value": 0}, {"frame": 25, "value": 2}],
                    }
                ],
                "expected": {path: obs["token"]},
            },
        )
        keyed_before = run("timeline.inspect", {"path": path})
        replacement = run(
            "animation.keyframes",
            {
                "tracks": [
                    {
                        "path": path + "/tx",
                        "keys": [{"frame": 1, "value": -2}, {"frame": 25, "value": 6}],
                    }
                ],
                "expected": {path: keyed_before["observation"]["token"]},
            },
        )
        run("animation.restore", {"animation_id": replacement["animation_id"]})
        assert run("timeline.inspect", {"path": path})["channels"] == keyed_before["channels"]
        evidence = run(
            "timeline.sample",
            {
                "path": path,
                "frames": [1, 13, 25, 13, 1.5],
                "resolution": 256,
                "require_motion": True,
                "max_speed": 3,
                "max_cook_ms": 1000,
            },
        )
        assert evidence["accepted"], evidence
        assert evidence["repeated_frame_checks"] == 1
        assert evidence["topology_stable"]
        assert evidence["original_time"] == evidence["time_after"] == before
        static = run(
            "timeline.sample",
            {"path": root + "/box", "frames": [1, 25], "resolution": 256, "require_motion": True},
        )
        assert not static["accepted"] and {"code": "NO_MOTION"} in static["reasons"]
        run("animation.restore", {"animation_id": authored["animation_id"]})
        restored = run("timeline.inspect", {"path": path})
        assert not restored["channels"]
        assert restored["time"] == before
        # Reproduce a wrangle cooked before its referenced control exists.
        token = run("timeline.inspect", {"path": root})["observation"]["token"]
        box_token = run("timeline.inspect", {"path": root + "/box"})["observation"]["token"]
        run(
            "batch",
            {
                "actions": [
                    {
                        "op": "create",
                        "parent": root,
                        "type": "attribwrangle",
                        "name": "binding",
                        "as": "w",
                    },
                    {
                        "op": "set",
                        "path": "$w",
                        "values": {"class": 2, "snippet": '@P.x += chf("drive");'},
                    },
                    {"op": "connect", "path": "$w", "input": 0, "source": root + "/box"},
                ],
                "expected": {root: token, root + "/box": box_token},
                "output": "$w",
                "feedback": False,
            },
        )
        binding = root + "/binding"
        token = run("timeline.inspect", {"path": binding})["observation"]["token"]
        control = run(
            "animation.control",
            {"path": binding, "name": "drive", "label": "Drive", "expected": token},
        )
        assert control["vex_bindings_refreshed"]
        run(
            "animation.keyframes",
            {
                "tracks": [
                    {
                        "path": binding + "/drive",
                        "keys": [{"frame": 1, "value": 0}, {"frame": 25, "value": 2}],
                    }
                ],
                "expected": {binding: control["observation"]["token"]},
            },
        )
        binding_review = run(
            "timeline.sample",
            {"path": binding, "frames": [1, 13, 25], "resolution": 256, "require_motion": True},
        )
        assert binding_review["accepted"], binding_review
        report = {
            "passed": True,
            "animation": authored,
            "temporal": evidence,
            "static_rejection": static,
            "restored": True,
            "late_control_binding": binding_review,
        }
        output = Path.home() / ".houdini-companion/time-spike/fixture.json"
        output.parent.mkdir(exist_ok=True, parents=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "report": str(output), "cook_ms": evidence["cook_ms"]}))
    finally:
        # Only this uniquely named test container belongs to the fixture.
        run(
            "execute",
            {"code": f"n=hou.node({root!r})\nif n:n.destroy()\nresult={{'removed':{root!r}}}"},
        )


if __name__ == "__main__":
    main()
