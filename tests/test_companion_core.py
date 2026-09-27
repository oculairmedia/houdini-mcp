"""Protocol failure cases: these tests require no Houdini installation."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from houdini_companion.core import CompanionError, Ledger


def request(ledger, rid="one", **changes):
    return {
        "version": 1,
        "session_id": ledger.session_id,
        "scene_id": ledger.scene_id,
        "request_id": rid,
        "operation": "inspect",
        "params": {},
        **changes,
    }


def test_duplicate_request_never_executes_twice(tmp_path):
    ledger = Ledger(tmp_path)
    payload = request(ledger)
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: ledger.submit(payload), range(32)))
    assert len({j["job_id"] for j in jobs}) == 1
    assert len(ledger.queue) == 1
    job = ledger.take()
    assert ledger.take() is None
    ledger.finish(job["job_id"], {"executions": 1})
    assert ledger.submit(payload)["result"] == {"executions": 1}
    assert ledger.take() is None


def test_reused_id_with_different_payload_is_rejected(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.submit(request(ledger))
    with pytest.raises(CompanionError, match="different content"):
        ledger.submit(request(ledger, params={"path": "/obj"}))


def test_full_queue_preserves_accepted_mutations(tmp_path):
    ledger = Ledger(tmp_path, queue_limit=1)
    first = ledger.submit(request(ledger, operation="batch", params={"actions": []}))
    with pytest.raises(CompanionError) as exc:
        ledger.submit(request(ledger, "two"))
    assert exc.value.code == "QUEUE_FULL"
    assert ledger.take()["job_id"] == first["job_id"]


def test_queue_cancel_frees_capacity_and_preserves_receipt(tmp_path):
    ledger = Ledger(tmp_path, queue_limit=1)
    first = ledger.submit(request(ledger))
    assert ledger.cancel(first["job_id"])["state"] == "cancelled"
    ledger.submit(request(ledger, "two"))
    assert ledger.take()["request_id"] == "two"
    assert ledger.submit(request(ledger))["state"] == "cancelled"


@pytest.mark.parametrize(
    "operation,params",
    [
        ("snapshot", {}),
        ("snapshot", {"path": "/obj/geo/box", "resolution": True}),
        ("snapshot", {"path": "/obj/geo/box", "resolution": 2000}),
        ("inspect", {"typo": True}),
        ("execute", {"code": []}),
    ],
)
def test_invalid_parameters_are_rejected_before_acceptance(tmp_path, operation, params):
    ledger = Ledger(tmp_path)
    with pytest.raises(CompanionError) as exc:
        ledger.submit(request(ledger, operation=operation, params=params))
    assert exc.value.code == "INVALID_PARAMS"
    assert not ledger.queue
    assert not ledger.requests


def test_running_cancel_does_not_claim_to_kill_operation(tmp_path):
    ledger = Ledger(tmp_path)
    job = ledger.submit(request(ledger))
    ledger.take()
    result = ledger.cancel(job["job_id"])
    assert result["state"] == "running"
    assert result["cancel_requested"]
    with pytest.raises(CompanionError, match="between phases"):
        ledger.checkpoint(job["job_id"])
    with pytest.raises(CompanionError, match="active operation"):
        ledger.stop()


def test_scene_replacement_cancels_queue_and_rejects_old_identity(tmp_path):
    ledger = Ledger(tmp_path)
    old = request(ledger)
    job = ledger.submit(old)
    ledger.new_scene()
    assert ledger.get(job["job_id"])["state"] == "cancelled"
    with pytest.raises(CompanionError) as exc:
        ledger.submit({**old, "request_id": "new"})
    assert exc.value.code == "STALE_SCENE"


def test_history_eviction_never_forgets_deduplication(tmp_path):
    ledger = Ledger(tmp_path, history_limit=1)
    old = request(ledger)
    job = ledger.submit(old)
    ledger.take()
    ledger.finish(job["job_id"], {"value": 1})
    ledger.submit(request(ledger, "two"))
    with pytest.raises(CompanionError) as exc:
        ledger.submit(old)
    assert exc.value.code == "RESULT_EXPIRED"
    assert len(ledger.queue) == 1


def test_receipt_excludes_submitted_source_and_is_readable(tmp_path):
    ledger = Ledger(tmp_path)
    job = ledger.submit(request(ledger, operation="execute", params={"code": "private-source"}))
    ledger.take()
    ledger.finish(job["job_id"], {"ok": True})
    path = tmp_path / job["job_id"] / "job.json"
    text = path.read_text()
    assert "private-source" not in text
    assert json.loads(text)["state"] == "succeeded"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"version": 99}, "PROTOCOL_MISMATCH"),
        ({"session_id": "old"}, "STALE_SESSION"),
        ({"operation": "save_hip"}, "INVALID_OPERATION"),
        ({"params": []}, "INVALID_OPERATION"),
        ({"request_id": ""}, "INVALID_REQUEST"),
        ({"extra": True}, "INVALID_REQUEST"),
    ],
)
def test_invalid_protocol_rejected_without_queueing(tmp_path, changes, code):
    ledger = Ledger(tmp_path)
    with pytest.raises(CompanionError) as exc:
        ledger.submit(request(ledger, **changes))
    assert exc.value.code == code
    assert not ledger.queue


def test_event_cursor_gap_is_explicit(tmp_path):
    ledger = Ledger(tmp_path)
    for i in range(600):
        ledger.event("test", index=i)
    result = ledger.poll(0)
    assert result["gap"]
    assert len(result["events"]) == 512
    assert ledger.poll(result["cursor"])["events"] == []


def test_public_job_copy_cannot_mutate_ledger(tmp_path):
    ledger = Ledger(tmp_path)
    job = ledger.submit(request(ledger))
    job["state"] = "succeeded"
    assert ledger.get(job["job_id"])["state"] == "queued"


def test_stop_cancels_queued_jobs(tmp_path):
    ledger = Ledger(tmp_path)
    job = ledger.submit(request(ledger))
    ledger.stop()
    assert ledger.get(job["job_id"])["state"] == "cancelled"
    with pytest.raises(CompanionError) as exc:
        ledger.submit(request(ledger, "new"))
    assert exc.value.code == "STOPPED"
