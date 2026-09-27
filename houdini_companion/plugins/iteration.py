"""Guarded VEX iteration over frozen inputs, with reusable evidence and recovery."""

import base64
import json
import time
from pathlib import Path

from ..core import atomic_json, digest
from ..diagnostics import audit, valid
from ..errors import CompanionError
from ..observation import INCLUDE, check_expected, fingerprint, require_node, source_files
from ..registry import OperationSpec, PluginSpec
from ..rendering import artifact, render_snapshot
from ..transactions import check_files, record, sha, transact
from .introspection import PATH, object_schema


def state(ctx):
    return ctx.state.setdefault("iteration", {})


def retain(ctx, job, value):
    value.update(scene_id=ctx.ledger.scene_id, receipt_id=job["job_id"])
    state(ctx)[job["job_id"]] = value
    atomic_json(ctx.ledger.root / job["job_id"] / "iteration.json", value)


def get(ctx, rid, kind):
    value = state(ctx).get(rid)
    if not value or value["scene_id"] != ctx.ledger.scene_id or value["kind"] != kind:
        raise CompanionError("ITERATION_EXPIRED", "Capture or stage is unavailable in this session")
    return value


def check(ctx, capture):
    node = require_node(ctx.hou, capture["path"])
    check_expected(ctx.hou, node, capture["observation"]["token"])
    for path, expected in capture["guards"].items():
        check_expected(ctx.hou, require_node(ctx.hou, path), expected)
    return node


def directory(ctx, job):
    path = ctx.ledger.root / job["job_id"]
    path.mkdir(exist_ok=True, parents=True)
    return path


def set_manifest(node, value):
    if value is not None:
        node.setUserData("houdini_companion_sources", value)
    elif node.userData("houdini_companion_sources") is not None:
        node.destroyUserData("houdini_companion_sources")


def evidence(ctx, job, node, folder, focus, views, resolution, cameras):
    start = time.perf_counter()
    ctx.ledger.phase(job["job_id"], "geometry_access")
    counts_before = node.cookCount()
    g = node.geometry()
    access_ms = (time.perf_counter() - start) * 1000
    if node.errors():
        raise CompanionError("COOK_FAILED", "; ".join(node.errors()))
    counts_after = node.cookCount()
    frozen = folder / "geometry.bgeo.sc"
    freeze_start = time.perf_counter()
    g.freeze().saveToFile(str(frozen))
    freeze_ms = (time.perf_counter() - freeze_start) * 1000
    ctx.ledger.phase(job["job_id"], "native_diagnostics")

    def checkpoint():
        ctx.ledger.checkpoint(job["job_id"])

    summary = audit(ctx.hou, frozen, checkpoint)
    ctx.ledger.phase(job["job_id"], "paired_render")
    render = render_snapshot(
        ctx.hou,
        frozen,
        folder,
        views,
        resolution,
        checkpoint,
        focus=focus,
        cameras=cameras,
    )
    result = {
        "geometry": summary,
        "geometry_artifact": artifact(frozen, "geometry"),
        **render,
        "warnings": list(node.warnings()),
        "stale": False,
        "timings": {
            "geometry_access_ms": access_ms,
            "freeze_ms": freeze_ms,
            "diagnostics_ms": summary["diagnostics_ms"],
            "render_ms": render["render_ms"],
            "total_ms": (time.perf_counter() - start) * 1000,
            "cook_count_delta": counts_after - counts_before,
            "classification": "may cook or reuse cache; not a regeneration benchmark",
        },
    }
    atomic_json(folder / "feedback.json", result)
    return result


