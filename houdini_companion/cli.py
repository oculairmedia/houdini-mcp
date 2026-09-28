"""CLI for the persistent companion. JSON on stdout, including failures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent_output import compact_job, scoped_catalog
from .client import Client
from .core import OPERATIONS, CompanionError, atomic_json
from .registry import load_registry
from .temporal import frame_list


class AgentParser(argparse.ArgumentParser):
    def error(self, message):
        raise CompanionError("ARGUMENT", message)


def recipe(path, inline=None):
    return json.loads(
        (
            sys.stdin.read()
            if path == "-"
            else Path(path).read_text(encoding="utf-8-sig")
            if path
            else inline
        ).lstrip("\ufeff")
    )


def install(prefs, repository=None):
    root = Path(repository or Path(__file__).resolve().parent.parent).resolve()
    prefs = Path(prefs).resolve()
    if not (root / "houdini_plugin").is_dir():
        raise CompanionError(
            "INSTALL_SOURCE", "Install from a repository checkout containing houdini_plugin"
        )
    package = prefs / "packages" / "houdini_companion.json"
    contents = {
        "env": [{"PYTHONPATH": {"value": [root.as_posix()], "method": "prepend"}}],
        "hpath": (root / "houdini_plugin").as_posix(),
    }
    if package.exists() and json.loads(package.read_text()) != contents:
        raise CompanionError(
            "INSTALL_CONFLICT",
            "Existing companion package points elsewhere; inspect it before replacing",
        )
    atomic_json(package, contents)
    return {
        "package": str(package),
        "startup": "next Houdini launch",
        "source": str(root),
        "current_session": "Use scripts/bootstrap_companion.py to attach without a restart",
    }


def _main(argv=None):
    parser = AgentParser(prog="houdini-agent", description=__doc__)
    parser.add_argument(
        "--pid", type=int, help="Choose a Houdini process when multiple sessions exist"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    p = commands.add_parser("schema")
    p.add_argument("--live", action="store_true", help="Include enabled external plugins")
    p.add_argument(
        "--command", dest="operation_filter", help="Filter operation names, e.g. timeline.*"
    )
    p.add_argument("--effects", help="Comma-separated effects, e.g. read,artifacts")
    p = commands.add_parser("install")
    p.add_argument("--prefs", required=True)
    p = commands.add_parser("inspect")
    p.add_argument("--path")
    p.add_argument("--selected", action="store_true")
    p.add_argument("--geometry", action="store_true")
    p.add_argument("--wait", type=float, default=30)
    p = commands.add_parser("snapshot")
    p.add_argument("--path", required=True)
    p.add_argument("--views", default="front,right,persp")
    p.add_argument("--resolution", type=int, default=640)
    p.add_argument("--wait", type=float, default=30)
    p = commands.add_parser("submit")
    p.add_argument("operation", help="Operation from the live schema, including plugin commands")
    data = p.add_mutually_exclusive_group(required=True)
    data.add_argument("--json")
    data.add_argument("--file")
    p.add_argument("--request-id")
    p.add_argument("--wait", type=float, default=0)
    p = commands.add_parser("run")
    p.add_argument("script")
    p.add_argument("--output", help="SOP path to inspect and render after execution")
    p.add_argument("--wait", type=float, default=30)
    p.add_argument("--request-id")
    p = commands.add_parser("job")
    p.add_argument("action", choices=["list", "status", "wait", "cancel"])
    p.add_argument("job_id", nargs="?")
    p.add_argument("--timeout", type=float, default=30)
    p = commands.add_parser("events")
    p.add_argument("--cursor", type=int, default=0)
    p = commands.add_parser("artifact")
    p.add_argument("job_id")
    p.add_argument("name")
    p.add_argument("--out", required=True)
    p = commands.add_parser("time")
    p.add_argument("action", choices=["inspect", "sample"])
    p.add_argument("--path")
    p.add_argument(
        "--frames", help="Comma list or inclusive start:end:step; fractional frames allowed"
    )
    p.add_argument("--views", default="persp")
    p.add_argument("--resolution", type=int, default=480)
    p.add_argument("--require-motion", action="store_true")
    p.add_argument("--max-cook-ms", type=float)
    p.add_argument("--max-speed", type=float)
    p.add_argument("--wait", type=float, default=0)
    p = commands.add_parser("animate")
    data = p.add_mutually_exclusive_group(required=True)
    data.add_argument("--file", help="Keyframe recipe JSON; use - for stdin")
    data.add_argument("--json")
    p.add_argument("--request-id")
    p.add_argument("--wait", type=float, default=0)
    commands.add_parser("stop")
    for command in commands.choices.values():
        command.add_argument(
            "--compact", action="store_true", help="Return a bounded agent receipt"
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            result = install(args.prefs)
        elif args.command == "schema":
            result = {
                "version": 1,
                "operations": OPERATIONS,
                **load_registry().catalog(),
                "commands": [
                    "doctor",
                    "inspect",
                    "snapshot",
                    "submit",
                    "run",
                    "job",
                    "events",
                    "artifact",
                    "install",
                    "stop",
                ],
                "batch_example": {
                    "actions": [{"op": "set", "path": "/obj/geo1/box1", "values": {"sizex": 2}}],
                    "expected": {"/obj/geo1/box1": "token from inspect"},
                    "output": "/obj/geo1/box1",
                },
                "preview_example": {
                    "path": "/obj/geo1/box1",
                    "expected": "token from inspect",
                    "values": {"sizex": 2},
                },
                "job_states": [
                    "queued",
                    "running",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "interrupted",
                ],
                "wait_timeout": "Returns the running job; does not cancel or retry it",
                "execute_policy": "Trusted Python in the live Houdini process",
            }
            if args.live:
                result = {"version": 1, **Client(pid=args.pid).call("schema")}
            if args.operation_filter or args.effects or args.compact:
                result = {
                    "version": 1,
                    **scoped_catalog(result, args.operation_filter, args.effects, args.compact),
                }
        else:
            client = Client(pid=args.pid)
            if args.command == "doctor":
                result = client.call("health")
            elif args.command == "inspect":
                result = client.run(
                    "inspect", {"path": args.path, "geometry": args.geometry}, args.wait
                )
            elif args.command == "snapshot":
                result = client.run(
                    "snapshot",
                    {
                        "path": args.path,
                        "views": args.views.split(","),
                        "resolution": args.resolution,
                    },
                    args.wait,
                )
            elif args.command == "submit":
                params = recipe(args.file, args.json)
                result = client.run(args.operation, params, args.wait, args.request_id)
            elif args.command == "animate":
                result = client.run(
                    "animation.keyframes", recipe(args.file, args.json), args.wait, args.request_id
                )
            elif args.command == "time":
                params = {"path": args.path} if args.path else {}
                if args.action == "sample":
                    if not args.path or not args.frames:
                        raise CompanionError("ARGUMENT", "time sample requires --path and --frames")
                    params.update(
                        frames=frame_list(args.frames),
                        views=args.views.split(","),
                        resolution=args.resolution,
                        require_motion=args.require_motion,
                    )
                    if args.max_cook_ms is not None:
                        params["max_cook_ms"] = args.max_cook_ms
                    if args.max_speed is not None:
                        params["max_speed"] = args.max_speed
                result = client.run("timeline." + args.action, params, args.wait)
            elif args.command == "run":
                result = client.run(
                    "execute",
                    {"code": Path(args.script).read_text(encoding="utf-8"), "output": args.output},
                    args.wait,
                    args.request_id,
                )
            elif args.command == "job":
                if args.action != "list" and not args.job_id:
                    raise CompanionError("ARGUMENT", "job_id is required")
                if args.action == "wait":
                    result = client.wait(args.job_id, args.timeout)
                else:
                    result = client.call(
                        {"list": "jobs", "status": "job", "cancel": "cancel"}[args.action],
                        job_id=args.job_id,
                    )
            elif args.command == "events":
                result = client.call("events", cursor=args.cursor)
            elif args.command == "artifact":
                target = Path(args.out)
                if target.exists():
                    raise CompanionError("OUTPUT_EXISTS", "Choose a new artifact output path")
                target.write_bytes(client.artifact(args.job_id, args.name))
                result = {"path": str(target.resolve())}
            else:
                result = client.call("stop")
        failed = isinstance(result, dict) and result.get("state") in {
            "failed",
            "cancelled",
            "interrupted",
        }
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            body = result["result"]
            failed = (
                failed
                or body.get("accepted") is False
                or body.get("accepted_basic_checks") is False
            )
        if args.compact and args.command != "schema":
            result = compact_job(result)
        print(json.dumps({"ok": not failed, "result": result}, allow_nan=False))
        return 1 if failed else 0
    except (CompanionError, OSError, ValueError) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, CompanionError)
            else {"code": type(exc).__name__, "message": str(exc)}
        )
        print(json.dumps({"ok": False, "error": error}))
        return 1


def main(argv=None):
    try:
        return _main(argv)
    except CompanionError as exc:
        print(json.dumps({"ok": False, "error": exc.as_dict()}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
