"""MCP adapter for the persistent service; contains no Houdini scene semantics."""

from __future__ import annotations

import base64
import inspect
import json
import os
import uuid

from houdini_companion.client import Client
from houdini_companion.core import CompanionError


def client():
    pid = os.environ.get("HOUDINI_COMPANION_PID")
    return Client(pid=int(pid) if pid else None)


def register(mcp):
    @mcp.tool()
    def companion_schema() -> dict:
        """Discover operation parameter contracts before submitting tracked work."""
        return client().call("schema")

    @mcp.tool()
    def companion_status() -> dict:
        """Discover the live companion, supported operations, UI heartbeat and active job."""
        return client().call("health")

    @mcp.tool()
    def companion_inspect(path: str | None = None, geometry: bool = False) -> dict:
        """Inspect a node or current selection. Keep the observation token for guarded edits."""
        return client().run("inspect", {"path": path, "geometry": geometry})

    @mcp.tool()
    def companion_submit(
        operation: str, params: dict, request_id: str, wait_seconds: float = 0
    ) -> dict:
        """Submit one tracked operation. Reuse request_id only for identical retries.

        Discover enabled operations and plugin contracts with companion_schema.
        Built-ins include query.batch, query.graph, query.parameters,
        query.node_types, query.geometry, review.accept and review.compare.
        batch accepts actions plus an
        expected map of node paths to inspection tokens. execute is trusted Python
        in Houdini, not sandboxed. Timeouts return a running job, never cancel it.
        """
        return client().run(operation, params, min(max(wait_seconds, 0), 30), request_id)

    @mcp.tool()
    def companion_job(job_id: str, wait_seconds: float = 0) -> dict:
        """Recover a job after reconnecting; optionally wait up to 30 seconds."""
        return client().wait(job_id, min(max(wait_seconds, 0), 30))

    @mcp.tool()
    def companion_cancel(job_id: str) -> dict:
        """Cancel queued work or request a stop between phases; cannot kill a running cook."""
        return client().call("cancel", job_id=job_id)

    @mcp.tool()
    def companion_events(cursor: int = 0) -> dict:
        """Read bounded job/scene events. A gap means old events expired; refresh job state."""
        return client().call("events", cursor=cursor)

    @mcp.tool()
    def companion_feedback(job_id: str) -> list:
        """Return the completed job report and rendered PNGs as native MCP images."""
        from mcp.types import ImageContent, TextContent

        connection = client()
        job = connection.call("job", job_id=job_id)
        result = job.get("result", {})
        feedback = result.get("feedback", result)
        content = [TextContent(type="text", text=json.dumps(job))]
        before_images = feedback.get("before_feedback", {}).get("images", [])[:3]
        for entry in [*before_images, *feedback.get("images", [])[:6]]:
            data = connection.artifact(job_id, entry["name"])
            content.append(
                ImageContent(
                    type="image", data=base64.b64encode(data).decode(), mimeType="image/png"
                )
            )
        return content


