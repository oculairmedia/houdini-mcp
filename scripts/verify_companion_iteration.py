"""Live disposable fixture: native diagnostics, guarded source apply, and exact restore."""

import json
import time
import uuid
from pathlib import Path

from houdini_companion.client import Client


def main():
    client = Client()
    name = "__iteration_test_" + uuid.uuid4().hex[:8]
    root = "/obj/" + name
    evidence = Path.home() / ".houdini-companion" / "iteration-spike"
    evidence.mkdir(exist_ok=True)
    source = evidence / (name + ".h")
    source.write_text("#define SCALE 1.0\n", encoding="utf-8")

    def run(operation, params):
        result = client.run(operation, params, timeout=1)
        while result["state"] in {"queued", "running"}:
            result = client.wait(result["job_id"], timeout=10)
        if result["state"] != "succeeded":
            raise RuntimeError(result)
        return result["result"]

    try:
        run(
            "execute",
            {
                "code": f"""n=hou.node('/obj').createNode('geo',{name!r})
n.setDisplayFlag(False)
n=n.createNode('subnet','network')
box=n.createNode('box','input')
w=n.createNode('attribwrangle','candidate')
w.parm('class').set(2)
w.setInput(0,box)
w.parm('snippet').set('#include "{source.as_posix()}"\\n@P *= SCALE;')
w.cook(force=True)
out=n.createNode('null','OUT')
out.setInput(0,w)
out.setDisplayFlag(True)
out.setRenderFlag(True)
result={{'path':w.path()}}
"""
            },
        )
        begin = time.perf_counter()
        cap = run(
            "iteration.capture",
            {"path": root + "/network/candidate", "views": ["persp"], "resolution": 256},
        )
        rejected = client.run(
            "iteration.stage",
            {
                "capture_id": cap["capture_id"],
                "files": [{"path": str(source), "content": "this is deliberately invalid VEX;\n"}],
            },
            timeout=10,
        )
        while rejected["state"] in {"queued", "running"}:
            rejected = client.wait(rejected["job_id"], timeout=10)
        assert rejected["state"] == "failed", rejected
        assert source.read_text() == "#define SCALE 1.0\n"
        staged = run(
            "iteration.stage",
            {
                "capture_id": cap["capture_id"],
                "files": [{"path": str(source), "content": "#define SCALE 1.1\n"}],
                "benchmark_samples": 3,
            },
        )
        assert staged["accepted_basic_checks"], staged
        assert staged["after"]["camera_recipes"] == cap["feedback"]["camera_recipes"]
        assert source.read_text() == "#define SCALE 1.0\n"
        applied = run("iteration.apply", {"stage_id": staged["stage_id"]})
        assert source.read_text() == "#define SCALE 1.1\n"
        recaptured = run(
            "iteration.capture",
            {"path": root + "/network/candidate", "views": ["persp"], "resolution": 256},
        )
        assert recaptured["source_paths"] == [str(source.resolve())], recaptured
        assert any("sources" in p["path"] for p in recaptured["observation"]["sources"])
        restored = run("iteration.restore", {"apply_id": applied["apply_id"]})
        assert source.read_text() == "#define SCALE 1.0\n"
        assert restored["feedback"]["geometry"]["bounds"] == cap["feedback"]["geometry"]["bounds"]
        report = {
            "elapsed_ms": (time.perf_counter() - begin) * 1000,
            "capture": cap,
            "stage": staged,
            "apply": applied,
            "restore": restored,
            "recapture_targets_editable_source": True,
            "failed_preview_restored": True,
            "paired_framing_preserved": True,
        }
        (evidence / "fixture-verification.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "passed": True,
                    "elapsed_ms": report["elapsed_ms"],
                    "benchmark": staged["after"]["benchmark"],
                    "report": str(evidence / "fixture-verification.json"),
                }
            )
        )
    finally:
        run(
            "execute",
            {"code": f"n=hou.node({root!r})\nif n:n.destroy()\nresult={{'removed':{root!r}}}"},
        )


if __name__ == "__main__":
    main()