def capture(ctx, job, path, guards=None, cameras=None, views=None, resolution=640):
    if len(state(ctx)) >= 64:
        raise CompanionError("ITERATION_LIMIT", "Release old captures before starting more")
    hou = ctx.hou
    node = require_node(hou, path)
    if node.type().name().split("::")[0] != "attribwrangle" or not node.matchesCurrentDefinition():
        raise CompanionError(
            "UNSUPPORTED_ITERATION", "Initial contract supports built-in attribute wrangles"
        )
    if any(p.keyframes() for p in node.parms()):
        raise CompanionError(
            "UNSUPPORTED_ITERATION", "Animated parameters require explicit staging"
        )
    node.geometry()
    if isinstance(node.parent(), hou.SopNode):
        node.parent().geometry()
    observation = fingerprint(hou, node)
    snippet = node.parm("snippet").eval()
    source_manifest = node.userData("houdini_companion_sources")
    authoring_snippet = (
        json.loads(source_manifest)["authoring_snippet"] if source_manifest else snippet
    )
    sources = source_files(hou, authoring_snippet)
    files = []
    for p in sources:
        if not Path(p).is_file() or Path(p).stat().st_size > 1024 * 1024:
            raise CompanionError("UNSUPPORTED_INCLUDE", p)
        files.append(record(p, Path(p).read_bytes()))
    folder = directory(ctx, job)
    guard_values = {p: fingerprint(hou, require_node(hou, p))["token"] for p in (guards or [])}
    recipes = {}
    # Captured camera transforms are converted to the SOP object's local coordinates.
    parent = node.parent()
    while not isinstance(parent, hou.ObjNode):
        parent = parent.parent()
    for index, path in enumerate(cameras or []):
        cam = require_node(hou, path)
        if cam.type().name() != "cam":
            raise CompanionError("CAMERA_REQUIRED", path)
        guard_values[path] = fingerprint(hou, cam)["token"]
        recipes[f"camera_{index}"] = {
            "transform": list(
                (cam.worldTransform() * parent.worldTransform().inverted()).asTuple()
            ),
            "parms": {
                p: cam.parm(p).eval()
                for p in (
                    "focal",
                    "aperture",
                    "projection",
                    "aspect",
                    "winx",
                    "winy",
                    "winsizex",
                    "winsizey",
                )
            },
            "source": path,
            "output_aspect": cam.parm("resx").eval() / cam.parm("resy").eval(),
        }
    selected_views = views or list(recipes) or ["front", "right", "persp"]
    inputs = []
    for connection in node.inputConnections():
        if connection.outputIndex() != 0:
            raise CompanionError("UNSUPPORTED_INPUT", "Only primary SOP outputs supported")
        index = connection.inputIndex()
        dest = folder / f"input_{index}.bgeo.sc"
        connection.inputNode().geometry().freeze().saveToFile(str(dest))
        inputs.append({"index": index, "path": str(dest), "sha256": sha(dest.read_bytes())})
    feedback = evidence(ctx, job, node, folder, None, selected_views, resolution, recipes)
    cap = {
        "kind": "capture",
        "path": node.path(),
        "observation": observation,
        "guards": guard_values,
        "snippet": snippet,
        "authoring_snippet": authoring_snippet,
        "source_manifest_before": source_manifest,
        "files": files,
        "inputs": inputs,
        "views": selected_views,
        "resolution": resolution,
        "cameras": feedback["camera_recipes"],
        "focus": feedback["geometry"]["bounds"],
        "feedback": feedback,
    }
    check(ctx, cap)
    retain(ctx, job, cap)
    return {
        "capture_id": job["job_id"],
        "feedback": feedback,
        "observation": observation,
        "source_paths": list(sources),
        "supported_scope": "trusted VEX with quoted includes, frozen direct inputs and guarded declared scene dependencies",
    }


def stage_sources(hou, text, files, folder):
    """Resolve all quoted includes to the captured bytes, rejecting new dependencies."""
    by_path = {str(Path(f["path"]).resolve()): f for f in files}
    visited = {}

    def expand(source, parent=None):
        def replace(match):
            p = Path(hou.expandString(match.group(1)))
            if not p.is_absolute():
                if parent is None:
                    raise CompanionError("UNRESOLVED_INCLUDE", str(p))
                p = parent / p
            p = p.resolve()
            if str(p) not in by_path:
                raise CompanionError(
                    "UNSTAGED_SOURCE", "Capture new dependencies first", path=str(p)
                )
            if str(p) not in visited:
                dest = folder / (sha(str(p).encode())[:12] + "_" + p.name)
                visited[str(p)] = dest
                content = base64.b64decode(by_path[str(p)]["after"]).decode("utf-8")
                expanded = expand(content, p.parent)
                if dest.exists():
                    if dest.read_text(encoding="utf-8") != expanded:
                        raise CompanionError(
                            "ARTIFACT_CHANGED",
                            "Content-addressed source was modified",
                            path=str(dest),
                        )
                else:
                    dest.write_text(expanded, encoding="utf-8")
            return '#include "' + visited[str(p)].as_posix() + '"'

        return INCLUDE.sub(replace, source)

    return expand(text)


