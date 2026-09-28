import io
import json
from types import SimpleNamespace

import pytest

from houdini_companion.agent_output import compact_job, scoped_catalog
from houdini_companion.cli import main, recipe
from houdini_companion.diagnostics import topology_hash
from houdini_companion.errors import CompanionError
from houdini_companion.plugins.animation import restore_channels
from houdini_companion.plugins.timeline import preserve_time
from houdini_companion.registry import load_registry
from houdini_companion.temporal import displacement, frame_list, validate_tracks


def test_topology_detects_added_orphan_points():
    connectivity = b"Poly:1:0,1,2,"
    assert topology_hash(3, connectivity) != topology_hash(4, connectivity)
    assert topology_hash(3, connectivity) != topology_hash(3, b"Poly:1:2,1,0,")


@pytest.mark.parametrize(
    "value,expected",
    [("1:3:0.5", [1, 1.5, 2, 2.5, 3]), ("3:1:-1", [3, 2, 1]), ("1,25,1", [1, 25, 1])],
)
def test_frame_parser(value, expected):
    assert frame_list(value) == expected


@pytest.mark.parametrize("value", ["1:240:1", "1:2:0", "nan,1", "1:2:-1", "", "1:2"])
def test_frame_parser_rejects_unbounded_or_invalid_work(value):
    with pytest.raises(CompanionError):
        frame_list(value)


def test_motion_uses_positions_and_seconds():
    import numpy as np

    a = np.zeros((3, 3), dtype=np.float32)
    b = a.copy()
    b[1, 0] = 2
    value = displacement(a.tobytes(), b.tobytes(), 0.5)
    assert value["moved_points"] == 1
    assert value["max_average_speed"] == 4
    assert displacement(a.tobytes(), a.tobytes(), 1)["moved_points"] == 0
    assert not displacement(a.tobytes(), b[:1].tobytes(), 1)["comparable"]


def test_time_restored_on_failure_with_fractional_frame_and_playback():
    values = {"frame": 12.5, "playing": True}
    hou = SimpleNamespace(
        frame=lambda: values["frame"],
        time=lambda: (values["frame"] - 1) / 24,
        fps=lambda: 24,
        setFrame=lambda x: values.update(frame=x),
        playbar=SimpleNamespace(
            frameRange=lambda: (1, 240),
            playbackRange=lambda: (1, 120),
            isPlaying=lambda: values["playing"],
            stop=lambda: values.update(playing=False),
            play=lambda: values.update(playing=True),
        ),
    )
    with pytest.raises(RuntimeError), preserve_time(hou):
        assert not values["playing"]
        values["frame"] = 100
        raise RuntimeError("cook failed")
    assert values == {"frame": 12.5, "playing": True}


def test_key_batch_rejects_duplicates_and_unsorted_frames():
    t = {"path": "/obj/g/tx", "keys": [{"frame": 2, "value": 1}, {"frame": 1, "value": 0}]}
    for tracks in ([t], [t, t]):
        with pytest.raises(CompanionError):
            validate_tracks(tracks)


def test_channel_restore_continues_after_failure_and_reports_it():
    restored = []
    good = SimpleNamespace(
        path=lambda: "good", deleteAllKeyframes=lambda: None, set=lambda v: restored.append(v)
    )

    def fail():
        raise RuntimeError("locked externally")

    bad = SimpleNamespace(path=lambda: "bad", deleteAllKeyframes=fail)
    with pytest.raises(CompanionError) as exc:
        restore_channels([(good, [], 4, []), (bad, [], 0, [])])
    assert exc.value.code == "ANIMATION_ROLLBACK_FAILED"
    assert restored == [4]


def test_scoped_schema_is_small_and_effect_filtered():
    catalog = load_registry().catalog()
    small = scoped_catalog(catalog, "timeline.*", "read", True)
    assert set(small["operations"]) == {"timeline.inspect", "timeline.boundary"}
    assert len(json.dumps(small)) < len(json.dumps(catalog)) / 10
    with pytest.raises(CompanionError):
        scoped_catalog(catalog, effects="delete")


