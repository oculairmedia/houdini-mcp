"""Run with hython in a fresh disposable process; never loads the artist HIP."""

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    import hou

    from houdini_companion.core import Ledger, atomic_json
    from houdini_companion.errors import CompanionError
    from houdini_companion.operations import Operations
    from houdini_companion.registry import load_registry
    from houdini_companion.state_guard import StateGuard, time_state

    directory = Path(sys.argv[1]).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    assert not hou.isUIAvailable(), "Run this disposable fixture with hython"
    registry = load_registry()
    ledger = Ledger(directory / "artifacts", registry=registry)
    ctx = Operations(hou, ledger, registry)
    evidence = {"houdini": hou.applicationVersionString(), "disposable_process": True, "checks": {}}

    def run(operation, **params):
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
            run(operation, **params)
        except CompanionError as exc:
            assert exc.code == code, (exc.code, str(exc))
            return exc.as_dict()
        raise AssertionError("Expected rejection: " + operation)

    original = time_state(hou)
    with StateGuard(hou):
        hou.setFrame(55)
        hou.setFps(30)
        hou.playbar.setFrameRange(10, 90)
    assert time_state(hou) == original
    evidence["checks"]["state_guard"] = True
    initial = {n.path() for n in hou.node("/obj").children()}
    failure = rejected(
        "build.stage",
        "BUILD_FAILED",
        nodes=[
            {
                "id": "bad",
                "type": "attribwrangle",
                "parms": {"class": 0, "snippet": "this is invalid VEX;"},
            }
        ],
        output="bad",
    )
    assert failure["cleanup"] == "removed"
    assert {n.path() for n in hou.node("/obj").children()} == initial
    evidence["checks"]["failed_build_cleanup"] = True
    source = directory / "fixture.h"
    source.write_text("#define WORKFLOW_SHIFT 0.002\n")
    vex = f'#include "{source.as_posix()}"\n@P.x += (@Frame-1)*WORKFLOW_SHIFT; i@id=@ptnum;'
    built = run(
        "build.stage",
        nodes=[
            {"id": "box", "type": "box"},
            {
                "id": "motion",
                "type": "attribwrangle",
                "inputs": ["box"],
                "parms": {"class": 2, "snippet": vex},
            },
        ],
        output="motion",
        name="workflow_fixture",
        profile="closed_solids",
    )
    assert built["hidden"] and not hou.node(built["root"]).isDisplayFlagSet()
    box = hou.node(built["root"] + "/box")
    box.parm("sizex").set(2)
    rejected("build.promote", "STALE_INPUT", build_id=built["build_id"])
    box.parm("sizex").set(1)
    rejected("build.promote", "REVIEW_REQUIRED", build_id=built["build_id"])
    review_cam = hou.node("/obj").createNode("cam", "promotion_cam")
    review_cam.parmTuple("t").set((3, 2, 4))
    review_cam.parmTuple("r").set((-20, 35, 0))
    candidate_render = run(
        "render.start",
        path=built["output"],
        frames=[hou.frame()],
        cameras=[review_cam.path()],
        resolution=128,
    )
    run("render.step", render_id=candidate_render["render_id"])
    candidate_review = run(
        "review.publish",
        render_id=candidate_render["render_id"],
        destination=str(directory / "candidate-review"),
    )
    promoted = run(
        "build.promote", build_id=built["build_id"], review_id=candidate_review["review_id"]
    )
    run("render.release", render_id=candidate_render["render_id"])
    root = hou.node(promoted["promoted"])
    out = root.node("motion")
    path = out.path()
    root.setDisplayFlag(False)
    evidence["checks"]["hidden_build_stale_rejection_promotion"] = True
    reverse = root.createNode("reverse", "reverse")
    reverse.setInput(0, out)
    assert not run("geometry.validate", path=reverse.path(), profile="closed_solids")["accepted"]
    reverse.destroy()
    card = root.createNode("grid", "card")
    assert run("geometry.validate", path=card.path(), profile="open_cards")["accepted"]
    assert not run("geometry.validate", path=card.path(), profile="closed_solids")["accepted"]
    card.destroy()
    probes = [{"origin": [0, 0, 0], "direction": [1, 0, 0], "distance": 2}]
    assert not run("geometry.validate", path=path, profile="walkway", probes=probes)["accepted"]
    evidence["checks"]["profiles_and_clearance"] = True
    cams = []
    for i in range(2):
        cam = hou.node("/obj").createNode("cam", "fixture_cam_" + str(i))
        cam.parmTuple("t").set((3 + i, 2, 4))
        cam.parmTuple("r").set((-20, 35 + i * 5, 0))
        cams.append(cam.path())
    hou.node(cams[0]).parm("projection").set("ortho")
    hou.node(cams[0]).parm("orthowidth").set(6)
    before = time_state(hou)
    sequence = run("render.start", path=path, frames=[1, 1.01, 3, 4], cameras=cams, resolution=256)
    rid = sequence["render_id"]
    folder = Path(sequence["manifest"]).parent
    recipe = json.loads((folder / "render-sequence.json").read_text())["recipes"]["view0"]
    assert recipe["parms"]["orthowidth"] == 6
    one = run("render.step", render_id=rid)
    assert one["completed"] == 1
    first = (folder / "frame-0000-view0.png").stat().st_mtime_ns
    run("render.cancel", render_id=rid)
    rejected("render.step", "RENDER_PAUSED", render_id=rid)
    two = run("render.step", render_id=rid, resume=True)
    assert two["completed"] == 2 and first == (folder / "frame-0000-view0.png").stat().st_mtime_ns
    out.parm("snippet").set(vex + "\n// changed")
    rejected("render.step", "STALE_INPUT", render_id=rid)
    out.parm("snippet").set(vex)
    c0 = hou.node(cams[0])
    c0.parm("tx").set(30)
    rejected("render.step", "STALE_INPUT", render_id=rid)
    c0.parm("tx").set(3)
    run("render.step", render_id=rid)
    run("render.step", render_id=rid)
    second = (folder / "frame-0001-view0.png").stat().st_mtime_ns
    (folder / "frame-0000-view0.png").write_bytes(b"corrupt")
    repaired = run("render.step", render_id=rid)
    assert repaired["rendered_frame"] == 1 and repaired["complete"]
    assert (folder / "frame-0001-view0.png").stat().st_mtime_ns == second
    assert time_state(hou) == before
    evidence["checks"]["render_pause_resume_corruption_stale_camera_source"] = True
    evidence["render_manifest"] = str(folder / "render-sequence.json")
    publication = run(
        "review.publish",
        render_id=rid,
        destination=str(directory / "review"),
        title="Harness acceptance",
        annotations=[{"frame": 1.01, "text": "Continuous boundary"}],
    )
    assert publication["image_decode_verified"]
    evidence["publication"] = publication
    continuity = run(
        "timeline.boundary", path=path, before=1, after=1.01, tolerance=0.001, render_id=rid
    )
    assert continuity["accepted"], continuity
    out.parm("snippet").set("i@id=@ptnum; @P.x += @Frame < 2 ? 0 : 2;")
    discontinuity = run("timeline.boundary", path=path, before=1.99, after=2.01, tolerance=0.01)
    assert not discontinuity["accepted"] and "POSITION_JUMP" in discontinuity["reasons"]
    jump = run("render.start", path=path, frames=[1.99, 2.01], cameras=cams, resolution=256)
    run("render.step", render_id=jump["render_id"])
    run("render.step", render_id=jump["render_id"])
    image_jump = run(
        "timeline.boundary",
        path=path,
        before=1.99,
        after=2.01,
        tolerance=0.01,
        image_tolerance=0.0001,
        render_id=jump["render_id"],
    )
    assert "IMAGE_DISCONTINUITY" in image_jump["reasons"], image_jump
    run("render.release", render_id=jump["render_id"])
    out.parm("snippet").set("i@id=1;")
    rejected("timeline.boundary", "DUPLICATE_ID", path=path, before=1, after=2)
    out.parm("snippet").set(vex)
    evidence["checks"]["boundary_geometry_and_images"] = True
    evidence["boundary"] = continuity
    original_hip = hou.hipFile.path()
    saved = run(
        "scene.save",
        destination=str(directory / "fixture.hip"),
        paths=[path],
        cameras=cams,
        frames=[1, 3],
    )
    assert hou.hipFile.path() == original_hip
    verification = run("save.verify", save_id=saved["save_id"], timeout=120)
    deadline = time.monotonic() + 130
    while time.monotonic() < deadline:
        status = run("save.verify_status", verification_id=verification["verification_id"])
        if status["state"] != "running":
            break
        time.sleep(0.5)
    assert status.get("accepted"), status
    evidence["save_reopen"] = status
    source.write_text("#define WORKFLOW_SHIFT 900\n")
    changed = run("save.verify", save_id=saved["save_id"], timeout=120)
    deadline = time.monotonic() + 130
    while time.monotonic() < deadline:
        status = run("save.verify_status", verification_id=changed["verification_id"])
        if status["state"] != "running":
            break
        time.sleep(0.5)
    assert not status["accepted"] and status["reasons"][0]["code"] == "CHANGED_DEPENDENCY", status
    source.write_text("#define WORKFLOW_SHIFT 0.002\n")
    evidence["checks"]["fresh_reopen_and_changed_dependency"] = True
    run("save.release", save_id=saved["save_id"])
    assert Path(saved["hip"]).exists()
    run("render.release", render_id=rid)
    rejected("render.status", "RENDER_NOT_FOUND", render_id=rid)
    evidence["checks"]["render_release"] = True
    evidence["passed"] = True
    atomic_json(directory / "report.json", evidence)
    print(json.dumps({"passed": True, "report": str(directory / "report.json")}), flush=True)


if __name__ == "__main__":
    main()
