"""Thread-safe job ledger and protocol, independent of Houdini and transport."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict, deque
from pathlib import Path

from . import PROTOCOL_VERSION
from .errors import CompanionError
from .schema import validate

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
OPERATIONS = {
    "inspect": "read",
    "validate_observation": "read",
    "snapshot": "artifacts",
    "batch": "scene",
    "execute": "code",
    "undo": "scene",
    "preview": "preview",
    "apply_preview": "scene",
    "discard_preview": "preview",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


class Ledger:
    """Only the UI dispatcher executes jobs; HTTP threads only access this ledger.

    Retired request ids are kept for the lifetime of a session. At the hard request
    limit we reject submissions, rather than silently forgetting deduplication keys.
    """

    def __init__(self, root, queue_limit=32, history_limit=256, request_limit=10000, registry=None):
        self.registry = registry
        self.root = Path(root)
        self.session_id = uuid.uuid4().hex
        self.scene_id = uuid.uuid4().hex
        self.queue_limit = queue_limit
        self.history_limit = history_limit
        self.request_limit = request_limit
        self.jobs = OrderedDict()
        self.requests = {}
        self.queue = deque()
        self.events = deque(maxlen=512)
        self.sequence = 0
        self.active = None
        self.accepting = True
        self.last_tick = time.time()
        self.lock = threading.RLock()
        self.completed = threading.Condition(self.lock)
        self.root.mkdir(parents=True, exist_ok=True)

    def event(self, kind, **fields):
        with self.lock:
            self.sequence += 1
            self.events.append(
                {"cursor": self.sequence, "time": time.time(), "kind": kind, **fields}
            )

    def submit(self, request):
        with self.lock:
            if not isinstance(request, dict) or set(request) - {
                "version",
                "session_id",
                "scene_id",
                "request_id",
                "operation",
                "params",
            }:
                raise CompanionError("INVALID_REQUEST", "Unknown request fields or invalid object")
            if request.get("version") != PROTOCOL_VERSION:
                raise CompanionError("PROTOCOL_MISMATCH", "Protocol version 1 required")
            if request.get("session_id") != self.session_id:
                raise CompanionError("STALE_SESSION", "Reconnect to the current companion")
            rid = request.get("request_id")
            if not isinstance(rid, str) or not 1 <= len(rid) <= 128:
                raise CompanionError("INVALID_REQUEST", "request_id must be 1–128 characters")
            signature = digest(request)
            if rid in self.requests:
                previous, jid = self.requests[rid]
                if previous != signature:
                    raise CompanionError(
                        "REQUEST_CONFLICT", "Request id reused with different content"
                    )
                if jid not in self.jobs:
                    raise CompanionError(
                        "RESULT_EXPIRED", "Already executed; result retired", job_id=jid
                    )
                return self.get(jid)
            if not self.accepting:
                raise CompanionError("STOPPED", "Companion is stopping")
            if request.get("scene_id") != self.scene_id:
                raise CompanionError("STALE_SCENE", "Scene was replaced; inspect it again")
            if request.get("operation") not in (
                self.registry.effects() if self.registry else OPERATIONS
            ) or not isinstance(request.get("params", {}), dict):
                raise CompanionError("INVALID_OPERATION", "Unsupported operation or parameters")
            validator = self.registry.validate if self.registry else validate
            validator(request["operation"], request.get("params", {}))
            if len(self.queue) >= self.queue_limit:
                raise CompanionError("QUEUE_FULL", "Queue is full; no job was accepted")
            if len(self.requests) >= self.request_limit:
                raise CompanionError(
                    "SESSION_LIMIT", "Request ledger full; restart the idle companion"
                )
            while len(self.jobs) >= self.history_limit:
                old = next((k for k, v in self.jobs.items() if v["state"] in TERMINAL), None)
                if old is None:
                    raise CompanionError("HISTORY_FULL", "No completed jobs can be retired")
                del self.jobs[old]
            jid = uuid.uuid4().hex
            job = {
                "job_id": jid,
                "request_id": rid,
                "session_id": self.session_id,
                "scene_id": self.scene_id,
                "operation": request["operation"],
                "params": copy.deepcopy(request.get("params", {})),
                "state": "queued",
                "phase": "queued",
                "submitted_at": time.time(),
                "cancel_requested": False,
            }
            self.jobs[jid] = job
            self.requests[rid] = (signature, jid)
            self.queue.append(jid)
            self._save(job)
            self.event("job.queued", job_id=jid)
            return self.get(jid)

    def _save(self, job):
        # Don't persist arbitrary source code or parameter values in the receipt.
        atomic_json(
            self.root / job["job_id"] / "job.json", {k: v for k, v in job.items() if k != "params"}
        )

    def get(self, jid):
        with self.lock:
            if jid not in self.jobs:
                raise CompanionError("JOB_NOT_FOUND", "Job is not retained in this session")
            return copy.deepcopy({k: v for k, v in self.jobs[jid].items() if k != "params"})

    def take(self):
        with self.lock:
            self.last_tick = time.time()
            if self.active or not self.accepting:
                return None
            while self.queue:
                job = self.jobs[self.queue.popleft()]
                if job["state"] != "queued":
                    continue
                if job["scene_id"] != self.scene_id:
                    self.finish(
                        job["job_id"], error={"code": "STALE_SCENE", "message": "Scene replaced"}
                    )
                    continue
                self.active = job["job_id"]
                job.update(state="running", phase="executing", started_at=time.time())
                job["queue_ms"] = round((job["started_at"] - job["submitted_at"]) * 1000, 2)
                self._save(job)
                self.event("job.running", job_id=job["job_id"])
                return copy.deepcopy(job)
            return None

    def phase(self, jid, phase):
        with self.lock:
            self.jobs[jid]["phase"] = phase
            self.event("job.phase", job_id=jid, phase=phase)

    def finish(self, jid, result=None, error=None):
        with self.lock:
            job = self.jobs[jid]
            job.update(
                state="failed" if error else "succeeded", phase="complete", finished_at=time.time()
            )
            job["execution_ms"] = round(
                (job["finished_at"] - job.get("started_at", job["submitted_at"])) * 1000, 2
            )
            job["error" if error else "result"] = error if error else result
            if self.active == jid:
                self.active = None
            self._save(job)
            self.event("job.finished", job_id=jid, state=job["state"])
            self.completed.notify_all()

    def cancel(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            if job is None:
                raise CompanionError("JOB_NOT_FOUND", "Unknown job")
            if job["state"] == "queued":
                self.queue.remove(jid)
                job.update(state="cancelled", phase="complete", finished_at=time.time())
            elif job["state"] == "running":
                job["cancel_requested"] = True
                job["cancellation"] = (
                    "Requested; stops only between supported phases. A running cook cannot be killed."
                )
            self._save(job)
            self.event("job.cancel", job_id=jid, state=job["state"])
            self.completed.notify_all()
            return self.get(jid)

    def wait(self, jid, timeout):
        with self.completed:
            self.completed.wait_for(
                lambda: jid not in self.jobs or self.jobs[jid]["state"] in TERMINAL, timeout=timeout
            )
            return self.get(jid)

    def checkpoint(self, jid):
        with self.lock:
            if self.jobs[jid]["cancel_requested"]:
                raise CompanionError(
                    "CANCEL_REQUESTED", "Stopped between phases; completed edits may remain"
                )

    def new_scene(self):
        with self.lock:
            self.scene_id = uuid.uuid4().hex
            for jid in list(self.queue):
                self.cancel(jid)
            self.event("scene.replaced", scene_id=self.scene_id)

    def status(self):
        with self.lock:
            return {
                "version": PROTOCOL_VERSION,
                "session_id": self.session_id,
                "scene_id": self.scene_id,
                "accepting": self.accepting,
                "active_job": self.active,
                "queued": len(self.queue),
                "ui_last_tick_age_s": round(time.time() - self.last_tick, 3),
                "operations": self.registry.effects() if self.registry else OPERATIONS,
            }

    def poll(self, cursor=0):
        with self.lock:
            return {
                "cursor": self.sequence,
                "gap": bool(self.events and cursor < self.events[0]["cursor"] - 1),
                "events": [copy.deepcopy(e) for e in self.events if e["cursor"] > cursor],
            }

    def stop(self):
        with self.lock:
            if self.active:
                raise CompanionError("BUSY", "Wait for the active operation before stopping")
            self.accepting = False
            for jid in list(self.queue):
                self.cancel(jid)
