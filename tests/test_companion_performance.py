"""Small CI timing gates plus deterministic checks for extra hot-path requests."""

from types import SimpleNamespace

import pytest

from houdini_companion.client import Client
from houdini_companion.core import CompanionError
from houdini_companion.registry import OperationSpec, PluginSpec, Registry
from scripts.benchmark_companion import compare

pytestmark = pytest.mark.performance


def test_warm_short_operation_needs_one_request(monkeypatch):
    client = Client(descriptor={})
    client.identity = {"session_id": "one", "scene_id": "scene"}
    calls = []

    def call(action, **fields):
        calls.append(action)
        return {"job_id": "one", "state": "succeeded", "result": {}}

    monkeypatch.setattr(client, "call", call)
    for _ in range(10):
        client.run("inspect", {})
    assert calls == ["submit_wait"] * 10


def test_stale_identity_is_not_replayed(monkeypatch):
    client = Client(descriptor={})
    client.identity = {"session_id": "one", "scene_id": "scene"}
    calls = []

    def call(action, **fields):
        calls.append(action)
        raise CompanionError("STALE_SCENE", "changed")

    monkeypatch.setattr(client, "call", call)
    with pytest.raises(CompanionError):
        client.run("batch", {"actions": []})
    assert calls == ["submit_wait"]
    assert client.identity is None


def test_dispatch_latency_budget(benchmark):
    op = OperationSpec(
        "test.echo",
        "read",
        {"type": "object", "properties": {}, "additionalProperties": False},
        lambda _ctx, _job: {},
    )
    registry = Registry([PluginSpec("test", "1", (op,))])
    context = SimpleNamespace(ledger=SimpleNamespace(checkpoint=lambda _jid: None))
    job = {"operation": "test.echo", "params": {}, "job_id": "one"}

    def workload():
        for _ in range(1000):
            registry.dispatch(context, job)

    benchmark.pedantic(workload, rounds=10, warmup_rounds=2)
    # One thousand empty dispatches should consume far less than a UI tick each.
    # Generous CI ceiling catches blocking/I/O accidentally entering dispatch.
    assert benchmark.stats["median"] < 0.1


def test_baseline_gate_detects_regression_and_rejects_mismatched_hosts():
    baseline = {"environment": {"host": "one"}, "metrics": {"inspect": {"p95_ms": 100}}}
    assert not compare(
        {"environment": {"host": "one"}, "metrics": {"inspect": {"p95_ms": 110}}}, baseline
    )
    assert compare(
        {"environment": {"host": "one"}, "metrics": {"inspect": {"p95_ms": 160}}}, baseline
    )
    with pytest.raises(ValueError):
        compare({"environment": {"host": "other"}}, baseline)
