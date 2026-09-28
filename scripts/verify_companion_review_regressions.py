"""Invoke run(directory) in an isolated GUI Houdini process, never the artist session."""

import json
import time
import uuid
from pathlib import Path


def run(directory):
    import hou

    from houdini_companion.core import Ledger, atomic_json
    from houdini_companion.errors import CompanionError
    from houdini_companion.observation import fingerprint
    from houdini_companion.operations import Operations
    from houdini_companion.registry import load_registry
    from houdini_companion.runtime import Runtime
    from houdini_companion.saved_scene import sha256
    from houdini_companion.state_guard import time_state

    assert hou.isUIAvailable(), "Dirty-state acceptance requires a disposable GUI process"
    directory = Path(directory).resolve()
    registry = load_registry()
    ledger = Ledger(directory / "artifacts", registry=registry)
    ctx = Operations(hou, ledger, registry)
    evidence = {
        "houdini": hou.applicationVersionString(),
        "pid": __import__("os").getpid(),
        "disposable_gui": True,
        "checks": {},
    }

    def call(operation, **params):
        submitted = ledger.submit(
            {
                "version": 1,
                "session_id": ledger.session_id,
                "scene_id": ledger.scene_id,
                "request_id": uuid.uuid4().hex,
                "operation": operation,
                "params": params,
            }
        )
        job = ledger.take()
        assert job["job_id"] == submitted["job_id"]
        try:
            result = ctx.execute(job)
        except CompanionError as exc:
            ledger.finish(job["job_id"], error=exc.as_dict())
            raise
        except Exception as exc:
            ledger.finish(job["job_id"], error={"code": type(exc).__name__, "message": str(exc)})
            raise
        ledger.finish(job["job_id"], result=result)
        return result

    def rejected(operation, code, **params):
        try:
            call(operation, **params)
        except CompanionError as exc:
            assert exc.code == code, (exc.code, str(exc))
            return exc.as_dict()
        raise AssertionError("Expected rejection: " + operation)

    hou.setFrame(1)
    root = hou.node("/obj").createNode("geo", "artist_fixture")
    box = root.createNode("box", "box")
    box.setDisplayFlag(True)
    untitled = hou.hipFile.path()
    assert not Path(untitled).is_file() and hou.hipFile.hasUnsavedChanges()
    call("scene.save", destination=str(directory / "untitled-copy.hip"), paths=[box.path()])
    assert hou.hipFile.path() == untitled and hou.hipFile.hasUnsavedChanges()
    evidence["checks"]["never_saved_copy_preserves_dirty_state"] = True
    hou.hipFile.save(str(directory / "original.hip"))
    original = Path(hou.hipFile.path())
    original_hash = sha256(original)
    assert not hou.hipFile.hasUnsavedChanges()
    clean = call("scene.save", destination=str(directory / "clean-copy.hip"), paths=[box.path()])
    assert (
        not hou.hipFile.hasUnsavedChanges()
        and Path(hou.hipFile.path()).resolve() == original.resolve()
    )
    box.parm("sizex").set(2)
    assert hou.hipFile.hasUnsavedChanges()
    dirty = call("scene.save", destination=str(directory / "dirty-copy.hip"), paths=[box.path()])
    assert (
        hou.hipFile.hasUnsavedChanges() and Path(hou.hipFile.path()).resolve() == original.resolve()
    )
    assert sha256(original) == original_hash
    evidence["save_receipts"] = [clean, dirty]
    evidence["checks"]["clean_and_dirty_copy_preserve_active_hip"] = True
    original_backup = hou.hipFile.saveAsBackup

    def fail_backup():
        raise hou.OperationFailed("Injected backup failure")

    hou.hipFile.saveAsBackup = fail_backup
    try:
        try:
            call("scene.save", destination=str(directory / "failed-copy.hip"), paths=[box.path()])
        except hou.OperationFailed:
            pass
        else:
            raise AssertionError("Expected save failure")
        assert (
            hou.hipFile.hasUnsavedChanges()
            and Path(hou.hipFile.path()).resolve() == original.resolve()
        )
        assert not (directory / "failed-copy.hip").exists()
    finally:
        hou.hipFile.saveAsBackup = original_backup
    evidence["checks"]["failed_copy_preserves_dirty_state"] = True

    target = root.createNode("null", "observed")
    expected = {n.path(): fingerprint(hou, n)["token"] for n in (root, target)}
    old_id = target.sessionId()
    actions = [
        {"op": "delete", "path": target.path()},
        {"op": "create", "parent": root.path(), "type": "null", "name": "observed", "as": "new"},
        {"op": "set", "path": target.path(), "values": {"copyinput": 0}},
    ]
    rejected("batch", "TARGET_DELETED", actions=actions, expected=expected, feedback=False)
    assert hou.node(target.path()).sessionId() == old_id
    actions[-1]["path"] = "$new"
    call("batch", actions=actions, expected=expected, feedback=False)
    assert root.node("observed").sessionId() != old_id
    evidence["checks"]["batch_literal_rejected_alias_replacement_accepted"] = True

    cam = hou.node("/obj").createNode("cam", "review_cam")
    cam.parmTuple("t").set((3, 2, 4))
    cam.parmTuple("r").set((-20, 35, 0))
    built = call(
        "build.stage",
        nodes=[{"id": "box", "type": "box"}],
        output="box",
        name="reviewed",
        profile="closed_solids",
        review_frames=[1, 2],
    )
    rejected("build.promote", "REVIEW_REQUIRED", build_id=built["build_id"])
    seq = call(
        "render.start", path=built["output"], frames=[1, 2], cameras=[cam.path()], resolution=128
    )
    call("render.step", render_id=seq["render_id"])
    rejected(
        "review.publish",
        "INCOMPLETE_REVIEW",
        render_id=seq["render_id"],
        destination=str(directory / "incomplete-review"),
    )
    call("render.step", render_id=seq["render_id"])
    review = call(
        "review.publish", render_id=seq["render_id"], destination=str(directory / "review")
    )
    candidate = hou.node(built["output"])
    candidate.parm("sizex").set(2)
    rejected(
        "build.promote", "STALE_INPUT", build_id=built["build_id"], review_id=review["review_id"]
    )
    candidate.parm("sizex").set(1)
    manifest = json.loads(Path(review["manifest"]).read_text())
    image = Path(review["manifest"]).parent / manifest["rows"][1]["images"][0]["name"]
    image_bytes = image.read_bytes()
    image.write_bytes(b"corrupt")
    rejected(
        "build.promote",
        "ARTIFACT_CORRUPT",
        build_id=built["build_id"],
        review_id=review["review_id"],
    )
    image.write_bytes(image_bytes)
    promoted = call("build.promote", build_id=built["build_id"], review_id=review["review_id"])
    assert hou.node(promoted["promoted"]).isDisplayFlagSet()
    evidence["promotion"] = promoted
    evidence["review"] = review
    evidence["checks"]["missing_partial_stale_corrupt_review_rejected_exact_promoted"] = True

    motion = root.createNode("attribwrangle", "ids")
    motion.setInput(0, box)
    motion.parm("class").set(2)
    motion.parm("snippet").set("i@id=@ptnum;")
    for frame in (1, 2):
        motion.geometry().saveToFile(str(directory / f"sample{frame}.bgeo.sc"))
    file_node = root.createNode("file", "temporal_files")
    file_node.parm("file").set((directory / "sample$F.bgeo.sc").as_posix())
    seq2 = call(
        "render.start", path=file_node.path(), frames=[1, 2], cameras=[cam.path()], resolution=128
    )
    call("render.step", render_id=seq2["render_id"])
    call("render.step", render_id=seq2["render_id"])
    old_time = time_state(hou)
    continuity = call(
        "timeline.boundary", path=file_node.path(), before=1, after=2, render_id=seq2["render_id"]
    )
    assert continuity["accepted"]
    box.parm("sizex").set(4)
    motion.geometry().saveToFile(str(directory / "sample2.bgeo.sc"))
    file_node.cook(force=True)
    rejected(
        "timeline.boundary",
        "STALE_INPUT",
        path=file_node.path(),
        before=1,
        after=2,
        render_id=seq2["render_id"],
    )
    assert time_state(hou) == old_time
    evidence["checks"]["nonanchor_source_edit_rejected_with_time_restored"] = True

    # Deterministic long-running verifier stand-in exercises real process lifetime,
    # accounting and actual BeforeClear callbacks without waiting for a fast worker.
    import subprocess
    import threading

    worker = subprocess.Popen(
        [str(Path(hou.getenv("HFS")) / "bin/hython.exe"), "-c", "import time;time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    timer = threading.Timer(120, worker.kill)
    timer.daemon = True
    timer.start()
    ctx.state.setdefault("save_verifiers", {})["lifetime"] = {
        "process": worker,
        "timer": timer,
        "save_id": dirty["save_id"],
        "folder": directory,
        "deadline": time.monotonic() + 120,
    }
    runtime = Runtime.__new__(Runtime)
    runtime.hou, runtime.ledger, runtime.operations = hou, ledger, ctx
    runtime.watchers = type("Watchers", (), {"clear": lambda _self: None})()
    runtime.tick_callback = lambda: None
    runtime.hip_callback = runtime.hip_event
    runtime.server, runtime.descriptor = None, directory / "absent-session.json"
    hou.ui.addEventLoopCallback(runtime.tick_callback)
    hou.hipFile.addEventCallback(runtime.hip_callback)
    try:
        prior_scene = ledger.scene_id
        hou.hipFile.clear(suppress_save_prompt=True)
        assert ledger.scene_id != prior_scene
        assert call("save.verify_status", verification_id="lifetime")["state"] == "running"
        assert dirty["save_id"] in ctx.state["deliverables"]
        runtime.stop()
        assert worker.poll() is not None
    finally:
        timer.cancel()
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=5)
    evidence["checks"]["actual_scene_clear_keeps_worker_handle_shutdown_reaps"] = True
    evidence["passed"] = True
    atomic_json(directory / "report.json", evidence)
    return evidence
