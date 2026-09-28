"""Standard-library client shared by the CLI and MCP adapters."""

from __future__ import annotations

import base64
import http.client
import json
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from . import PROTOCOL_VERSION
from .core import TERMINAL, CompanionError


class Client:
    def __init__(self, descriptor=None, pid=None, timeout=5):
        self.timeout = timeout
        self._connections = threading.local()
        self.identity = None
        if descriptor is None:
            root = Path(
                os.environ.get("HOUDINI_COMPANION_HOME", str(Path.home() / ".houdini-companion"))
            )
            paths = sorted((root / "sessions").glob(f"{pid or '*'}.json"))
            alive = []
            for path in paths:
                try:
                    candidate = json.loads(path.read_text())
                    self.descriptor = candidate
                    health = self.call("health")
                    if health["session_id"] == candidate["session_id"]:
                        alive.append(candidate)
                        self.identity = health
                except (OSError, ValueError, CompanionError):
                    continue
            if len(alive) != 1:
                raise CompanionError(
                    "DISCOVERY",
                    "Expected one live companion; start it in Houdini or specify --pid",
                    live_sessions=[d["pid"] for d in alive],
                )
            descriptor = alive[0]
        self.descriptor = descriptor

    def call(self, action, **fields):
        url = urlsplit(self.descriptor["url"])
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise CompanionError("TRANSPORT", "Companion URL must use local HTTP")
        endpoint = (url.hostname, url.port)
        connection = getattr(self._connections, "connection", None)
        if connection is None or getattr(self._connections, "endpoint", None) != endpoint:
            if connection:
                connection.close()
            connection = http.client.HTTPConnection(*endpoint, timeout=self.timeout)
            self._connections.connection, self._connections.endpoint = connection, endpoint
        try:
            connection.request(
                "POST",
                url.path,
                json.dumps({"action": action, **fields}),
                {
                    "Authorization": "Bearer " + self.descriptor["token"],
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            payload = json.loads(response.read())
        except (OSError, ValueError, http.client.HTTPException) as exc:
            connection.close()
            self._connections.connection = None
            raise CompanionError(
                "TRANSPORT",
                str(exc),
                retry_policy="Query the same job/request; never blindly replay a mutation",
            ) from exc
        if not payload.get("ok"):
            error = dict(payload["error"])
            raise CompanionError(error.pop("code"), error.pop("message"), **error)
        return payload["result"]

    def submit(self, operation, params=None, request_id=None, wait_seconds=0):
        health = self.identity or self.call("health")
        self.identity = health
        request = {
            "version": PROTOCOL_VERSION,
            "session_id": health["session_id"],
            "scene_id": health["scene_id"],
            "request_id": request_id or uuid.uuid4().hex,
            "operation": operation,
            "params": params or {},
        }
        try:
            if wait_seconds:
                return self.call("submit_wait", request=request, wait_seconds=wait_seconds)
            return self.call("submit", request=request)
        except CompanionError as exc:
            if exc.code in {"STALE_SESSION", "STALE_SCENE"}:
                self.identity = None
            exc.details["request"] = request
            raise

    def wait(self, job_id, timeout=30):
        deadline = time.monotonic() + timeout
        delay = 0.05
        job = self.call("job", job_id=job_id)
        while True:
            remaining = deadline - time.monotonic()
            if job["state"] in TERMINAL or remaining <= 0:
                return job
            if (self.identity or {}).get("capabilities", {}).get("bounded_job_wait"):
                started = time.monotonic()
                job = self.call("wait_job", job_id=job_id, wait_seconds=min(1, remaining))
                # All wait slots may be occupied; do not spin on immediate replies.
                if job["state"] not in TERMINAL and time.monotonic() - started < 0.05:
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            else:
                time.sleep(min(delay, remaining))
                delay = min(0.5, delay * 1.7)
                job = self.call("job", job_id=job_id)

    def run(self, operation, params=None, timeout=30, request_id=None):
        started = time.monotonic()
        job = self.submit(operation, params, request_id, min(max(timeout, 0), 1))
        if timeout <= 0 or job["state"] in TERMINAL:
            return job
        return self.wait(job["job_id"], max(0, timeout - (time.monotonic() - started)))

    def artifact(self, job_id, name):
        result = self.call("artifact", job_id=job_id, name=name)
        return base64.b64decode(result["data"])
