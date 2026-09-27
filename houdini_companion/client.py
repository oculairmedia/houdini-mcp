"""Standard-library client shared by the CLI and MCP adapters."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import PROTOCOL_VERSION
from .core import TERMINAL, CompanionError


class Client:
    def __init__(self, descriptor=None, pid=None, timeout=5):
        self.timeout = timeout
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
        request = urllib.request.Request(
            self.descriptor["url"],
            data=json.dumps({"action": action, **fields}).encode(),
            headers={
                "Authorization": "Bearer " + self.descriptor["token"],
                "Content-Type": "application/json",
            },
        )
        try:
            # Do not send local session tokens through an environment proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read())
        except (OSError, ValueError) as exc:
            raise CompanionError(
                "TRANSPORT",
                str(exc),
                retry_policy="Query the same job/request; never blindly replay a mutation",
            ) from exc
        if not payload.get("ok"):
            error = dict(payload["error"])
            raise CompanionError(error.pop("code"), error.pop("message"), **error)
        return payload["result"]

    def submit(self, operation, params=None, request_id=None):
        health = self.call("health")
        request = {
            "version": PROTOCOL_VERSION,
            "session_id": health["session_id"],
            "scene_id": health["scene_id"],
            "request_id": request_id or uuid.uuid4().hex,
            "operation": operation,
            "params": params or {},
        }
        try:
            return self.call("submit", request=request)
        except CompanionError as exc:
            exc.details["request"] = request
            raise

    def wait(self, job_id, timeout=30):
        deadline = time.monotonic() + timeout
        while True:
            job = self.call("job", job_id=job_id)
            if job["state"] in TERMINAL or time.monotonic() >= deadline:
                return job
            time.sleep(0.05)

    def run(self, operation, params=None, timeout=30, request_id=None):
        job = self.submit(operation, params, request_id)
        return job if timeout <= 0 else self.wait(job["job_id"], timeout)

    def artifact(self, job_id, name):
        result = self.call("artifact", job_id=job_id, name=name)
        return base64.b64decode(result["data"])
