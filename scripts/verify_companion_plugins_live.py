"""Verify query/review plugins on an owned frozen building fixture; never save HIP."""

import argparse
import json
import time
import uuid
from pathlib import Path

from houdini_companion.client import Client
from houdini_companion.core import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geometry", type=Path)
    args = parser.parse_args()
    if not args.geometry.is_file():
        parser.error("Geometry specimen must exist")
    client = Client()
    directory = Path(client.call("health")["capabilities"]["artifact_root"])
    root = "/obj/__companion_plugins_" + uuid.uuid4().hex[:8]
    output = root + "/building"

    def run(op, params):
        job = client.run(op, params)
        assert job["state"] == "succeeded", job
        return job

    evidence = {}
    try:
        run(
            "batch",
            {
                "actions": [
                    {
                        "op": "create",
                        "parent": "/obj",
                        "type": "geo",
                        "name": root.split("/")[-1],
                        "as": "g",
                    },
                    {"op": "flags", "path": "$g", "display": False},
                    {"op": "create", "parent": "$g", "type": "file", "name": "building", "as": "f"},
                    {
                        "op": "set",
                        "path": "$f",
                        "values": {"file": args.geometry.resolve().as_posix()},
                    },
                ],
                "feedback": False,
            },
        )
        queries = [
            {"operation": "query.graph", "params": {"path": root}},
            {"operation": "query.parameters", "params": {"path": output, "pattern": "file*"}},
            {"operation": "query.node_types", "params": {"category": "Sop", "pattern": "box"}},
            {
                "operation": "query.geometry",
                "params": {"path": output, "attributes": ["P", "Cd"], "limit": 4},
            },
        ]
        start = time.perf_counter()
        for query in queries:
            run(query["operation"], query["params"])
        evidence["sequential_four_queries_ms"] = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        grouped = run("query.batch", {"queries": queries})
        evidence["grouped_four_queries_ms"] = (time.perf_counter() - start) * 1000
        assert len(grouped["result"]["results"]) == 4
        samples = grouped["result"]["results"][3]["result"]
        assert len(samples["points"]) == 4 and samples["total_points"] > 4
        assert samples["truncated"]
        rejected = client.run(
            "query.batch",
            {
                "queries": [
                    {
                        "operation": "execute",
                        "params": {"code": "raise Exception('must not execute')"},
                    }
                ]
            },
        )
        assert rejected["error"]["code"] == "READ_REQUIRED"
        review = run(
            "review.accept",
            {
                "path": output,
                "resolution": 640,
                "requirements": {
                    "min_points": 100,
                    "min_coverage": 0.05,
                    "required_point_attributes": ["P", "Cd"],
                    "max_warnings": 0,
                },
            },
        )
        assert review["result"]["accepted"], review
        assert len(review["result"]["receipt_hash"]) == 64
        failed_gate = run(
            "review.accept",
            {
                "path": output,
                "views": ["front"],
                "resolution": 128,
                "requirements": {"min_points": 10000000},
            },
        )
        assert not failed_gate["result"]["accepted"]
        delta = run(
            "review.compare", {"before_job": review["job_id"], "after_job": failed_gate["job_id"]}
        )
        assert delta["result"]["point_delta"] == 0
        evidence.update(
            passed=True,
            grouped_queries=grouped,
            accepted_review=review,
            rejected_review=failed_gate,
            comparison=delta,
            read_batch_rejects_mutations=True,
        )
    finally:
        observed = client.run("inspect", {"path": root})
        if observed["state"] == "succeeded":
            run(
                "batch",
                {
                    "actions": [{"op": "delete", "path": root}],
                    "expected": {root: observed["result"]["observation"]["token"]},
                    "feedback": False,
                },
            )
        atomic_json(directory / "plugin-acceptance.json", evidence)
    print(
        json.dumps(
            {
                "evidence": str(directory / "plugin-acceptance.json"),
                "passed": evidence.get("passed", False),
                "review_job": evidence["accepted_review"]["job_id"],
                "sequential_ms": evidence["sequential_four_queries_ms"],
                "grouped_ms": evidence["grouped_four_queries_ms"],
            }
        )
    )


if __name__ == "__main__":
    main()