def test_running_compact_receipt_resumes_same_job():
    result = compact_job(
        {
            "job_id": "abc",
            "state": "running",
            "phase": "frame_2_of_5",
            "result": {"huge": "x" * 100000},
        }
    )
    assert "job wait abc" in result["next_command"]
    assert result["resubmit"] is False
    assert len(json.dumps(result)) < 1000


def test_compact_batch_preserves_created_paths_and_undo():
    result = compact_job(
        {
            "job_id": "abc",
            "state": "succeeded",
            "result": {
                "changed": [{"path": "/obj/new"}],
                "aliases": {"new": "/obj/new"},
                "undo_job_id": "abc",
            },
        }
    )
    assert result["result"]["aliases"]["new"] == "/obj/new"
    assert result["result"]["undo_job_id"] == "abc"


def test_bounded_job_wait_uses_one_request_per_second_without_resubmit(monkeypatch):
    from houdini_companion.client import Client

    clock = [0.0]
    calls = []
    monkeypatch.setattr("houdini_companion.client.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "houdini_companion.client.time.sleep", lambda n: clock.__setitem__(0, clock[0] + n)
    )
    c = Client(descriptor={})
    c.identity = {"capabilities": {"bounded_job_wait": True}}

    def call(action, **kw):
        calls.append(action)
        clock[0] += kw.get("wait_seconds", 0)
        return {"job_id": "one", "state": "succeeded" if clock[0] >= 5 else "running"}

    monkeypatch.setattr(c, "call", call)
    assert c.wait("one", timeout=10)["state"] == "succeeded"
    assert calls == ["job"] + ["wait_job"] * 5


def test_cli_failed_stage_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        "houdini_companion.cli.Client",
        lambda **_kw: SimpleNamespace(
            run=lambda *_a: {
                "job_id": "one",
                "state": "succeeded",
                "result": {"accepted_basic_checks": False},
            }
        ),
    )
    assert (
        main(
            ["submit", "iteration.stage", "--json", '{"capture_id":"x","snippet":""}', "--compact"]
        )
        == 1
    )
    assert not json.loads(capsys.readouterr().out)["ok"]


def test_inline_candidate_is_discoverable_and_missing_work_is_rejected():
    from houdini_companion.plugins.iteration import stage

    load_registry().validate("iteration.stage", {"capture_id": "x", "snippet": "@P.x+=1;"})
    with pytest.raises(CompanionError) as exc:
        stage(None, None, "x")
    assert exc.value.code == "EMPTY_CANDIDATE"


def test_cli_errors_are_json(capsys):
    assert main(["time", "explode"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "ARGUMENT"


def test_stdin_recipe(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"tracks":[]}'))
    assert recipe("-") == {"tracks": []}


@pytest.mark.parametrize(
    "op,params",
    [
        ("timeline.sample", {"path": "x", "frames": [1]}),
        ("timeline.sample", {"path": "x", "frames": [1, float("nan")]}),
        ("animation.keyframes", {"tracks": [], "expected": {}}),
        (
            "animation.keyframes",
            {
                "tracks": [
                    {"path": "p", "keys": [{"frame": 1, "value": 0}], "interpolation": "eval(code)"}
                ],
                "expected": {},
            },
        ),
    ],
)
def test_temporal_contract_bounds(op, params):
    with pytest.raises(CompanionError):
        load_registry().validate(op, params)


@pytest.mark.performance
def test_million_point_motion_budget(benchmark):
    import numpy as np

    a = np.zeros((1000000, 3), dtype=np.float32).tobytes()
    b = np.ones((1000000, 3), dtype=np.float32).tobytes()
    assert benchmark(displacement, a, b, 1)["moved_points"] == 1000000
    assert benchmark.stats["median"] < 0.25
