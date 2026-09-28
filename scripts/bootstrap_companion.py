"""Start the companion in an existing hrpyc session without saving or restarting HIP."""

import argparse
from pathlib import Path

import rpyc

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=18811)
parser.add_argument("--reload", action="store_true")
args = parser.parse_args()
root = str(Path(__file__).resolve().parent.parent)
connection = rpyc.classic.connect("127.0.0.1", args.port)
connection._config["sync_request_timeout"] = 30
try:
    connection.execute(
        "import sys, json, hdefereval\n"
        + f"sys.path.insert(0, {root!r}) if {root!r} not in sys.path else None\n"
        + "from houdini_companion import runtime\n"
        + (
            "hdefereval.executeInMainThreadWithResult(runtime.stop)\nimport importlib\n"
            "from houdini_companion import schema\nimportlib.reload(schema)\nimportlib.reload(runtime)\n"
            if args.reload
            else ""
        )
        + "RESULT=json.dumps(hdefereval.executeInMainThreadWithResult(runtime."
        + ("reload_runtime" if args.reload else "start")
        + "))"
    )
    print(connection.namespace["RESULT"])
finally:
    connection.close()
