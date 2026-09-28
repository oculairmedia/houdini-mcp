import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from houdini_companion.agent_output import compact_job
from houdini_companion.continuity import compare_images, compare_points
from houdini_companion.errors import CompanionError
from houdini_companion.geometry_profiles import analyze
from houdini_companion.plugins.render_sequence import cached_hash, completed, file_ok
from houdini_companion.registry import load_registry
from houdini_companion.review_player import publish_files
from houdini_companion.saved_scene import dependency_failures, sha256, verify
from houdini_companion.state_guard import StateGuard


def fake_hou():
    state = {
        "frame": 12.5,
        "fps": 24,
        "frame_range": [1, 240],
        "playback_range": [10, 120],
        "playing": True,
    }
    h = SimpleNamespace(
        frame=lambda: state["frame"],
        fps=lambda: state["fps"],
        setFrame=lambda v: state.update(frame=v),
        setFps=lambda v: state.update(fps=v),
        playbar=SimpleNamespace(
            frameRange=lambda: state["frame_range"],
            playbackRange=lambda: state["playback_range"],
            isPlaying=lambda: state["playing"],
            setFrameRange=lambda a, b: state.update(frame_range=[a, b]),
            setPlaybackRange=lambda a, b: state.update(playback_range=[a, b]),
            play=lambda: state.update(playing=True),
            stop=lambda: state.update(playing=False),
        ),
    )
    return h, state


@pytest.mark.parametrize(
    "failure", [None, RuntimeError("cook failed"), CompanionError("CANCEL_REQUESTED", "cancelled")]
)
def test_state_guard_restores_declared_time_on_success_failure_cancel(failure):
    h, values = fake_hou()
    before = copy.deepcopy(values)
    try:
        with StateGuard(h) as guard:
            values.update(frame=70, fps=30, frame_range=[5, 500], playback_range=[50, 80])
            if failure:
                raise failure
    except (RuntimeError, CompanionError) as exc:
        assert exc is failure
    assert values == before
    assert guard.receipt["restored"]
    assert guard.receipt["before"]["time"] == guard.receipt["after"]["time"]


def test_failed_restoration_continues_remaining_fields_and_reports_original():
    h, values = fake_hou()

    def fail(_v):
        raise RuntimeError("fps locked")

    h.setFps = fail
    with pytest.raises(CompanionError) as exc, StateGuard(h):
        values.update(fps=30, frame=99)
        raise ValueError("original render failure")
    assert exc.value.code == "STATE_RESTORE_FAILED"
    assert values["frame"] == 12.5 and values["playing"]
    assert "original render failure" in str(exc.value.details)
    assert values["fps"] == 30


def tetra():
    return np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float), [
        [1, 2, 0],
        [3, 1, 0],
        [2, 3, 0],
        [3, 2, 1],
    ]


def test_closed_solid_orientation_and_open_card_profiles():
    xyz, faces = tetra()
    assert analyze(xyz, faces, "closed_solids")["accepted"]
    json.dumps(analyze(xyz + 10000, faces, "closed_solids"), allow_nan=False)
    wrong = analyze(xyz, [list(reversed(f)) for f in faces], "closed_solids")
    assert not wrong["accepted"] and wrong["inward_components"] == 1
    assert analyze(xyz, [faces[0]], "open_cards")["accepted"]
    assert not analyze(xyz, [faces[0]], "closed_solids")["accepted"]


def test_disconnected_inward_component_cannot_hide_inside_net_volume():
    xyz, faces = tetra()
    coords = np.concatenate([xyz * 10, xyz + 20])
    all_faces = faces + [[p + 4 for p in reversed(f)] for f in faces]
    assert analyze(coords, all_faces, "closed_solids")["inward_components"] == 1


def test_degenerate_and_nonfinite_geometry_rejects():
    xyz, faces = tetra()
    xyz[1] = xyz[0]
    assert not analyze(xyz, faces)["accepted"]
    xyz[1, 0] = np.nan
    assert analyze(xyz, faces)["reasons"] == ["NONFINITE_POINTS"]


def test_boundary_matches_ids_when_point_order_changes_and_reports_births():
    r = compare_points(
        [1, 2], [[0, 0, 0], [1, 0, 0]], [3, 2, 1], [[3, 0, 0], [1.001, 0, 0], [0, 0, 0]], 0.01, True
    )
    assert r["accepted"] and r["born_ids"] == [3] and r["matched"] == 2
    assert not compare_points([1], [[0, 0, 0]], [1], [[1, 0, 0]], 0.01)["accepted"]
    with pytest.raises(CompanionError, match="unique"):
        compare_points([1, 1], [[0, 0, 0]] * 2, [1], [[0, 0, 0]], 0.01)
    assert not compare_points([1], [[0, 0, 0]], [2], [[0, 0, 0]], 1, True)["accepted"]


