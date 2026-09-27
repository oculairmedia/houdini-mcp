import copy
import threading
from types import SimpleNamespace

import pytest

from houdini_companion.core import CompanionError, Ledger
from houdini_companion.registry import OperationSpec, PluginSpec, Registry, load_registry


def spec(name="example.echo", handler=None):
    return OperationSpec(
        name,
        "read",
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler or (lambda _ctx, _job, value: {"value": value}),
    )


def test_extension_dispatch_and_immutable_contract():
    op = spec()
    registry = Registry([PluginSpec("example", "1.0", (op,))])
    op.schema["required"].append("modified")
    exported = registry.catalog()
    exported["parameters"]["example.echo"]["required"].append("modified")
    context = SimpleNamespace(ledger=SimpleNamespace(checkpoint=lambda _jid: None))
    assert registry.dispatch(
        context, {"job_id": "one", "operation": "example.echo", "params": {"value": 3}}
    ) == {"value": 3}
    with pytest.raises(CompanionError, match="schema"):
        registry.validate("example.echo", {"value": True})


@pytest.mark.parametrize(
    "plugins,code",
    [
        ([PluginSpec("x", "1", (spec(),), api_version=99)], "PLUGIN_API"),
        ([PluginSpec("x", "1", (spec(),), requires=("absent",))], "PLUGIN_DEPENDENCY"),
        (
            [PluginSpec("x", "1", (), requires=("y",)), PluginSpec("y", "1", (), requires=("x",))],
            "PLUGIN_DEPENDENCY",
        ),
        ([PluginSpec("x", "1", (spec(),)), PluginSpec("y", "1", (spec(),))], "OPERATION_CONFLICT"),
        ([PluginSpec("x", "1", ()), PluginSpec("x", "2", ())], "PLUGIN_CONFLICT"),
    ],
)
def test_plugin_failures_are_explicit(plugins, code):
    with pytest.raises(CompanionError) as exc:
        Registry(plugins)
    assert exc.value.code == code


def test_builtin_contracts_reject_nested_invalid_review_requirements():
    registry = load_registry()
    with pytest.raises(CompanionError):
        registry.validate(
            "review.accept", {"path": "/obj/geo/box", "requirements": {"min_coverage": 2}}
        )
    with pytest.raises(CompanionError):
        registry.validate("query.geometry", {"path": "/obj/geo/box", "limit": 1000000})
    assert set(registry.effects()) >= {
        "iteration.capture",
        "iteration.stage",
        "iteration.apply",
        "iteration.restore",
        "iteration.release",
    }


def test_plugin_result_must_be_json_object():
    registry = Registry([PluginSpec("x", "1", (spec(handler=lambda *_a, **_kw: object()),))])
    context = SimpleNamespace(ledger=SimpleNamespace(checkpoint=lambda _jid: None))
    with pytest.raises(CompanionError) as exc:
        registry.dispatch(
            context, {"job_id": "one", "operation": "example.echo", "params": {"value": 3}}
        )
    assert exc.value.code == "PLUGIN_RESULT"


def test_wait_is_notified_on_completion_and_cancel(tmp_path):
    ledger = Ledger(tmp_path)
    request = {
        "version": 1,
        "session_id": ledger.session_id,
        "scene_id": ledger.scene_id,
        "request_id": "one",
        "operation": "inspect",
        "params": {},
    }
    first = ledger.submit(request)
    result = []
    waiter = threading.Thread(target=lambda: result.append(ledger.wait(first["job_id"], 2)))
    waiter.start()
    ledger.cancel(first["job_id"])
    waiter.join(1)
    assert not waiter.is_alive()
    assert result[0]["state"] == "cancelled"


def test_acceptance_rejects_incomplete_or_stale_evidence():
    from houdini_companion.plugins.acceptance import evaluate

    good = {
        "geometry": {
            "points": 8,
            "primitives": 6,
            "attributes": {"point": ["P"]},
            "checks": {"nonfinite_point_count": 0, "zero_area_count": 0, "complete": True},
        },
        "images": [{"suspect_blank_or_dark": False, "alpha_coverage": 0.3}],
        "stale": False,
        "warnings": [],
    }
    assert evaluate(good, {"min_coverage": 0.1})["accepted"]
    assert not evaluate(good, {"required_point_attributes": ["missing"]})["accepted"]
    for field in ["stale", "incomplete"]:
        bad = copy.deepcopy(good)
        if field == "stale":
            bad["stale"] = True
        else:
            bad["geometry"]["checks"]["complete"] = False
        assert not evaluate(bad, {})["accepted"]


def test_external_module_uses_same_discovery_and_dispatch_contract():
    registry = load_registry(["examples.companion_plugins.diagnostics"])
    context = SimpleNamespace(
        ledger=SimpleNamespace(checkpoint=lambda _jid: None),
        hou=SimpleNamespace(frame=lambda: 42, applicationVersionString=lambda: "test"),
    )
    result = registry.dispatch(
        context, {"job_id": "one", "operation": "example.frame", "params": {}}
    )
    assert result == {"frame": 42, "houdini": "test"}
    assert registry.catalog()["contracts"]["example.frame"]["plugin"] == "example.diagnostics"


def test_unknown_schema_constraints_fail_at_registration():
    op = spec()
    op.schema["properties"]["value"]["multipleOf"] = 2
    with pytest.raises(CompanionError) as exc:
        Registry([PluginSpec("example", "1", (op,))])
    assert exc.value.code == "PLUGIN_SCHEMA"


def test_watcher_uses_observed_file_version_not_a_later_disk_version(tmp_path):
    from houdini_companion.watchers import Watchers

    watcher = object.__new__(Watchers)
    watcher.files, watcher.nodes = {}, {}
    path = tmp_path / "source.h"
    path.write_text("new version after snapshot")
    watcher.track(
        {
            "observation": {
                "token": "old",
                "dependency_paths": [],
                "sources": [{"path": str(path), "mtime_ns": 1, "bytes": 3}],
            }
        }
    )
    assert watcher.files[str(path)] == (1, 3)
    assert watcher.files[str(path)] != watcher.stat(path)
