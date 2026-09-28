"""Build five owned live variants, verify them, and publish a comparison gallery."""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from demo import execute, run  # noqa: E402
from generate import VARIANTS  # noqa: E402

from houdini_companion.client import Client  # noqa: E402

HERE = Path(__file__).resolve().parent
DIRECTORY = Path.home() / ".houdini-companion" / "relativity-variants"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    client = Client()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    state_file = DIRECTORY / "build.json"
    if state_file.exists() and not args.resume:
        raise RuntimeError("Existing variant receipts found; inspect rather than overwrite")
    if args.resume:
        state = json.loads(state_file.read_text())
        before = state["before"]
        for record in state["variants"]:
            if "promoted" not in record:
                raise RuntimeError("Partial candidate requires explicit recovery before resume")
            execute(
                client,
                f"""
n=hou.node({record["promoted"]["promoted"]!r})
assert n and n.userData('companion_demo')=='relativity-variants-v1'
assert n.node('generator').parm('snippet').eval()=={(HERE / (record["slug"] + ".vfl")).read_text(encoding="utf-8")!r}
result={{'retained':n.path()}}
""",
            )
    else:
        before = execute(
            client,
            """
import hashlib
from houdini_companion.state_guard import time_state
cams=[n for n in hou.node('/obj').allSubChildren() if n.type().name()=='cam']
result={'time':time_state(hou),'hip':hou.hipFile.path(),'camera_paths':[n.path() for n in cams],
'camera_digest':hashlib.sha256(''.join(n.asCode() for n in cams).encode()).hexdigest()}
""",
        )
        state = {"before": before, "variants": []}
        state_file.write_text(json.dumps(state, indent=2))
    for index, config in enumerate(VARIANTS):
        slug = config["slug"]
        if any(record["slug"] == slug for record in state["variants"]):
            continue
        built = run(
            client,
            "build.stage",
            name="relativity_" + slug,
            profile="surface",
            nodes=[
                {
                    "id": "generator",
                    "type": "attribwrangle",
                    "parms": {
                        "class": 0,
                        "snippet": (HERE / (slug + ".vfl")).read_text(encoding="utf-8"),
                    },
                },
                {"id": "normals", "type": "normal", "inputs": ["generator"]},
                {"id": "OUT_VARIANT", "type": "null", "inputs": ["normals"]},
            ],
            output="OUT_VARIANT",
        )
        record = {**config, "candidate": built}
        state["variants"].append(record)
        state_file.write_text(json.dumps(state, indent=2))
        cam = execute(
            client,
            f"""
rig=hou.node('/obj/relativity_variant_views')
if rig is None:
    rig=hou.node('/obj').createNode('subnet','relativity_variant_views')
    rig.setUserData('companion_demo','relativity-variants-v1')
assert rig.userData('companion_demo')=='relativity-variants-v1'
assert rig.node({slug!r}) is None
cam=rig.createNode('cam',{slug!r})
cam.parmTuple('t').set((35,35,35));cam.parmTuple('r').set((-35.26438968,45,0))
cam.parm('projection').set('ortho');cam.parm('orthowidth').set({config["width"]})
cam.parm('resx').set(960);cam.parm('resy').set(960)
cam.parm('near').set(.1);cam.parm('far').set(250)
result=cam.path()
""",
        )
        record["camera"] = cam
        record["checks"] = []
        for frame in (1, 121):
            check = run(
                client, "geometry.validate", path=built["output"], profile="surface", frame=frame
            )
            assert check["accepted"], check
            record["checks"].append({"frame": frame, **check})
        loop = run(
            client, "timeline.boundary", path=built["output"], before=1, after=241, tolerance=0.001
        )
        assert loop["accepted"], loop
        record["loop"] = loop
        seq = run(
            client,
            "render.start",
            path=built["output"],
            frames=[1, 61, 121, 181, 241],
            cameras=[cam],
            resolution=900,
        )
        record["render"] = seq
        state_file.write_text(json.dumps(state, indent=2))
        for _ in range(5):
            run(client, "render.step", render_id=seq["render_id"])
        pub = run(
            client,
            "review.publish",
            render_id=seq["render_id"],
            destination=str(DIRECTORY / slug),
            title=config["title"],
        )
        record["publication"] = pub
        run(client, "render.release", render_id=seq["render_id"])
        shutil.copy2(HERE / (slug + ".vfl"), DIRECTORY / slug / (slug + ".vfl"))
        # Expose only the reviewed candidate. Translate the new object and its new camera together.
        promoted = run(client, "build.promote", build_id=built["build_id"])
        record["promoted"] = promoted
        record["offset"] = 3000 + index * 100
        execute(
            client,
            f"""
n=hou.node({promoted["promoted"]!r});n.parmTuple('t').set(({record["offset"]},0,0))
n.setUserData('companion_demo','relativity-variants-v1')
n.setComment({(config["title"] + " | " + config["description"] + " | 240-frame loop.")!r})
n.setColor(hou.Color((.25,.55,.5)))
camera=hou.node({cam!r});camera.parm('tx').set({record["offset"] + 35})
result={{'root':n.path()}}
""",
        )
        state_file.write_text(json.dumps(state, indent=2))
        print(json.dumps({"variant": slug, "complete": True}), flush=True)
    after = execute(
        client,
        f"""
import hashlib
from houdini_companion.state_guard import time_state
result={{'time':time_state(hou),'hip':hou.hipFile.path(),
'camera_digest':hashlib.sha256(''.join(hou.node(p).asCode() for p in {before["camera_paths"]!r}).encode()).hexdigest()}}
""",
    )
    assert all(before[key] == after[key] for key in ("time", "hip", "camera_digest")), after
    state["after"] = after
    state["artist_state_preserved"] = True
    state_file.write_text(json.dumps(state, indent=2))
    print(json.dumps({"complete": True, "receipt": str(state_file)}), flush=True)


if __name__ == "__main__":
    main()
