"""Exercise the companion against owned geometry in the existing UI session.

Never opens/saves a HIP or changes the town. Retains JSON and PNG evidence under
the companion artifact directory. Run using external Python, not hython.
"""

from __future__ import annotations

import json
import statistics
import time
import uuid
from pathlib import Path

from houdini_companion.client import Client
from houdini_companion.core import atomic_json


def main():
    client = Client()
    health = client.call("health")
    evidence = {"capabilities": health["capabilities"], "checks": {}, "jobs": []}
    name = "__companion_test_" + uuid.uuid4().hex[:8]
    root = "/obj/" + name
    box = root + "/box"

    def run(operation, params, timeout=30):
        job = client.run(operation, params, timeout)
        evidence["jobs"].append(
            {
                "job_id": job["job_id"],
                "operation": operation,
                "state": job["state"],
                "queue_ms": job.get("queue_ms"),
                "execution_ms": job.get("execution_ms"),
            }
        )
        assert job["state"] == "succeeded", job
        return job

    def inspect_box():
        return run("inspect", {"path": box, "geometry": True})["result"]

    def set_box(value):
        token = inspect_box()["observation"]["token"]
        return run(
            "batch",
            {
                "actions": [{"op": "set", "path": box, "values": {"sizex": value}}],
                "expected": {box: token},
                "output": box,
                "feedback": False,
            },
        )

    cameras = [
        "/obj/town_cam",
        "/obj/town_street_cam",
        "/obj/town_wire_cam",
        "/obj/town_oblique_cam",
    ]
    camera_before = {
        p: run("inspect", {"path": p})["result"]["observation"]["token"] for p in cameras
    }
    created = False
    try:
        setup = run(
            "batch",
            {
                "actions": [
                    {"op": "create", "parent": "/obj", "type": "geo", "name": name, "as": "geo"},
                    {"op": "create", "parent": "$geo", "type": "box", "name": "box", "as": "box"},
                ],
                "output": "$box",
                "feedback": True,
                "resolution": 384,
            },
        )
        created = True
        assert "feedback_error" not in setup["result"], setup
        evidence["baseline_images"] = {
            "job_id": setup["job_id"],
            "images": setup["result"]["feedback"]["images"],
        }
        before = inspect_box()
        assert before["geometry"]["primitives"] == 6
        preview = run(
            "preview",
            {
                "path": box,
                "expected": before["observation"]["token"],
                "values": {"sizex": 2},
                "resolution": 384,
            },
        )
        assert inspect_box()["geometry"]["bounds"] == before["geometry"]["bounds"]
        evidence["checks"]["preview_preserves_live_geometry"] = True
        apply = run("apply_preview", {"preview_id": preview["job_id"], "feedback": False})
        assert inspect_box()["geometry"]["bounds"][1][0] == 1
        run("undo", {"job_id": apply["job_id"]})
        assert inspect_box()["geometry"]["bounds"] == before["geometry"]["bounds"]
        evidence["checks"]["apply_and_undo"] = True

        # A newer action must prevent an older targeted undo.
        old = set_box(1.2)
        new = set_box(1.4)
        conflict = client.run("undo", {"job_id": old["job_id"]})
        assert conflict["state"] == "failed" and conflict["error"]["code"] == "UNDO_CONFLICT", (
            conflict
        )
        run("undo", {"job_id": new["job_id"]})
        run("undo", {"job_id": old["job_id"]})
        evidence["checks"]["undo_conflict_preserves_newer_work"] = True

        stale = inspect_box()["observation"]["token"]
        newer = set_box(1.1)
        rejected = client.run(
            "batch",
            {
                "actions": [{"op": "set", "path": box, "values": {"sizex": 9}}],
                "expected": {box: stale},
                "feedback": False,
            },
        )
        assert rejected["state"] == "failed" and rejected["error"]["code"] == "STALE_INPUT", (
            rejected
        )
        run("undo", {"job_id": newer["job_id"]})
        evidence["checks"]["stale_edit_rejected"] = True

        # A duplicate request stays one operation even across independent clients.
        token = inspect_box()["observation"]["token"]
        params = {
            "actions": [{"op": "set", "path": box, "values": {"sizex": 1.5}}],
            "expected": {box: token},
            "feedback": False,
        }
        rid = uuid.uuid4().hex
        first = client.submit("batch", params, rid)
        second = Client().submit("batch", params, rid)
        assert first["job_id"] == second["job_id"]
        assert Client().wait(first["job_id"])["state"] == "succeeded"
        run("undo", {"job_id": first["job_id"]})
        evidence["checks"]["deduplication_and_reconnect"] = True

        # Watcher-driven invalidation, including a real external VEX include.
        observed_job = run("inspect", {"path": box})
        changed_job = set_box(1.25)
        assert client.call("job", job_id=observed_job["job_id"])["result"]["stale"]
        run("undo", {"job_id": changed_job["job_id"]})
        evidence["checks"]["automatic_scene_invalidation"] = True

        include_path = Path(health["capabilities"]["artifact_root"]) / "acceptance_source.h"
        include_path.write_text("vector companion_offset(vector p) { return p + set(0.25,0,0); }\n")
        wrangle = root + "/wrangle"
        expected_box = inspect_box()["observation"]["token"]
        expected_root = run("inspect", {"path": root})["result"]["observation"]["token"]
        snippet = '#include "' + include_path.as_posix() + '"\n@P=companion_offset(@P);'
        run(
            "batch",
            {
                "actions": [
                    {
                        "op": "create",
                        "parent": root,
                        "type": "attribwrangle",
                        "name": "wrangle",
                        "as": "w",
                    },
                    {"op": "connect", "path": "$w", "source": box, "input": 0},
                    {"op": "set", "path": "$w", "values": {"snippet": snippet}},
                ],
                "expected": {root: expected_root, box: expected_box},
                "output": "$w",
                "feedback": False,
            },
        )
        wrangle_obs = run("inspect", {"path": wrangle})
        source_preview = run(
            "preview",
            {
                "path": wrangle,
                "expected": wrangle_obs["result"]["observation"]["token"],
                "values": {"snippet": snippet + "\n@P*=2;"},
                "views": ["persp"],
                "resolution": 256,
            },
        )
        assert source_preview["result"]["staged_sources"]
        include_path.write_text("vector companion_offset(vector p) { return p + set(0.5,0,0); }\n")
        time.sleep(0.65)
        assert client.call("job", job_id=wrangle_obs["job_id"])["result"]["stale"]
        reject = client.run(
            "apply_preview", {"preview_id": source_preview["job_id"], "feedback": False}
        )
        assert reject["state"] == "failed" and reject["error"]["code"] == "STALE_INPUT", reject
        run("discard_preview", {"preview_id": source_preview["job_id"]})
        evidence["checks"]["source_staging_and_stale_apply"] = True

        # Roll back a partially executed supported batch on a later invalid parm.
        token = inspect_box()["observation"]["token"]
        failure = client.run(
            "batch",
            {
                "actions": [
                    {"op": "set", "path": box, "values": {"sizex": 7}},
                    {"op": "set", "path": box, "values": {"missing_parameter": 2}},
                ],
                "expected": {box: token},
                "feedback": False,
            },
        )
        assert failure["state"] == "failed" and failure["error"]["rollback"] == "undone", failure
        assert inspect_box()["geometry"]["bounds"] == before["geometry"]["bounds"]
        evidence["checks"]["partial_batch_rollback"] = True

        snapshot = run("snapshot", {"path": box, "resolution": 384})
        assert not snapshot["result"]["stale"]
        assert all(not image["suspect_blank_or_dark"] for image in snapshot["result"]["images"])
        evidence["checks"]["rendered_feedback"] = True
        evidence["preview_images"] = {
            "job_id": preview["job_id"],
            "images": preview["result"]["images"],
        }
        samples = []
        for _ in range(5):
            started = time.perf_counter()
            run("inspect", {"path": box})
            samples.append((time.perf_counter() - started) * 1000)
        evidence["inspect_roundtrip_ms"] = {
            "median": statistics.median(samples),
            "max": max(samples),
        }

        for path in cameras:
            assert (
                run("inspect", {"path": path})["result"]["observation"]["token"]
                == camera_before[path]
            )
        evidence["checks"]["user_cameras_preserved"] = True
    finally:
        if created:
            info = client.run("inspect", {"path": root})
            if info["state"] == "succeeded":
                run(
                    "batch",
                    {
                        "actions": [{"op": "delete", "path": root}],
                        "expected": {root: info["result"]["observation"]["token"]},
                        "feedback": False,
                    },
                )
        target = Path(health["capabilities"]["artifact_root"]) / "acceptance.json"
        atomic_json(target, evidence)
        print(json.dumps({"evidence": str(target), "checks": evidence["checks"]}))


if __name__ == "__main__":
    main()