def test_image_continuity_measures_pop_and_requires_alignment():
    a = np.zeros((16, 16, 3), dtype=np.uint8)
    assert compare_images(a, a)["mean_absolute_difference"] == 0
    assert compare_images(a, np.full_like(a, 255))["changed_pixel_fraction"] == 1
    with pytest.raises(CompanionError):
        compare_images(a, a[:1])


def item(path, content=b"content"):
    path.write_bytes(content)
    return {"name": path.name, "sha256": hashlib.sha256(content).hexdigest()}


def test_render_hash_cache_avoids_quadratic_reads_and_detects_corruption(tmp_path):
    cached_hash.cache_clear()
    files = [item(tmp_path / f"{i}.png", b"x" * 65536) for i in range(50)]
    for _ in range(20):
        assert all(file_ok(tmp_path, f) for f in files)
    assert cached_hash.cache_info().misses == 50
    (tmp_path / "0.png").write_bytes(b"corrupt")
    assert not file_ok(tmp_path, files[0])
    assert not file_ok(tmp_path, {"name": "../outside", "sha256": "x"})


def review_data(tmp_path):
    geo = item(tmp_path / "geometry.bgeo")
    image = item(tmp_path / "view.png")
    return {
        "rows": [{"images": [image], "geometry_artifact": geo}],
        "recipes": {"view0": {}},
        "fps": 24,
    }


def test_publication_rejects_incomplete_corrupt_and_undecodable_evidence(tmp_path):
    data = review_data(tmp_path)
    assert completed(tmp_path, data["rows"][0])
    bad = copy.deepcopy(data)
    bad["rows"] = [None]
    with pytest.raises(CompanionError):
        publish_files(tmp_path, bad, tmp_path / "out", "T", [], lambda _p: None)
    (tmp_path / "view.png").write_bytes(b"changed")
    with pytest.raises(CompanionError):
        publish_files(tmp_path, data, tmp_path / "out", "T", [], lambda _p: None)
    data = review_data(tmp_path)

    def fail(_path):
        raise ValueError("decode failed")

    with pytest.raises(ValueError):
        publish_files(tmp_path, data, tmp_path / "out", "T", [], fail)
    assert not (tmp_path / "out").exists()


def test_publication_escapes_untrusted_title_and_annotations(tmp_path):
    data = review_data(tmp_path)
    out = tmp_path / "out"
    publish_files(
        tmp_path,
        data,
        out,
        "<script>bad()</script>",
        [{"frame": 1, "text": "</script><script>bad()</script>"}],
        lambda _p: None,
    )
    text = (out / "index.html").read_text()
    assert "<script>bad()" not in text
    assert json.loads((out / "review.json").read_text())["title"] == "<script>bad()</script>"
    assert (out / "geometry.bgeo").read_bytes() == b"content"
    with pytest.raises(CompanionError):
        publish_files(tmp_path, data, out, "x", [], lambda _p: None)


def test_missing_changed_dependency_prevents_hip_load(tmp_path):
    asset = tmp_path / "source.h"
    asset.write_text("original")
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    manifest = {
        "hip": str(hip),
        "hip_sha256": sha256(hip),
        "dependencies": [{"path": str(asset), "sha256": sha256(asset)}],
    }
    asset.write_text("changed")
    assert dependency_failures(manifest)[0]["code"] == "CHANGED_DEPENDENCY"
    h = SimpleNamespace(
        hipFile=SimpleNamespace(load=lambda *_a, **_k: pytest.fail("must not open"))
    )
    assert not verify(h, manifest)["opened"]
    asset.unlink()
    assert dependency_failures(manifest)[0]["code"] == "MISSING_DEPENDENCY"


def test_new_contracts_have_bounded_inputs_and_compact_continuation():
    registry = load_registry()
    for op in (
        "build.stage",
        "geometry.validate",
        "render.start",
        "review.publish",
        "scene.save",
        "save.verify",
        "timeline.boundary",
    ):
        assert op in registry.effects()
    with pytest.raises(CompanionError):
        registry.validate(
            "render.start", {"path": "/obj/g/x", "frames": list(range(301)), "cameras": ["/obj/c"]}
        )
    value = compact_job(
        {
            "job_id": "j",
            "state": "succeeded",
            "result": {
                "render_id": "r",
                "completed": 2,
                "total": 8,
                "next_operation": "render.step",
                "manifest": "x",
            },
        }
    )
    assert (
        value["result"]["render_id"] == "r" and value["result"]["next_operation"] == "render.step"
    )


