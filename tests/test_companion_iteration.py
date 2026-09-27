import base64
import json
from types import SimpleNamespace

import pytest

from houdini_companion import transactions as tx
from houdini_companion.errors import CompanionError
from houdini_companion.plugins.iteration import stage_sources
from houdini_companion.registry import load_registry


def test_source_transaction_rolls_back_files_and_scene_on_failure(tmp_path):
    paths = [tmp_path / name for name in ("one.h", "two.h")]
    for p in paths:
        p.write_bytes(b"original\r\n")
    records = [tx.record(p, b"candidate") for p in paths]
    calls = []

    def mutate():
        assert all(p.read_bytes() == b"candidate" for p in paths)
        raise RuntimeError("cook failed")

    with pytest.raises(RuntimeError, match="cook failed"):
        tx.transact(records, tmp_path / "journal.json", mutate, lambda: calls.append("revert"))
    assert calls == ["revert"]
    assert all(p.read_bytes() == b"original\r\n" for p in paths)
    journal = json.loads((tmp_path / "journal.json").read_text())
    assert journal["state"] == "rolled_back"
    assert base64.b64decode(journal["files"][0]["before"]) == b"original\r\n"


def test_stale_transaction_never_calls_mutation(tmp_path):
    p = tmp_path / "source.h"
    p.write_bytes(b"old")
    records = [tx.record(p, b"new")]
    p.write_bytes(b"artist edit")
    with pytest.raises(CompanionError) as exc:
        tx.transact(
            records, tmp_path / "journal.json", lambda: pytest.fail("mutated"), lambda: None
        )
    assert exc.value.code == "STALE_SOURCE"
    assert p.read_bytes() == b"artist edit"


