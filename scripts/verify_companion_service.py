"""Live transport, cancellation, panel and lifecycle checks, without scene edits."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from houdini_companion.client import Client
from houdini_companion.core import CompanionError, atomic_json


def main():
    client = Client()
    health = client.call("health")
    root = Path(health["capabilities"]["artifact_root"])
    checks = {}
    job = client.submit(
        "execute", {"code": "import time\ntime.sleep(1.2)\nresult={'completed':True}"}
    )
    deadline = time.monotonic() + 3
    while client.call("job", job_id=job["job_id"])["state"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert client.wait(job["job_id"], 0.05)["state"] == "running"
    queued = client.submit("inspect", {"path": "/obj"})
    assert client.call("cancel", job_id=queued["job_id"])["state"] == "cancelled"
    assert client.call("cancel", job_id=job["job_id"])["state"] == "running"
    recovered = Client().wait(job["job_id"], 5)
    assert recovered["state"] == "succeeded" and recovered["cancel_requested"]
    checks["running_timeout_does_not_kill_or_retry"] = True
    checks["queued_cancel_and_reconnect"] = True
    try:
        urllib.request.urlopen(
            urllib.request.Request(client.descriptor["url"], data=b'{"action":"health"}')
        )
        raise AssertionError("Unauthenticated request accepted")
    except urllib.error.HTTPError as exc:
        assert json.loads(exc.read())["error"]["code"] == "UNAUTHORIZED"
    checks["token_required"] = True
    try:
        client.artifact(job["job_id"], "../job.json")
        raise AssertionError("Artifact traversal accepted")
    except CompanionError as exc:
        assert exc.code == "INVALID_ARTIFACT"
    checks["artifact_traversal_rejected"] = True
    panel = client.run(
        "execute",
        {
            "code": "from houdini_companion.panel import create_interface\nw=create_interface()\nw.resize(700,700)\nw.refresh()\nresult={'widget':w.metaObject().className()}\nw.deleteLater()"
        },
    )
    assert panel["state"] == "succeeded", panel
    checks["panel_constructs_and_closes_without_stopping_service"] = True
    prior_session = client.call("health")["session_id"]
    assert client.call("stop")["stopping"]
    deadline = time.monotonic() + 5
    while True:
        try:
            client.call("health")
        except CompanionError:
            break
        assert time.monotonic() < deadline, "Server did not stop"
        time.sleep(0.05)
    assert (
        not Path.home()
        .joinpath(".houdini-companion", "sessions", f"{health['capabilities']['pid']}.json")
        .exists()
    )
    checks["stop_closes_listener_and_discovery"] = True
    bootstrap = Path(__file__).with_name("bootstrap_companion.py")
    result = subprocess.run(
        [sys.executable, str(bootstrap)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    restarted = Client()
    assert restarted.call("health")["session_id"] != prior_session
    archived = restarted.call("job", job_id=job["job_id"])
    assert archived["archived"] and archived["state"] == "succeeded"
    checks["restart_rotates_identity_and_preserves_receipts"] = True
    atomic_json(root / "service-acceptance.json", checks)
    print(json.dumps({"checks": checks, "evidence": str(root / "service-acceptance.json")}))


if __name__ == "__main__":
    main()