def stage(ctx, job, capture_id, files, benchmark_samples=0):
    cap = get(ctx, capture_id, "capture")
    node = check(ctx, cap)
    originals = {f["path"]: f for f in cap["files"]}
    if len(files) != len({str(Path(f["path"]).resolve()) for f in files}):
        raise CompanionError("DUPLICATE_SOURCE", "Each source can be changed once")
    updated = dict(originals)
    for change in files:
        p = str(Path(change["path"]).resolve())
        if p not in originals:
            raise CompanionError("UNSTAGED_SOURCE", "Can only change captured includes", path=p)
        content = change["content"].encode("utf-8")
        updated[p] = {
            **originals[p],
            "after": base64.b64encode(content).decode(),
            "after_sha256": sha(content),
        }
    check_files(list(originals.values()), "before")
    folder = directory(ctx, job)
    signature = digest([(f["path"], f["after_sha256"]) for f in updated.values()])
    live_snippet = cap["authoring_snippet"] + "\n// companion source revision " + signature + "\n"
    # Applied nodes depend on these revisions beyond artifact/session retention.
    source_cache = ctx.ledger.root.parent.parent / "sources" / signature
    source_cache.mkdir(exist_ok=True, parents=True)
    snippet = stage_sources(ctx.hou, live_snippet, list(updated.values()), source_cache)
    created = []
    flags = [(n, n.isDisplayFlagSet(), n.isRenderFlagSet()) for n in node.parent().children()]
    original_inputs = [
        (c.inputIndex(), c.inputNode(), c.outputIndex()) for c in node.inputConnections()
    ]
    preview_journal = {
        "state": "prepared",
        "path": node.path(),
        "before_snippet": cap["snippet"],
        "inputs": [(i, n.path(), output) for i, n, output in original_inputs],
        "flags": [(n.path(), display, render) for n, display, render in flags],
        "guarantee": "temporary live-node preview restored on handled exits; not process-crash atomic",
    }
    atomic_json(folder / "stage-transaction.json", preview_journal)

    def restore_flags():
        for sibling, display, render in flags:
            if display:
                sibling.setDisplayFlag(True)
            if render:
                sibling.setRenderFlag(True)

    try:
        with ctx.hou.undos.disabler():
            # Houdini's compiled cache is node-context-sensitive. Preview on the
            # target, with frozen inputs, then restore before returning evidence.
            clone = node
            for item in cap["inputs"]:
                p = Path(item["path"])
                if not p.is_file() or sha(p.read_bytes()) != item["sha256"]:
                    raise CompanionError("ARTIFACT_CHANGED", "Frozen input changed")
                src = node.parent().createNode("file", "__companion_input")
                created.append(src)
                src.parm("file").set(str(p))
                clone.setInput(item["index"], src)
            clone.parm("snippet").set(snippet)
            feedback = evidence(
                ctx,
                job,
                clone,
                folder,
                cap["focus"],
                cap["views"],
                cap["resolution"],
                cap["cameras"],
            )
            feedback["timings"]["compile_and_cook_ms"] = feedback["timings"]["geometry_access_ms"]
            feedback["timings"]["classification"] = (
                "new candidate: combined compile and cook; compiler-only timing unavailable"
            )
            if benchmark_samples:
                if not cap["inputs"] or cap["inputs"][0]["index"] != 0:
                    raise CompanionError(
                        "BENCHMARK_INPUT_REQUIRED",
                        "Input zero is required for invalidation benchmark",
                    )
                ctx.ledger.phase(job["job_id"], "invalidated_regeneration_benchmark")
                epoch = node.parent().createNode("python", "__companion_epoch")
                created.append(epoch)
                epoch.setInput(0, clone.input(0))
                clone.setInput(0, epoch)
                samples = []
                for index in range(benchmark_samples + 1):
                    ctx.ledger.checkpoint(job["job_id"])
                    epoch.parm("python").set(
                        "g=hou.pwd().geometry()\ng.merge(hou.pwd().input(0).geometry())\ng.addAttrib(hou.attribType.Global,'companion_iteration_epoch',"
                        + str(index)
                        + ")"
                    )
                    before_count = clone.cookCount()
                    start = time.perf_counter()
                    regenerated = clone.geometry()
                    elapsed = (time.perf_counter() - start) * 1000
                    if (
                        regenerated.attribValue("companion_iteration_epoch") != index
                        or clone.cookCount() <= before_count
                    ):
                        raise CompanionError(
                            "BENCHMARK_CACHED", "Regeneration was not demonstrated"
                        )
                    if index:
                        samples.append(elapsed)
                feedback["benchmark"] = {
                    "samples_ms": samples,
                    "scope": "changed frozen input detail attribute; includes input regeneration and cached VEX execution",
                    "compile_included": False,
                }
    finally:
        with ctx.hou.undos.disabler():
            node.parm("snippet").set(cap["snippet"])
            for index in range(len(node.inputs())):
                node.setInput(index, None)
            for index, upstream, output in original_inputs:
                node.setInput(index, upstream, output)
            for temporary in reversed(created):
                temporary.destroy()
            restore_flags()
            node.geometry()
            # SOP subnet references are cook-derived. Refresh the restored output
            # before comparing dependencies, rather than accepting stale metadata.
            if isinstance(node.parent(), ctx.hou.SopNode):
                node.parent().geometry()
            preview_journal["state"] = "restored"
            atomic_json(folder / "stage-transaction.json", preview_journal)
    check(ctx, cap)
    acceptable = valid(feedback["geometry"]) and all(
        not i["suspect_blank_or_dark"] for i in feedback["images"]
    )
    atomic_json(folder / "feedback.json", feedback)
    value = {
        "kind": "stage",
        "capture_id": capture_id,
        "files": list(updated.values()),
        "snippet": snippet,
        "authoring_snippet": live_snippet,
        "source_manifest": json.dumps(
            {
                "authoring_snippet": live_snippet,
                "revision": signature,
                "files": [
                    {"path": f["path"], "sha256": f["after_sha256"]} for f in updated.values()
                ],
            },
            sort_keys=True,
        ),
        "feedback": feedback,
        "acceptable": acceptable,
        "source_cache": source_cache.name,
    }
    retain(ctx, job, value)
    return {
        "stage_id": job["job_id"],
        "accepted_basic_checks": acceptable,
        "before": cap["feedback"],
        "after": feedback,
        "primitive_delta": feedback["geometry"]["primitives"]
        - cap["feedback"]["geometry"]["primitives"],
        "scope": "artistic quality still requires visual review",
    }