def test_partial_write_failure_restores_preceding_files(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    original = tx.replace_bytes

    def replace(path, data):
        if str(path) == str(b) and data == b"new":
            raise OSError("disk full")
        original(path, data)

    monkeypatch.setattr(tx, "replace_bytes", replace)
    with pytest.raises(OSError, match="disk full"):
        tx.transact(
            [tx.record(a, b"new"), tx.record(b, b"new")],
            tmp_path / "j.json",
            lambda: None,
            lambda: None,
        )
    assert a.read_bytes() == b"a"
    assert b.read_bytes() == b"b"


def test_rollback_preserves_concurrent_edit_and_records_recovery_failure(tmp_path):
    p = tmp_path / "a"
    p.write_bytes(b"old")
    records = [tx.record(p, b"new")]

    def mutate():
        p.write_bytes(b"artist")
        raise ValueError("abort")

    with pytest.raises(CompanionError) as exc:
        tx.transact(records, tmp_path / "j.json", mutate, lambda: None)
    assert exc.value.code == "ROLLBACK_FAILED"
    assert p.read_bytes() == b"artist"
    assert json.loads((tmp_path / "j.json").read_text())["state"] == "rollback_failed"


def test_success_and_reverse_transaction_preserve_exact_bytes(tmp_path):
    p = tmp_path / "a"
    p.write_bytes(b"old\r\n")
    records = [tx.record(p, b"new\n")]
    assert tx.transact(records, tmp_path / "j.json", lambda: {"ok": True}, lambda: None) == {
        "ok": True
    }
    assert json.loads((tmp_path / "j.json").read_text())["state"] == "applied"
    tx.check_files(records, "after")


def test_stages_nested_includes_from_immutable_capture_and_rejects_new_dependencies(tmp_path):
    a, b = tmp_path / "a.h", tmp_path / "b.h"
    a.write_text('#include "b.h"\n', encoding="utf-8")
    b.write_text("original", encoding="utf-8")
    records = [tx.record(a, a.read_bytes()), tx.record(b, b"reviewed")]
    b.write_text("external edit", encoding="utf-8")
    out = tmp_path / "stage"
    out.mkdir()
    hou = SimpleNamespace(expandString=lambda x: x)
    text = stage_sources(hou, '#include "' + a.as_posix() + '"', records, out)
    assert str(out).replace("\\", "/") in text
    assert any(p.read_text() == "reviewed" for p in out.iterdir())
    with pytest.raises(CompanionError) as exc:
        stage_sources(hou, '#include "missing.h"', records, out)
    assert exc.value.code == "UNRESOLVED_INCLUDE"


def test_source_cache_preserves_mtime_and_rejects_tampering(tmp_path):
    source = tmp_path / "source.h"
    source.write_bytes(b"code")
    records = [tx.record(source, b"candidate")]
    folder = tmp_path / "cache"
    folder.mkdir()
    hou = SimpleNamespace(expandString=lambda x: x)
    snippet = '#include "' + source.as_posix() + '"'
    stage_sources(hou, snippet, records, folder)
    cached = next(folder.iterdir())
    stamp = cached.stat().st_mtime_ns
    stage_sources(hou, snippet, records, folder)
    assert cached.stat().st_mtime_ns == stamp
    cached.write_text("unexpected edit")
    with pytest.raises(CompanionError) as exc:
        stage_sources(hou, snippet, records, folder)
    assert exc.value.code == "ARTIFACT_CHANGED"


def test_semantic_comparison_tracks_geometry_not_serialization_date():
    from houdini_companion.diagnostics import semantic_hash

    attr = SimpleNamespace(
        name=lambda: "P",
        isArrayType=lambda: False,
        dataType=lambda: SimpleNamespace(name=lambda: "Float"),
        size=lambda: 3,
    )
    values = [b"positions"]
    geo = SimpleNamespace(
        pointAttribs=lambda: [attr],
        primAttribs=lambda: [],
        vertexAttribs=lambda: [],
        globalAttribs=lambda: [],
        pointFloatAttribValuesAsString=lambda _name: values[0],
        date="yesterday",
    )
    original = semantic_hash(geo, b"Poly:1:0,1,2")
    geo.date = "today"
    assert semantic_hash(geo, b"Poly:1:0,1,2") == original
    assert semantic_hash(geo, b"Poly:1:0,2,1") != original
    values[0] = b"different positions"
    assert semantic_hash(geo, b"Poly:1:0,1,2") != original


@pytest.mark.parametrize(
    "operation,params",
    [
        ("iteration.stage", {"capture_id": "id", "files": []}),
        (
            "iteration.stage",
            {"capture_id": "id", "files": [{"path": "x", "content": "y"}], "benchmark_samples": 50},
        ),
        ("iteration.capture", {"path": "/obj/geo/w", "resolution": 0}),
        ("iteration.apply", {"stage_id": "id", "ignore_stale": True}),
    ],
)
def test_iteration_contracts_reject_invalid_requests(operation, params):
    with pytest.raises(CompanionError):
        load_registry().validate(operation, params)


def test_bulk_point_checks_detect_outlier_beyond_old_sample_limit():
    import numpy as np

    from houdini_companion.diagnostics import point_checks

    points = np.zeros((100001, 3), dtype=np.float32)
    points[99999, 2] = np.nan
    points[100000, 1] = np.inf
    result = point_checks(points.tobytes())
    assert result == {"nonfinite_point_count": 2, "nonfinite_points": [99999, 100000]}


@pytest.mark.performance
def test_bulk_million_point_budget(benchmark):
    import numpy as np

    from houdini_companion.diagnostics import point_checks

    data = np.zeros((1000000, 3), dtype=np.float32).tobytes()
    result = benchmark(point_checks, data)
    assert result["nonfinite_point_count"] == 0
    assert benchmark.stats["median"] < 0.25


def test_automatic_framing_centers_sparse_point_projection_with_margin():
    import numpy as np

    from houdini_companion.rendering import projected_window

    points = np.array([[-2, -8, -10], [4, -2, -10], [0, -6, -20]], dtype=np.float32)
    x, y, size = projected_window(points.tobytes(), np.eye(4), 0.5)
    projected = points[:, :2] / (-points[:, 2, None] * 0.5)
    framed = (projected - 2 * np.array([x, y])) / size
    assert np.allclose(framed.min(axis=0) + framed.max(axis=0), 0, atol=1e-6)
    assert np.max(np.abs(framed)) == pytest.approx(0.8)


def test_automatic_framing_rejects_points_behind_camera():
    import numpy as np

    from houdini_companion.rendering import projected_window

    with pytest.raises(CompanionError) as exc:
        projected_window(np.array([[0, 0, 1]], dtype=np.float32).tobytes(), np.eye(4), 0.5)
    assert exc.value.code == "INVALID_FRAMING"