@pytest.mark.parametrize("expired", [False, True])
def test_verifier_nonzero_exit_never_trusts_success_report(tmp_path, expired):
    import time

    from houdini_companion.plugins.delivery import verify_status

    (tmp_path / "verification.json").write_text('{"accepted": true}')
    record = {
        "process": SimpleNamespace(poll=lambda: 1),
        "timer": SimpleNamespace(cancel=lambda: None),
        "folder": tmp_path,
        "deadline": time.monotonic() + (-10 if expired else 10),
    }
    ctx = SimpleNamespace(state={"save_verifiers": {"v": record}})
    result = verify_status(ctx, {}, "v")
    assert not result["accepted"]
    assert result["reason"] == ("TIMEOUT" if expired else "WORKER_FAILED")


def test_saved_receipt_release_refuses_active_worker_then_unpins():
    from houdini_companion.plugins.delivery import release, verify_start

    exit_code = [None]
    record = {
        "process": SimpleNamespace(poll=lambda: exit_code[0]),
        "timer": SimpleNamespace(cancel=lambda: None),
        "save_id": "s",
    }
    ctx = SimpleNamespace(
        state={"deliverables": {"s": "manifest"}, "save_verifiers": {"v": record}}
    )
    with pytest.raises(CompanionError) as exc:
        release(ctx, {}, "s")
    assert exc.value.code == "VERIFY_BUSY"
    ctx.state["save_verifiers"] = {str(i): record for i in range(16)}
    with pytest.raises(CompanionError) as exc:
        verify_start(ctx, {}, "s")
    assert exc.value.code == "VERIFY_LIMIT"
    exit_code[0] = 0
    assert not release(ctx, {}, "s")["hip_deleted"]
    assert not ctx.state["save_verifiers"] and not ctx.state["deliverables"]


def test_state_guard_rejects_silent_failed_restoration():
    h, state = fake_hou()
    h.setFrame = lambda _frame: None
    with pytest.raises(CompanionError) as exc, StateGuard(h):
        state["frame"] = 99
    assert exc.value.code == "STATE_RESTORE_FAILED"
    assert exc.value.details["receipt"]["failures"][0]["field"] == "readback"


def test_camera_channel_restoration_and_explicit_show():
    from houdini_companion.plugins.delivery import show

    h, values = fake_hou()
    channel = {"value": 2}
    parm = SimpleNamespace(
        eval=lambda: channel["value"],
        keyframes=lambda: (),
        deleteAllKeyframes=lambda: None,
        set=lambda value: channel.update(value=value),
    )
    camera = SimpleNamespace(
        path=lambda: "/obj/camera",
        type=lambda: SimpleNamespace(name=lambda: "cam"),
        parm=lambda name: parm if name == "tx" else None,
    )
    with StateGuard(h, [camera]):
        channel["value"] = 99
    assert channel["value"] == 2
    display = [False]
    root = SimpleNamespace(
        isDisplayFlagSet=lambda: display[0],
        setDisplayFlag=lambda flag: display.__setitem__(0, flag),
    )
    viewport_state = {"camera": None, "locked": True}
    viewport = SimpleNamespace(
        camera=lambda: viewport_state["camera"],
        setCamera=lambda node: viewport_state.update(camera=node),
        lockCameraToView=lambda flag: viewport_state.update(locked=flag),
    )
    viewer = SimpleNamespace(curViewport=lambda: viewport, setIsCurrentTab=lambda: None)
    h.ObjNode = SimpleNamespace
    h.node = lambda path: {"/obj/g": root, "/obj/camera": camera}.get(path)
    h.isUIAvailable = lambda: True
    h.paneTabType = SimpleNamespace(SceneViewer=1)
    h.ui = SimpleNamespace(paneTabOfType=lambda _type: viewer)
    result = show(SimpleNamespace(hou=h), {}, "/obj/g", "/obj/camera", 42)
    assert not result["before"]["display"] and result["after"]["display"]
    assert result["after"]["camera"] == "/obj/camera" and values["frame"] == 42
    assert not viewport_state["locked"]


def test_render_manifest_from_another_scene_rejects(tmp_path):
    from houdini_companion.plugins.render_sequence import get

    folder = tmp_path / "r"
    folder.mkdir()
    (folder / "render-sequence.json").write_text('{"scene_id":"old","session_id":"s"}')
    ctx = SimpleNamespace(
        state={"render_sequences": {"r": True}},
        ledger=SimpleNamespace(root=tmp_path, scene_id="new", session_id="s"),
    )
    with pytest.raises(CompanionError) as exc:
        get(ctx, "r")
    assert exc.value.code == "STALE_SCENE"


@pytest.mark.performance
def test_profile_analysis_budget(benchmark):
    xyz, faces = tetra()
    positions = np.concatenate([xyz + [i * 3, 0, 0] for i in range(2500)])
    polygons = [[p + i * 4 for p in face] for i in range(2500) for face in faces]
    result = benchmark.pedantic(lambda: analyze(positions, polygons, "closed_solids"), rounds=3)
    assert result["accepted"] and result["components"] == 2500
    assert benchmark.stats["median"] < 0.6
