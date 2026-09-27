"""Bounded CLI discovery and job receipts without changing operation contracts."""

import fnmatch
import json

from .errors import CompanionError


def scoped_catalog(catalog, pattern=None, effects=None, compact=False):
    requested = set(effects.split(",")) if effects else None
    if requested and not requested <= {"read", "scene", "preview", "artifacts", "code"}:
        raise CompanionError("INVALID_EFFECT", "Unknown effect filter")
    names = [
        n
        for n, effect in catalog["operations"].items()
        if (not pattern or fnmatch.fnmatchcase(n, pattern))
        and (not requested or effect in requested)
    ]
    if pattern and not names:
        raise CompanionError("NO_COMMAND_MATCH", pattern)
    result = {
        "plugin_api": catalog["plugin_api"],
        "operations": {n: catalog["operations"][n] for n in names},
        "contracts": {n: catalog["contracts"][n] for n in names},
    }
    if compact:
        result["parameters"] = {
            n: {
                "required": catalog["parameters"][n].get("required", []),
                "fields": list(catalog["parameters"][n].get("properties", {})),
            }
            for n in names
        }
    else:
        result["parameters"] = {n: catalog["parameters"][n] for n in names}
    return result


def compact_job(job):
    if not isinstance(job, dict) or "job_id" not in job:
        return job
    result = {
        k: job[k]
        for k in ("job_id", "operation", "state", "phase", "queue_ms", "execution_ms", "error")
        if k in job
    }
    if job.get("state") in {"queued", "running"}:
        result["next_command"] = f"houdini-agent job wait {job['job_id']} --timeout 30 --compact"
        result["resubmit"] = False
    body = job.get("result", {})
    keep = {
        "accepted",
        "accepted_basic_checks",
        "reasons",
        "path",
        "time",
        "time_dependent",
        "animation_id",
        "sample_id",
        "capture_id",
        "stage_id",
        "apply_id",
        "restored",
        "manifest",
        "artifact_directory",
        "contact_sheet",
        "motion_detected",
        "topology_stable",
        "frame_count",
        "cook_ms",
        "initial_geometry_access_ms",
        "total_ms",
        "restore_operation",
        "hip_saved",
        "verification",
        "source_paths",
    }
    if body:
        result["result"] = {k: v for k, v in body.items() if k in keep}
        if not result["result"] and len(json.dumps(body)) <= 4096:
            result["result"] = dict(body)
        result["result_fields"] = list(body)
        if "changed" in body:
            result["result"]["changed_count"] = len(body["changed"])
            result["result"]["changed"] = body["changed"][:8]
            result["result"]["aliases"] = body.get("aliases", {})
            result["result"]["undo_job_id"] = body.get("undo_job_id")
        if "observation" in body:
            result["result"]["observation"] = {
                k: v
                for k, v in body["observation"].items()
                if k in {"token", "path", "frame", "fps"}
            }
    return result
