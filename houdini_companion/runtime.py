"""Houdini lifecycle and hwebserver adapter; no HOM calls on HTTP threads."""

from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import traceback
import uuid
from pathlib import Path

from .core import CompanionError, Ledger, atomic_json
from .registry import load_registry

_runtime = None


def home():
    return Path(
        os.environ.get("HOUDINI_COMPANION_HOME", str(Path.home() / ".houdini-companion"))
    ).resolve()


class Runtime:
    def __init__(self, hou, port):
        from .operations import Operations
        from .watchers import Watchers

        self.hou = hou
        self.port = port
        self.token = secrets.token_urlsafe(32)
        modules = [
            s.strip()
            for s in os.environ.get("HOUDINI_COMPANION_PLUGINS", "").split(",")
            if s.strip()
        ]
        self.registry = load_registry(modules)
        self.wait_slots = threading.BoundedSemaphore(2)
        self.ledger = Ledger(home() / "artifacts" / uuid.uuid4().hex, registry=self.registry)
        self.operations = Operations(hou, self.ledger, self.registry)
        self.watchers = Watchers(hou, self.ledger)
        self.server = None
        self.stopping = False
        self.descriptor = home() / "sessions" / f"{os.getpid()}.json"
        self.capabilities = {
            "houdini": hou.applicationVersionString(),
            "pid": os.getpid(),
            "ui": hou.isUIAvailable(),
            "transport": "hwebserver-http",
            "renderer": "opengl" if "opengl" in hou.ropNodeTypeCategory().nodeTypes() else None,
            "preview_scope": "built-in leaf SOP, frozen direct inputs, quoted source includes",
            "python_execution": "trusted, unsandboxed",
            "cancellation": "queued immediately; running at phase boundaries",
            "artifact_root": str(self.ledger.root),
            "bounded_job_wait": True,
        }
        self.tick_callback = self.tick
        self.hip_callback = self.hip_event

    def start(self):
        import hwebserver

        if threading.current_thread() is not threading.main_thread():
            raise CompanionError("MAIN_THREAD_REQUIRED", "Start through Houdini's UI thread")
        self.server = hwebserver.Server("houdini_companion_" + self.ledger.session_id)
        self.server.urlHandler("/companion/v1")(self.http)
        # Explicit server object: do not stop or reconfigure Houdini's help server.
        self.server.setPortInfo(
            "main",
            self.port,
            self.port,
            False,
            "127.0.0.1",
            False,
            ["127.0.0.1", "localhost"],
            False,
        )
        self.server.run(
            port=self.port,
            in_background=True,
            reload_source_changes=False,
            max_request_size=512 * 1024,
            max_num_threads=4,
        )
        self.hou.ui.addEventLoopCallback(self.tick_callback)
        self.hou.hipFile.addEventCallback(self.hip_callback)
        atomic_json(
            self.descriptor,
            {
                "url": f"http://127.0.0.1:{self.port}/companion/v1",
                "token": self.token,
                "pid": os.getpid(),
                "session_id": self.ledger.session_id,
                "artifact_root": str(self.ledger.root),
            },
        )
        try:
            self.descriptor.chmod(0o600)
        except OSError:
            pass
        return {**self.ledger.status(), "capabilities": self.capabilities}

    def http(self, request):
        import hwebserver

        try:
            peer = request.clientAddress()[0]
            if not ipaddress.ip_address(peer).is_loopback:
                raise CompanionError("FORBIDDEN", "Only local clients are supported")
            headers = {str(k).lower(): str(v) for k, v in request.headers().items()}
            if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + self.token):
                raise CompanionError("UNAUTHORIZED", "Companion token required")
            if request.method() != "POST":
                raise CompanionError("METHOD", "POST required")
            raw = request.body()
            if len(raw) > 512 * 1024:
                raise CompanionError("REQUEST_LIMIT", "Request exceeds 512 KB")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise CompanionError("INVALID_REQUEST", "JSON object required")
            result = self.handle(payload)
            return hwebserver.Response(
                json.dumps({"ok": True, "result": result}, allow_nan=False),
                content_type="application/json",
            )
        except CompanionError as exc:
            return hwebserver.Response(
                json.dumps({"ok": False, "error": exc.as_dict()}),
                status=400,
                content_type="application/json",
            )
        except Exception as exc:
            return hwebserver.Response(
                json.dumps(
                    {"ok": False, "error": {"code": "INVALID_REQUEST", "message": str(exc)}}
                ),
                status=400,
                content_type="application/json",
            )

    def handle(self, payload):
        action = payload.get("action")
        if action == "schema":
            return {"version": 1, **self.operations.registry.catalog()}
        if action == "health":
            return {**self.ledger.status(), "capabilities": self.capabilities}
        if action in {"submit", "submit_wait"}:
            seconds = payload.get("wait_seconds", 0)
            if type(seconds) not in (int, float) or not 0 <= seconds <= 1:
                raise CompanionError("INVALID_WAIT", "wait_seconds must be 0 to 1")
            job = self.ledger.submit(payload["request"])
            if action == "submit_wait" and seconds and self.wait_slots.acquire(blocking=False):
                try:
                    return self.ledger.wait(job["job_id"], seconds)
                finally:
                    self.wait_slots.release()
            return job
        if action == "wait_job":
            seconds = payload.get("wait_seconds", 0)
            if type(seconds) not in (int, float) or not 0 <= seconds <= 1:
                raise CompanionError("INVALID_WAIT", "wait_seconds must be 0 to 1")
            job = self.handle({"action": "job", "job_id": payload["job_id"]})
            if job.get("archived") or not seconds or not self.wait_slots.acquire(blocking=False):
                return job
            try:
                return self.ledger.wait(job["job_id"], seconds)
            finally:
                self.wait_slots.release()
        if action == "job":
            jid = payload["job_id"]
            try:
                return self.ledger.get(jid)
            except CompanionError:
                if not isinstance(jid, str) or not re.fullmatch(r"[0-9a-f]{32}", jid):
                    raise CompanionError("JOB_NOT_FOUND", "Invalid job id") from None
                for path in (home() / "artifacts").glob(f"*/{jid}/job.json"):
                    job = json.loads(path.read_text(encoding="utf-8"))
                    job["archived"] = True
                    if isinstance(job.get("result"), dict):
                        job["result"]["stale"] = True
                        job["result"]["stale_reason"] = (
                            "Historical result from a previous runtime session"
                        )
                    if job["state"] in {"queued", "running"}:
                        job.update(
                            state="interrupted",
                            error={
                                "code": "SESSION_ENDED",
                                "message": "Previous session ended; scene consistency is unknown. Do not replay automatically.",
                            },
                        )
                    return job
                raise CompanionError("JOB_NOT_FOUND", "No retained receipt") from None
        if action == "cancel":
            return self.ledger.cancel(payload["job_id"])
        if action == "jobs":
            with self.ledger.lock:
                return [self.ledger.get(jid) for jid in reversed(self.ledger.jobs)]
        if action == "events":
            return self.ledger.poll(int(payload.get("cursor", 0)))
        if action == "artifact":
            jid, name = payload["job_id"], payload["name"]
            self.handle({"action": "job", "job_id": jid})
            if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
                raise CompanionError("INVALID_ARTIFACT", "A basename is required")
            directory = self.ledger.root / jid
            if not directory.is_dir():
                receipts = list((home() / "artifacts").glob(f"*/{jid}/job.json"))
                if receipts:
                    directory = receipts[0].parent
            path = (directory / name).resolve()
            if (
                path.parent != directory.resolve()
                or not path.is_relative_to(home() / "artifacts")
                or not path.is_file()
            ):
                raise CompanionError("ARTIFACT_NOT_FOUND", "Artifact is unavailable")
            if path.stat().st_size > 12 * 1024 * 1024:
                raise CompanionError("ARTIFACT_LIMIT", "Artifact exceeds inline transfer limit")
            return {"name": name, "data": base64.b64encode(path.read_bytes()).decode()}
        if action == "stop":
            # The UI callback owns shutdown; HTTP requests never call HOM.
            if self.ledger.active:
                raise CompanionError("BUSY", "Wait for the active operation before stopping")
            self.ledger.stop()
            self.stopping = True
            return {"stopping": True}
        raise CompanionError("UNKNOWN_ACTION", "Unsupported service action")

    def tick(self):
        if self.stopping:
            self.stop()
            return
        self.watchers.poll()
        job = self.ledger.take()
        if job is None:
            return
        jid = job["job_id"]
        try:
            result = self.operations.execute(job)
            try:
                self.watchers.track(result)
            except Exception as exc:
                self.ledger.event("awareness.error", message=str(exc))
            # Publish completion only after observations are registered. A fast
            # client can edit a source immediately after receiving the result.
            self.ledger.finish(jid, result=result)
        except CompanionError as exc:
            self.ledger.finish(jid, error=exc.as_dict())
        except Exception as exc:
            self.ledger.finish(
                jid,
                error={
                    "code": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc()[-6000:],
                },
            )
        try:
            self.cleanup()
        except Exception as exc:
            self.ledger.event("cleanup.error", message=str(exc))

    def hip_event(self, event):
        if event in {self.hou.hipFileEventType.BeforeLoad, self.hou.hipFileEventType.BeforeClear}:
            self.ledger.new_scene()
            self.watchers.clear()
            self.operations.reset()

    def cleanup(self, keep=64, byte_limit=1024 * 1024 * 1024):
        # Only our current session's completed job directories are eligible.
        root = self.ledger.root.resolve()
        directories = []
        with self.ledger.lock:
            protected = set(self.operations.previews) | {self.ledger.active}
            protected.update(self.operations.state.get("iteration", {}))
            protected.update(
                v["source_cache"]
                for v in self.operations.state.get("iteration", {}).values()
                if "source_cache" in v
            )
            protected.update(
                j for j, v in self.ledger.jobs.items() if v["state"] in {"queued", "running"}
            )
            for directory in root.iterdir():
                if (
                    directory.is_dir()
                    and directory.resolve().parent == root
                    and (directory / "job.json").is_file()
                ):
                    size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
                    directories.append((directory, size))
            directories.sort(key=lambda item: item[0].stat().st_mtime, reverse=True)
            total = sum(size for _, size in directories)
            for index, (directory, size) in reversed(list(enumerate(directories))):
                if index < keep and total <= byte_limit:
                    continue
                if directory.name in protected:
                    continue
                # Preserve the small job receipt; remove only generated artifacts.
                for path in directory.iterdir():
                    if (
                        path.is_file()
                        and path.name
                        not in {
                            "job.json",
                            "transaction.json",
                            "stage-transaction.json",
                            "iteration.json",
                            "animation-transaction.json",
                            "sequence.json",
                        }
                        and path.resolve().parent == directory.resolve()
                    ):
                        path.unlink()
                total -= size

    def stop(self):
        global _runtime
        self.ledger.stop()
        self.watchers.clear()
        self.hou.ui.removeEventLoopCallback(self.tick_callback)
        self.hou.hipFile.removeEventCallback(self.hip_callback)
        if self.server:
            self.server.requestShutdown()
        if self.descriptor.exists():
            saved = json.loads(self.descriptor.read_text())
            if saved.get("session_id") == self.ledger.session_id:
                self.descriptor.unlink()
        self.operations.previews.clear()
        if _runtime is self:
            _runtime = None


