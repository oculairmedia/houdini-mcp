"""Read-only live latency gate. Baselines must come from the same host and target."""

import argparse
import json
import platform
import statistics
import time
from pathlib import Path

from houdini_companion.client import Client
from houdini_companion.core import atomic_json


def measure(function, samples):
    function()
    elapsed, queues, executions, sizes = [], [], [], []
    for _ in range(samples):
        start = time.perf_counter()
        result = function()
        elapsed.append((time.perf_counter() - start) * 1000)
        if "state" in result and result["state"] != "succeeded":
            raise RuntimeError(result)
        queues.append(result.get("queue_ms", 0))
        executions.append(result.get("execution_ms", 0))
        sizes.append(len(json.dumps(result).encode()))
    return {
        "p50_ms": statistics.median(elapsed),
        "p95_ms": sorted(elapsed)[int((samples - 1) * 0.95)],
        "queue_p50_ms": statistics.median(queues),
        "execution_p50_ms": statistics.median(executions),
        "max_response_bytes": max(sizes),
        "samples_ms": elapsed,
    }


def compare(report, baseline, ratio=1.35, noise_ms=20):
    if report["environment"] != baseline["environment"]:
        raise ValueError(
            "Baseline host/platform/Houdini/target mismatch; capture a matching baseline"
        )
    failures = []
    for name, previous in baseline["metrics"].items():
        if name not in report["metrics"]:
            failures.append(f"Missing baseline workload: {name}")
            continue
        ceiling = max(previous["p95_ms"] * ratio, previous["p95_ms"] + noise_ms)
        if report["metrics"][name]["p95_ms"] > ceiling:
            failures.append(f"{name}: p95 exceeds {ceiling:.2f} ms")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="Stable lightweight node, e.g. a camera")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if not 10 <= args.samples <= 200:
        parser.error("Use 10 to 200 samples")
    client = Client()
    health = client.call("health")
    environment = {
        "host": platform.node(),
        "platform": platform.platform(),
        "houdini": health["capabilities"]["houdini"],
        "path": args.path,
    }
    workloads = {
        "health": lambda: client.call("health"),
        "inspect": lambda: client.run("inspect", {"path": args.path}),
        "query.graph": lambda: client.run("query.graph", {"path": args.path, "limit": 32}),
        "query.parameters": lambda: client.run(
            "query.parameters", {"path": args.path, "pattern": "t*", "limit": 16}
        ),
    }
    report = {
        "environment": environment,
        "metrics": {name: measure(fn, args.samples) for name, fn in workloads.items()},
    }
    queries = [
        {
            "operation": "query.parameters",
            "params": {"path": args.path, "pattern": "t*", "limit": 16},
        }
    ] * 4
    report["metrics"]["query.batch_four"] = measure(
        lambda: client.run("query.batch", {"queries": queries}), args.samples
    )
    failures = []
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        # Process identity changes on restart; hardware and scene target must match.
        baseline["environment"].pop("pid", None)
        failures = compare(report, baseline)
    report.update(passed=not failures, regressions=failures)
    atomic_json(args.output, report)
    print(
        json.dumps(
            {
                "report": str(args.output),
                "passed": not failures,
                "metrics": {
                    k: {n: v for n, v in m.items() if n != "samples_ms"}
                    for k, m in report["metrics"].items()
                },
                "regressions": failures,
            }
        )
    )
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
