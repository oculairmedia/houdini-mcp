"""Launch only a fresh, isolated Houdini GUI to test PR #38 regression contracts."""

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hfs", type=Path, required=True)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    directory = (
        args.directory
        or Path.home() / ".houdini-companion" / ("pr38-review-regressions-" + str(time.time_ns()))
    ).resolve()
    if directory.exists():
        raise RuntimeError("Acceptance requires a new directory")
    match = re.search(r"(\d+\.\d+)\.\d+", args.hfs.name)
    if not match:
        raise RuntimeError("HFS directory must identify the Houdini build")
    version = match[1]
    preferences = directory / ("prefs" + version)
    scripts = preferences / "scripts"
    scripts.mkdir(parents=True)
    repo = Path(__file__).resolve().parent.parent
    startup = f"""import hou,sys,json,traceback
from pathlib import Path
sys.path.insert(0,{str(repo)!r})
directory=Path({str(directory)!r})
directory.joinpath('startup.json').write_text(json.dumps({{'ui':hou.isUIAvailable()}}))
def _acceptance():
    hou.ui.removeEventLoopCallback(_acceptance)
    directory.joinpath('started.json').write_text('{{}}')
    try:
        from scripts.verify_companion_review_regressions import run
        run(directory)
    except Exception:
        directory.joinpath('failure.txt').write_text(traceback.format_exc())
    finally:
        hou.hscript('quit -f')
hou.ui.addEventLoopCallback(_acceptance)
"""
    (scripts / "123.py").write_text(startup, encoding="utf-8")
    env = {
        **os.environ,
        "HFS": str(args.hfs),
        "HOUDINI_USER_PREF_DIR": str(directory / "prefs__HVER__"),
        "HOUDINI_PATH": str(preferences) + os.pathsep + "&",
        "HOUDINI_COMPANION_AUTOSTART": "0",
        "HOUDINI_COMPANION_HOME": str(directory / "companion"),
        "HOUDINI_NO_ENV_FILE": "1",
    }
    options = {}
    if os.name == "nt":
        info = subprocess.STARTUPINFO()
        info.dwFlags = subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        options = {"startupinfo": info, "creationflags": subprocess.CREATE_NO_WINDOW}
    executable = args.hfs / "bin" / ("houdini.exe" if os.name == "nt" else "houdini")
    with (directory / "gui.log").open("wb") as log:
        process = subprocess.Popen(
            [str(executable), "-foreground"],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            **options,
        )
        (directory / "launch.json").write_text(
            json.dumps(
                {"pid": process.pid, "directory": str(directory), "disposable": True}, indent=2
            )
        )
        print(json.dumps({"pid": process.pid, "directory": str(directory)}), flush=True)
        try:
            process.wait(timeout=args.timeout)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    failure = directory / "failure.txt"
    if failure.exists():
        raise RuntimeError(failure.read_text())
    report = json.loads((directory / "report.json").read_text())
    if not report.get("passed") or process.returncode != 0:
        raise RuntimeError("Disposable acceptance failed")
    print(
        json.dumps(
            {"passed": True, "report": str(directory / "report.json"), "checks": report["checks"]}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
