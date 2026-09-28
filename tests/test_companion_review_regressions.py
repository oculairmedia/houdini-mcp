"""Failure paths found in the source review of PR #38 at a0d50af."""

import copy
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from houdini_companion.core import Ledger, atomic_json, digest
from houdini_companion.errors import CompanionError
from houdini_companion.operations import Operations
from houdini_companion.plugins import boundary, build, delivery, render_sequence, scene
from houdini_companion.runtime import Runtime
from tests.test_companion_workflow import fake_hou


def windows_sddl(path):
    from ctypes import wintypes as w

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.GetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        w.LPVOID,
        w.DWORD,
        w.DWORD,
        ctypes.POINTER(w.LPWSTR),
        ctypes.POINTER(w.DWORD),
    ]
    needed = w.DWORD()
    api.GetFileSecurityW(str(path), 4, None, 0, ctypes.byref(needed))
    buffer = ctypes.create_string_buffer(needed.value)
    assert api.GetFileSecurityW(str(path), 4, buffer, needed, ctypes.byref(needed))
    text = w.LPWSTR()
    assert api.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        buffer, 1, 4, ctypes.byref(text), None
    )
    try:
        return text.value
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [w.LPVOID]
        free(text)


def test_descriptor_permissions_exist_before_token_write_and_after_publish(tmp_path, monkeypatch):
    original = os.fdopen
    checked = []

    def inspect(fd, *args, **kwargs):
        assert os.fstat(fd).st_size == 0
        temp = next(tmp_path.glob("*.tmp"))
        if os.name == "nt":
            sddl = windows_sddl(temp)
            assert "D:P" in sddl and sddl.count("(A;") == 2
            assert ";;;SY)" in sddl and ";;;S-1-5-21-" in sddl
            assert not re.search(r";;;(?:WD|BU|AU|BA)\)", sddl)
        else:
            assert os.fstat(fd).st_mode & 0o777 == 0o600
        checked.append(True)
        return original(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", inspect)
    old_umask = os.umask(0)
    try:
        target = tmp_path / "session.json"
        atomic_json(target, {"token": "fixture-token"}, private=True)
        assert checked and json.loads(target.read_text())["token"] == "fixture-token"
        if os.name == "nt":
            assert "D:P" in windows_sddl(target)
        else:
            assert target.stat().st_mode & 0o777 == 0o600
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        os.umask(old_umask)


def test_descriptor_permission_failure_never_publishes(tmp_path, monkeypatch):
    def fail(*_a, **_k):
        raise OSError("private file creation denied")

    if os.name == "nt":
        import houdini_companion.private_file as private

        monkeypatch.setattr(private, "windows_private_fd", fail)
    else:
        monkeypatch.setattr("houdini_companion.core.tempfile.mkstemp", fail)
    target = tmp_path / "session.json"
    target.write_text("existing")
    with pytest.raises(OSError):
        atomic_json(target, {"token": "must-not-be-written"}, private=True)
    assert target.read_text() == "existing" and len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("dirty", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_copy_save_never_calls_save_as_or_changes_hip_state(tmp_path, dirty, failure):
    env = {"HOUDINI_BACKUP_DIR": "artist-backups"}
    values = {"path": "artist.hip", "dirty": dirty}

    def backup():
        assert env["HOUDINI_BACKUP_DIR"] != "artist-backups"
        if failure:
            raise OSError("backup failed")
        path = Path(env["HOUDINI_BACKUP_DIR"]) / "artist_bak1.hip"
        path.write_bytes(b"current unsaved scene")
        return str(path)

    h = NS(
        getenv=env.get,
        putenv=env.__setitem__,
        unsetenv=lambda k: env.pop(k, None),
        hipFile=NS(
            path=lambda: str(tmp_path / "original.hip"),
            saveAsBackup=backup,
            save=lambda **_k: pytest.fail("Save As clears dirty state"),
        ),
    )
    (tmp_path / "original.hip").write_bytes(b"old")
    before = dict(values)
    if failure:
        with pytest.raises(OSError):
            delivery.save_copy(h, tmp_path / "copy.hip", tmp_path / "job")
    else:
        saved = delivery.save_copy(h, tmp_path / "copy.hip", tmp_path / "job")
        assert saved.read_bytes() == b"current unsaved scene"
    assert values == before and env["HOUDINI_BACKUP_DIR"] == "artist-backups"


@pytest.mark.parametrize("dirty", [False, True])
def test_scene_save_copy_preserves_dirty_flag_at_operation_boundary(tmp_path, monkeypatch, dirty):
    h, _time = fake_hou()
    original = tmp_path / "artist.hip"
    original.write_bytes(b"old")
    hip = {"path": str(original), "dirty": dirty}
    env = {}

    def save_as(file_name):
        hip.update(path=file_name, dirty=False)
        Path(file_name).write_bytes(b"saved")

    def backup():
        target = Path(env["HOUDINI_BACKUP_DIR"]) / "artist_bak.hip"
        target.write_bytes(b"saved")
        return str(target)

    h.hipFile = NS(
        path=lambda: hip["path"],
        hasUnsavedChanges=lambda: hip["dirty"],
        save=save_as,
        setName=lambda p: hip.update(path=p),
        saveAsBackup=backup,
    )
    h.getenv, h.putenv, h.unsetenv = env.get, env.__setitem__, lambda k: env.pop(k, None)
    h.node = lambda _p: NS(
        geometry=lambda: None, geometryAtFrame=lambda _f: None, errors=lambda: []
    )
    monkeypatch.setattr(delivery, "fingerprint", lambda *_a: {"sources": []})
    monkeypatch.setattr(delivery, "geometry_signature", lambda _g: {})
    ctx = NS(hou=h, state={}, ledger=NS(root=tmp_path / "artifacts"))
    delivery.save(ctx, {"job_id": "save"}, str(tmp_path / "copy.hip"), ["/obj/g/out"])
    assert hip == {"path": str(original), "dirty": dirty}


def test_never_saved_scene_uses_native_copy_not_save_as(tmp_path):
    commands = []
    env = {}

    def native(command):
        commands.append(command)
        (tmp_path / "job/hip-copy/scene.hip").write_bytes(b"new scene")
        return "", ""

    h = NS(
        hipFile=NS(
            path=lambda: str(tmp_path / "untitled.hip"),
            save=lambda **_k: pytest.fail("must not save-as"),
        ),
        getenv=env.get,
        putenv=env.__setitem__,
        unsetenv=lambda k: env.pop(k, None),
        hscript=native,
    )
    target = delivery.save_copy(h, tmp_path / "copy.hip", tmp_path / "job")
    assert target.read_bytes() == b"new scene" and commands[0].startswith('mwrite -n "')


def test_review_release_preserves_published_evidence(tmp_path):
    from houdini_companion.plugins.publication import release

    manifest = tmp_path / "review.json"
    manifest.write_text("published")
    ctx = NS(state={"reviews": {"review": {"manifest": str(manifest)}}})
    result = release(ctx, {}, "review")
    assert not result["published_files_deleted"] and manifest.read_text() == "published"
    assert not ctx.state["reviews"]


def test_private_descriptor_failure_stops_listener_and_removes_callbacks(tmp_path, monkeypatch):
    import houdini_companion.runtime as module

    stopped, callbacks = [], []
    server = NS(
        urlHandler=lambda _p: lambda _fn: None,
        setPortInfo=lambda *_a: None,
        run=lambda **_kw: None,
        requestShutdown=lambda: stopped.append(True),
    )
    monkeypatch.setitem(sys.modules, "hwebserver", NS(Server=lambda _n: server))

    def denied(*_a, **kw):
        assert kw["private"]
        raise OSError("descriptor denied")

    monkeypatch.setattr(module, "atomic_json", denied)
    runtime = Runtime.__new__(Runtime)
    runtime.ledger = Ledger(tmp_path / "jobs")
    runtime.operations = Operations(NS(), runtime.ledger)
    runtime.watchers = NS(clear=lambda: None)
    runtime.hou = NS(
        ui=NS(addEventLoopCallback=callbacks.append, removeEventLoopCallback=callbacks.remove),
        hipFile=NS(addEventCallback=callbacks.append, removeEventCallback=callbacks.remove),
    )
    runtime.port, runtime.token = 18800, "fixture-only"
    runtime.tick_callback, runtime.hip_callback = object(), object()
    runtime.descriptor = tmp_path / "session.json"
    with pytest.raises(OSError):
        runtime.start()
    assert stopped == [True] and not callbacks and not runtime.descriptor.exists()
    assert not runtime.ledger.accepting


def batch_fixture(monkeypatch):
    nodes = {}

    class Node:
        serial = 0

        def __init__(self, path):
            Node.serial += 1
            self.id, self._path, self.value = Node.serial, path, 0
            nodes[path] = self

        def path(self):
            return self._path

        def sessionId(self):
            return self.id

        def node(self, name):
            return nodes.get(self._path + "/" + name)

        def createNode(self, _type, name):
            return Node(self._path + "/" + name)

        def destroy(self):
            del nodes[self._path]

        def parm(self, name):
            return NS(set=lambda v: setattr(self, "value", v)) if name == "x" else None

        def parmTuple(self, _name):
            return None

    root, original = Node("/obj/g"), Node("/obj/g/n")
    h = NS(node=nodes.get, ObjectWasDeleted=RuntimeError)
    monkeypatch.setattr(
        scene, "check_expected", lambda _h, n, token: token == str(n.id) or pytest.fail("token")
    )
    context = NS(hou=h, ledger=NS(), state={})
    return scene.Handlers(context), root, original, nodes


def test_batch_rejects_delete_recreate_literal_before_any_mutation(monkeypatch):
    handler, root, original, nodes = batch_fixture(monkeypatch)
    actions = [
        {"op": "delete", "path": original.path()},
        {"op": "create", "parent": root.path(), "type": "null", "name": "n", "as": "new"},
        {"op": "set", "path": original.path(), "values": {"x": 7}},
    ]
    with pytest.raises(CompanionError) as exc:
        handler._validate_actions(actions, {n.path(): str(n.id) for n in (root, original)})
    assert exc.value.code == "TARGET_DELETED" and nodes[original.path()] is original


def test_batch_replacement_uses_explicit_new_alias(monkeypatch):
    handler, root, original, nodes = batch_fixture(monkeypatch)
    actions = [
        {"op": "delete", "path": original.path()},
        {"op": "create", "parent": root.path(), "type": "null", "name": "n", "as": "new"},
        {"op": "set", "path": "$new", "values": {"x": 7}},
    ]
    bound = handler._validate_actions(actions, {n.path(): str(n.id) for n in (root, original)})
    handler._apply_actions(actions, bound)
    assert nodes[original.path()] is not original and nodes[original.path()].value == 7


def test_batch_bound_target_cannot_be_replaced_after_preflight(monkeypatch):
    handler, root, original, nodes = batch_fixture(monkeypatch)
    actions = [{"op": "set", "path": original.path(), "values": {"x": 7}}]
    bound = handler._validate_actions(actions, {original.path(): str(original.id)})
    replacement = root.createNode("null", "n")
    with pytest.raises(CompanionError, match="identity changed"):
        handler._apply_actions(actions, bound)
    assert replacement.value == 0 and original.value == 0


def test_batch_rejects_deleted_ancestor_alias_before_mutation(monkeypatch):
    handler, root, original, nodes = batch_fixture(monkeypatch)
    actions = [
        {"op": "create", "parent": root.path(), "type": "geo", "name": "new", "as": "parent"},
        {"op": "create", "parent": "$parent", "type": "null", "name": "child", "as": "child"},
        {"op": "delete", "path": "$parent"},
        {"op": "set", "path": "$child", "values": {"x": 7}},
    ]
    with pytest.raises(CompanionError) as exc:
        handler._validate_actions(actions, {root.path(): str(root.id)})
    assert exc.value.code == "TARGET_DELETED" and len(nodes) == 2


def test_running_verifiers_survive_scene_reset_and_are_reaped_on_stop(tmp_path):
    ctx = Operations(NS(), Ledger(tmp_path))
    processes = [
        subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"]) for _ in range(2)
    ]
    try:
        cancelled = []
        records = {
            str(i): {
                "process": p,
                "timer": NS(cancel=lambda: cancelled.append(True)),
                "save_id": "s",
                "folder": tmp_path,
            }
            for i, p in enumerate(processes)
        }
        ctx.state.update(builds={"old": {}}, deliverables={"s": "manifest"}, save_verifiers=records)
        runtime = Runtime.__new__(Runtime)
        runtime.ledger, runtime.operations = ctx.ledger, ctx
        runtime.watchers = NS(clear=lambda: None)
        runtime.hou = NS(
            hipFileEventType=NS(BeforeLoad=1, BeforeClear=2),
            ui=NS(removeEventLoopCallback=lambda _c: None),
            hipFile=NS(removeEventCallback=lambda _c: None),
        )
        runtime.tick_callback, runtime.hip_callback = None, None
        runtime.server, runtime.descriptor = None, tmp_path / "absent.json"
        old_scene = ctx.ledger.scene_id
        runtime.hip_event(1)
        assert ctx.ledger.scene_id != old_scene and "builds" not in ctx.state
        assert (
            ctx.state["save_verifiers"] is records and ctx.state["deliverables"]["s"] == "manifest"
        )
        assert delivery.verify_status(ctx, {}, "0")["state"] == "running"
        with pytest.raises(CompanionError) as exc:
            delivery.verify_start(ctx, {}, "s")
        assert exc.value.code == "VERIFY_BUSY"
        runtime.stop()
        assert len(cancelled) == 2 and all(p.poll() is not None for p in processes)
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)


def review_fixture(tmp_path, monkeypatch):
    h, values = fake_hou()
    values["frame"] = 1
    signature, source = {}, {}
    geo = NS(
        intrinsicValue=lambda _n: 1,
        findPointAttrib=lambda _n: NS(size=lambda: 1, dataType=lambda: "int"),
        pointIntAttribValues=lambda _n: [1],
        pointFloatAttribValuesAsString=lambda _n: np.zeros((1, 3), np.float32).tobytes(),
    )
    node = NS(geometry=lambda: geo, errors=lambda: ())
    h.node = lambda _p: node
    h.attribData = NS(Int="int", String="string")
    monkeypatch.setattr(
        "houdini_companion.continuity.image_pixels", lambda _p: np.zeros((2, 2, 3), np.uint8)
    )

    def check(_h, _n, expected):
        if expected != source.get(h.frame(), "original"):
            raise CompanionError("STALE_INPUT", "source changed at sample frame")

    monkeypatch.setattr(render_sequence, "check_expected", check)
    monkeypatch.setattr(boundary, "check_expected", check)
    monkeypatch.setattr(
        render_sequence, "geometry_signature", lambda _g: signature.get(h.frame(), "geometry")
    )
    folder = tmp_path / "render"
    folder.mkdir()
    rows = []
    for i, frame in enumerate((1, 2)):
        items = []
        for kind in ("bgeo", "png"):
            name = f"{i}.{kind}"
            (folder / name).write_bytes(b"evidence")
            items.append({"name": name, "sha256": hashlib.sha256(b"evidence").hexdigest()})
        rows.append(
            {
                "frame": frame,
                "source_observation": "original",
                "geometry_signature": "geometry",
                "geometry_artifact": items[0],
                "images": items[1:],
            }
        )
    data = {
        "frames": [1, 2],
        "path": "/obj/g/n",
        "anchor_frame": 1,
        "expected": "original",
        "camera_tokens": {},
        "recipes": {"view0": {}},
        "rows": rows,
        "session_id": "session",
        "scene_id": "scene",
    }
    (folder / "render-sequence.json").write_text(json.dumps(data))
    ctx = NS(
        hou=h,
        ledger=NS(root=tmp_path, scene_id="scene", session_id="session"),
        state={"render_sequences": {"render": True}},
    )
    return ctx, values, source, signature, folder, data


@pytest.mark.parametrize(
    "fault,code",
    [
        ("source", "STALE_INPUT"),
        ("geometry", "UNALIGNED_EVIDENCE"),
        ("artifact", "ARTIFACT_CORRUPT"),
    ],
)
def test_boundary_rejects_changed_nonanchor_evidence_and_restores_time(
    tmp_path, monkeypatch, fault, code
):
    ctx, values, source, signature, folder, _data = review_fixture(tmp_path, monkeypatch)
    before = copy.deepcopy(values)
    if fault == "source":
        source[2] = "frame-dependent edit"
    elif fault == "geometry":
        signature[2] = "changed geometry despite unchanged parameters"
    else:
        (folder / "1.bgeo").write_bytes(b"corrupt")
    with pytest.raises(CompanionError) as exc:
        boundary.boundary(ctx, {}, "/obj/g/n", 1, 2, render_id="render")
    assert exc.value.code == code and values == before


def test_boundary_rejects_rows_bound_to_wrong_frame(tmp_path, monkeypatch):
    ctx, values, _source, _sig, folder, data = review_fixture(tmp_path, monkeypatch)
    data["rows"][1]["frame"] = 1
    (folder / "render-sequence.json").write_text(json.dumps(data))
    before = copy.deepcopy(values)
    with pytest.raises(CompanionError) as exc:
        boundary.boundary(ctx, {}, data["path"], 1, 2, render_id="render")
    assert exc.value.code == "UNALIGNED_EVIDENCE" and values == before


@pytest.mark.parametrize(
    "fault,code",
    [
        ("missing", "REVIEW_REQUIRED"),
        ("partial", "INCOMPLETE_REVIEW"),
        ("source", "STALE_INPUT"),
        ("artifact", "ARTIFACT_CORRUPT"),
        ("manifest", "ARTIFACT_CORRUPT"),
    ],
)
def test_promotion_requires_exact_complete_review(tmp_path, monkeypatch, fault, code):
    ctx, values, source, _sig, folder, data = review_fixture(tmp_path, monkeypatch)
    root = NS(
        name=lambda: "candidate",
        isDisplayFlagSet=lambda: False,
        setName=lambda *_a, **_k: pytest.fail("must not promote"),
        setDisplayFlag=lambda _v: pytest.fail("must not expose"),
    )
    value = {
        "output": data["path"],
        "expected": "original",
        "anchor_frame": 1,
        "review_frames": [1, 2],
        "name": "ready",
    }
    monkeypatch.setattr(build, "record", lambda *_a: (value, root))
    monkeypatch.setattr(build, "check_expected", lambda *_a: None)
    manifest = folder / "review.json"
    if fault == "partial":
        data["rows"][1] = None
    manifest.write_text(json.dumps(data))
    ctx.state["reviews"] = {
        "review": {"path": data["path"], "manifest": str(manifest), "manifest_digest": digest(data)}
    }
    if fault == "missing":
        ctx.state["reviews"].clear()
    elif fault == "source":
        source[2] = "later edit"
    elif fault == "artifact":
        (folder / "1.png").write_bytes(b"changed")
    elif fault == "manifest":
        manifest.write_text("{}")
    before = copy.deepcopy(values)
    with pytest.raises(CompanionError) as exc:
        build.promote(ctx, {}, "build", review_id="review")
    assert exc.value.code == code and values == before


def test_complete_review_promotes_once_and_consumes_receipt(tmp_path, monkeypatch):
    ctx, values, _source, _sig, folder, data = review_fixture(tmp_path, monkeypatch)
    node = ctx.hou.node(data["path"])
    ctx.hou.node = lambda p: node if p == data["path"] else None
    changes = []
    root = NS(
        name=lambda: "candidate",
        isDisplayFlagSet=lambda: False,
        setName=lambda name, **_kw: changes.append(("name", name)),
        setDisplayFlag=lambda v: changes.append(("display", v)),
        path=lambda: "/obj/ready",
    )
    value = {
        "output": data["path"],
        "expected": "original",
        "anchor_frame": 1,
        "review_frames": [1, 2],
        "name": "ready",
        "validation": {"accepted": True},
    }
    ctx.state["builds"] = {"build": value}

    def record(_ctx, key):
        if key not in ctx.state["builds"]:
            raise CompanionError("BUILD_NOT_FOUND", "consumed")
        return value, root

    monkeypatch.setattr(build, "record", record)
    monkeypatch.setattr(build, "check_expected", lambda *_a: None)
    manifest = folder / "review.json"
    manifest.write_text(json.dumps(data))
    ctx.state["reviews"] = {
        "review": {"path": data["path"], "manifest": str(manifest), "manifest_digest": digest(data)}
    }
    before = copy.deepcopy(values)
    result = build.promote(ctx, {}, "build", review_id="review")
    assert result["review_id"] == "review" and values == before
    assert changes == [("name", "ready"), ("display", True)] and not ctx.state["reviews"]
    with pytest.raises(CompanionError) as exc:
        build.promote(ctx, {}, "build", review_id="review")
    assert exc.value.code == "BUILD_NOT_FOUND" and len(changes) == 2