def apply(ctx, job, stage_id):
    staged = get(ctx, stage_id, "stage")
    cap = get(ctx, staged["capture_id"], "capture")
    node = check(ctx, cap)
    if not staged["acceptable"]:
        raise CompanionError("REVIEW_FAILED", "Stage did not pass complete basic checks")
    folder = directory(ctx, job)

    def mutate():
        node.parm("snippet").set(staged["snippet"])
        node.setUserData("houdini_companion_sources", staged["source_manifest"])
        feedback = evidence(
            ctx, job, node, folder, cap["focus"], cap["views"], cap["resolution"], cap["cameras"]
        )
        if not valid(feedback["geometry"]):
            raise CompanionError("REVIEW_FAILED", "Applied geometry failed audit")
        if (
            feedback["geometry"]["semantic_sha256"]
            != staged["feedback"]["geometry"]["semantic_sha256"]
        ):
            raise CompanionError("STAGE_MISMATCH", "Applied geometry differs from reviewed stage")
        if isinstance(node.parent(), ctx.hou.SopNode):
            node.parent().geometry()
        for p, expected in cap["guards"].items():
            check_expected(ctx.hou, require_node(ctx.hou, p), expected)
        return feedback

    def revert():
        node.parm("snippet").set(cap["snippet"])
        set_manifest(node, cap.get("source_manifest_before"))

    with ctx.hou.undos.group("Companion iteration " + job["job_id"][:8]):
        feedback = transact(
            staged["files"],
            folder / "transaction.json",
            mutate,
            revert,
            {
                "path": cap["path"],
                "before_snippet": cap["snippet"],
                "after_snippet": staged["snippet"],
                "before_manifest": cap["source_manifest_before"],
                "after_manifest": staged["source_manifest"],
            },
        )
    value = {
        "kind": "apply",
        "stage_id": stage_id,
        "capture_id": staged["capture_id"],
        "observation": fingerprint(ctx.hou, node),
        "feedback": feedback,
    }
    retain(ctx, job, value)
    return {
        "apply_id": job["job_id"],
        "feedback": feedback,
        "observation": value["observation"],
        "restore_operation": "iteration.restore",
        "journal": "transaction.json",
        "hip_saved": False,
        "source_revision": json.loads(staged["source_manifest"]),
    }