class ToolAdapter:
    """Explicit companion backend for common legacy tool names.

    Unmigrated tools fail explicitly. They never fall back to RPyC behind an
    active companion job. The default legacy backend is unchanged.
    """

    def __init__(self, legacy):
        self.legacy = legacy

    def __getattr__(self, name):
        original = getattr(self.legacy, name)

        def invoke(*args, **kwargs):
            try:
                bound = inspect.signature(original).bind(*args, **kwargs)
                bound.apply_defaults()
                return self.call(name, bound.arguments)
            except CompanionError as exc:
                return {"status": "error", "message": str(exc), "error": exc.as_dict()}

        return invoke

    def call(self, name, args):
        connection = client()

        def run(operation, params, timeout=30):
            job = connection.run(operation, params, timeout)
            state = job["state"]
            if state == "failed":
                return {
                    "status": "error",
                    "job_id": job["job_id"],
                    "message": job["error"]["message"],
                    "error": job["error"],
                }
            if state != "succeeded":
                return {"status": "running", "job_id": job["job_id"], "state": state}
            return {"status": "success", "job_id": job["job_id"], **job["result"]}

        def inspect_path(path):
            job = connection.run("inspect", {"path": path}, 10)
            if job["state"] != "succeeded":
                raise CompanionError(
                    "INSPECTION_UNAVAILABLE", "Inspection did not finish", job_id=job["job_id"]
                )
            return job["result"]

        if name == "get_scene_info":
            result = run("inspect", {"path": "/obj"})
            result["houdini_version"] = connection.call("health")["capabilities"]["houdini"]
            return result
        if name in {"get_node_info", "list_children"}:
            path = args.get("node_path", args.get("parent_path", "/obj"))
            return run(
                "inspect", {"path": path, "geometry": bool(args.get("include_geometry", False))}
            )
        if name == "execute_code":
            from .tools._common import (
                _detect_dangerous_code,
                _detect_heavy_geometry_code,
                _detect_import_hou,
                _detect_mutation_code,
            )
            from .tools.code import VALID_POLICIES, _build_audit, _bypass_config_enabled

            code = args["code"]
            policy = args.get("policy", "normal")
            bypass = _bypass_config_enabled()
            dangerous = _detect_dangerous_code(code)
            heavy = _detect_heavy_geometry_code(code)
            mutation = _detect_mutation_code(code)
            blocked = None
            if policy not in VALID_POLICIES:
                blocked = "invalid_policy"
            elif policy == "privileged" and not bypass:
                blocked = "privileged_without_config"
            elif _detect_import_hou(code):
                blocked = "import_hou"
            elif policy == "read-only" and (mutation or dangerous or heavy):
                blocked = "read_only_violation"
            elif dangerous and not (bypass and args.get("allow_dangerous")):
                blocked = "dangerous_pattern"
            elif heavy and not (
                bypass and (args.get("allow_heavy_geometry") or args.get("allow_dangerous"))
            ):
                blocked = "heavy_geometry"
            elif args.get("capture_diff"):
                blocked = "capture_diff_not_migrated_use_companion_batch"
            audit = _build_audit(
                code=code,
                policy=policy,
                allow_dangerous=args.get("allow_dangerous", False),
                allow_heavy_geometry=args.get("allow_heavy_geometry", False),
                bypass_config_enabled=bypass,
                dangerous_patterns=dangerous,
                heavy_geometry_patterns=heavy,
                blocked_reason=blocked,
            )
            if blocked:
                return {"status": "error", "message": blocked, "policy": policy, "audit": audit}
            result = run(
                "execute",
                {"code": args["code"], "feedback": False},
                min(args.get("timeout", 30), 30),
            )
            result.update(policy=policy, audit=audit)
            return result
        if name in {"render_viewport", "render_quad_view"}:
            path = args.get("look_at_node")
            if not path:
                raise CompanionError(
                    "SOP_REQUIRED", "Companion rendering requires look_at_node set to a SOP output"
                )
            return run(
                "snapshot",
                {
                    "path": path,
                    "views": ["front", "right", "top", "persp"]
                    if name == "render_quad_view"
                    else ["persp"],
                },
            )
        action, expected = None, {}
        if name == "create_node":
            parent = args.get("parent_path", "/obj")
            action = {
                "op": "create",
                "parent": parent,
                "type": args["node_type"],
                "name": args.get("name") or "companion_" + uuid.uuid4().hex[:8],
                "as": "created",
            }
            if parent not in {"/obj", "/out"}:
                expected[parent] = inspect_path(parent)["observation"]["token"]
        elif name in {"set_parameter", "delete_node", "set_node_flags"}:
            path = args["node_path"]
            expected[path] = inspect_path(path)["observation"]["token"]
            if name == "set_parameter":
                action = {"op": "set", "path": path, "values": {args["param_name"]: args["value"]}}
            elif name == "delete_node":
                action = {"op": "delete", "path": path}
            else:
                if args.get("bypass") is not None:
                    raise CompanionError(
                        "UNSUPPORTED_OPTION", "Bypass flag migration is not implemented"
                    )
                action = {
                    "op": "flags",
                    "path": path,
                    **{k: args[k] for k in ("display", "render") if args.get(k) is not None},
                }
        elif name in {"connect_nodes", "disconnect_node_input"}:
            path = args.get("dst_path", args.get("node_path"))
            source = args.get("src_path")
            for target in (path, source):
                if target:
                    expected[target] = inspect_path(target)["observation"]["token"]
            action = {
                "op": "connect",
                "path": path,
                "source": source,
                "input": args.get("dst_input_index", args.get("input_index", 0)),
                "output": args.get("src_output_index", 0),
            }
        if action:
            return run("batch", {"actions": [action], "expected": expected, "feedback": False})
        raise CompanionError(
            "UNMIGRATED_TOOL",
            f"{name} is not migrated; use the companion operation API or explicitly select the legacy backend",
        )
