"""Exercise companion feedback on an existing frozen building review specimen."""

import argparse
import json
import uuid
from pathlib import Path

from houdini_companion.client import Client
from houdini_companion.core import atomic_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("geometry", type=Path)
args = parser.parse_args()
if not args.geometry.is_file():
    parser.error("Geometry file does not exist")
client = Client()
root = "/obj/__companion_review_" + uuid.uuid4().hex[:8]
job = client.run(
    "batch",
    {
        "actions": [
            {
                "op": "create",
                "parent": "/obj",
                "type": "geo",
                "name": root.split("/")[-1],
                "as": "geo",
            },
            {"op": "flags", "path": "$geo", "display": False},
            {"op": "create", "parent": "$geo", "type": "file", "name": "building", "as": "file"},
            {"op": "set", "path": "$file", "values": {"file": args.geometry.resolve().as_posix()}},
        ],
        "output": "$file",
        "views": ["front", "right", "persp"],
        "resolution": 900,
    },
    timeout=30,
)
try:
    assert job["state"] == "succeeded", job
    assert "feedback_error" not in job["result"], job
    feedback = job["result"]["feedback"]
    assert feedback["geometry"]["primitives"] > 0
    assert feedback["geometry"]["checks"]["zero_area_count"] == 0
    assert feedback["geometry"]["checks"]["nonfinite_point_count"] == 0
    assert all(not item["suspect_blank_or_dark"] for item in feedback["images"])
    directory = Path(client.call("health")["capabilities"]["artifact_root"])
    atomic_json(directory / "building-review.json", job)
    print(
        json.dumps(
            {
                "job_id": job["job_id"],
                "geometry": feedback["geometry"],
                "images": [str(directory / job["job_id"] / i["name"]) for i in feedback["images"]],
                "render_ms": feedback["render_ms"],
            }
        )
    )
finally:
    observation = client.run("inspect", {"path": root})
    if observation["state"] == "succeeded":
        cleanup = client.run(
            "batch",
            {
                "actions": [{"op": "delete", "path": root}],
                "expected": {root: observation["result"]["observation"]["token"]},
                "feedback": False,
            },
        )
        assert cleanup["state"] == "succeeded", cleanup