def restore(ctx, job, apply_id):
    applied = get(ctx, apply_id, "apply")
    staged = get(ctx, applied["stage_id"], "stage")
    cap = get(ctx, applied["capture_id"], "capture")
    node = require_node(ctx.hou, cap["path"])
    check_expected(ctx.hou, node, applied["observation"]["token"])
    files = [
        {
            **f,
            "before": f["after"],
            "after": f["before"],
            "before_sha256": f["after_sha256"],
            "after_sha256": f["before_sha256"],
        }
        for f in staged["files"]
    ]
    folder = directory(ctx, job)

    def mutate():
        node.parm("snippet").set(cap["snippet"])
        set_manifest(node, cap.get("source_manifest_before"))
        feedback = evidence(
            ctx, job, node, folder, cap["focus"], cap["views"], cap["resolution"], cap["cameras"]
        )
        if not valid(feedback["geometry"]):
            raise CompanionError("RESTORE_FAILED", "Restored geometry failed audit")
        return feedback

    def revert():
        node.parm("snippet").set(staged["snippet"])
        set_manifest(node, staged.get("source_manifest"))

    feedback = transact(
        files,
        folder / "transaction.json",
        mutate,
        revert,
        {
            "path": cap["path"],
            "before_snippet": staged["snippet"],
            "after_snippet": cap["snippet"],
            "before_manifest": staged.get("source_manifest"),
            "after_manifest": cap.get("source_manifest_before"),
        },
    )
    return {"restored": apply_id, "feedback": feedback, "hip_saved": False}


def release(ctx, job):
    count = len(state(ctx))
    state(ctx).clear()
    return {
        "released_receipts": count,
        "scope": "session handles only; journals remain subject to artifact retention",
    }


def plugin():
    source = object_schema(
        {"path": PATH, "content": {"type": "string", "maxLength": 1048576}}, ["path", "content"]
    )
    array = {"type": "array", "maxItems": 16, "items": PATH}
    specs = [
        (
            "capture",
            "artifacts",
            capture,
            {
                "path": PATH,
                "guards": array,
                "cameras": {**array, "maxItems": 6},
                "views": {**array, "maxItems": 6},
                "resolution": {"type": "integer", "minimum": 128, "maximum": 1600},
            },
            ["path"],
        ),
        (
            "stage",
            "preview",
            stage,
            {
                "capture_id": PATH,
                "files": {"type": "array", "minItems": 1, "maxItems": 16, "items": source},
                "benchmark_samples": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            ["capture_id", "files"],
        ),
        ("apply", "scene", apply, {"stage_id": PATH}, ["stage_id"]),
        ("restore", "scene", restore, {"apply_id": PATH}, ["apply_id"]),
        ("release", "preview", release, {}, []),
    ]
    return PluginSpec(
        "iteration",
        "0.3.0",
        tuple(
            OperationSpec(
                "iteration." + name, effect, object_schema(params, required), fn, fn.__doc__ or name
            )
            for name, effect, fn, params, required in specs
        ),
        requires=("review",),
    )