def start(port=None):
    global _runtime
    if _runtime is not None:
        return {**_runtime.ledger.status(), "capabilities": _runtime.capabilities}
    import hou

    if not hou.isUIAvailable():
        raise CompanionError("UI_REQUIRED", "This companion release targets interactive Houdini")
    runtime = Runtime(hou, int(port or os.environ.get("HOUDINI_COMPANION_PORT", "18812")))
    result = runtime.start()
    _runtime = runtime
    return result


def stop():
    if _runtime:
        _runtime.stop()


def reload_runtime():
    import importlib
    import sys

    from . import (
        core,
        diagnostics,
        errors,
        observation,
        operations,
        plugins,
        registry,
        rendering,
        schema,
        temporal,
        transactions,
        watchers,
    )
    from .plugins import (
        acceptance,
        animation,
        execution,
        introspection,
        iteration,
        query,
        review,
        scene,
        timeline,
    )

    stop()
    for module in (
        errors,
        schema,
        registry,
        core,
        observation,
        rendering,
        diagnostics,
        transactions,
        temporal,
        plugins,
        query,
        scene,
        review,
        execution,
        introspection,
        acceptance,
        iteration,
        animation,
        timeline,
        operations,
        watchers,
    ):
        importlib.reload(module)
    module = importlib.reload(sys.modules[__name__])
    return module.start()


def instance():
    return _runtime
