"""Build a separate Escher-inspired sculpture through the live companion.

Run from an editable installation: python examples/recursive_relativity/demo.py stage
No artist HIP is saved, reloaded or replaced.
"""

import argparse
import json
import time
from pathlib import Path

from houdini_companion.client import Client

HERE = Path(__file__).resolve().parent
DIRECTORY = Path.home() / ".houdini-companion" / "recursive-relativity"
STATE = DIRECTORY / "demo.json"
ROOT = "/obj/recursive_relativity"
VIEWS = "/obj/relativity_views"


def run(client, operation, **params):
    job = client.run(operation, params, timeout=1)
    print(json.dumps({"operation": operation, "job_id": job["job_id"]}), flush=True)
    while job["state"] in {"queued", "running"}:
        job = client.wait(job["job_id"], timeout=10)
    if job["state"] != "succeeded":
        raise RuntimeError(json.dumps(job))
    return job["result"]


def execute(client, code):
    return run(client, "execute", code=code, feedback=False)["value"]


def label_review(publication):
    """Present the generic review player with this study's artistic labels."""
    index = Path(publication["index"])
    labels = """<script>
document.querySelector('#source').textContent='Six worlds inside themselves. Three directions of gravity. One impossible stair loop.';
document.querySelectorAll('#views figcaption').forEach((label,i)=>label.textContent=['The impossible loop','How the illusion is built'][i]);
const details=document.createElement('details'),summary=document.createElement('summary');
summary.textContent='Geometry and timing';details.append(summary,document.querySelector('#metrics'));document.body.append(details);
</script>"""
    index.write_text(
        index.read_text(encoding="utf-8").replace("</html>", labels + "</html>"), encoding="utf-8"
    )


def stage(client):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        raise RuntimeError("Demo receipt exists; inspect it before building another candidate")
    before = execute(
        client,
        """
import hashlib
from houdini_companion.state_guard import time_state
cams=[n for n in hou.node('/obj').allSubChildren() if n.type().name()=='cam']
result={'time':time_state(hou),'hip':hou.hipFile.path(),
        'camera_paths':[n.path() for n in cams],
        'camera_digest':hashlib.sha256(''.join(n.asCode() for n in cams).encode()).hexdigest()}
""",
    )
    built = run(
        client,
        "build.stage",
        name="recursive_relativity",
        profile="surface",
        review_frames=[1, 61, 121, 181, 241],
        nodes=[
            {
                "id": "relativity",
                "type": "attribwrangle",
                "parms": {"class": 0, "snippet": (HERE / "relativity.vfl").read_text()},
            },
            {
                "id": "recursive_drift",
                "type": "attribwrangle",
                "inputs": ["relativity"],
                "parms": {
                    "class": 2,
                    "snippet": 'int pp[]=pointprims(0,@ptnum); int g=prim(0,"generation",pp[0]); float a=radians(8*g*sin(2*M_PI*(@Frame-1)/240.0)); @P=qrotate(quaternion(a,normalize(set(1,1,1))),@P);',
                },
            },
            {"id": "normals", "type": "normal", "inputs": ["recursive_drift"]},
            {"id": "isolate", "type": "xform", "inputs": ["normals"], "parms": {"t": [2000, 0, 0]}},
            {"id": "OUT_RELATIVITY", "type": "null", "inputs": ["isolate"]},
        ],
        output="OUT_RELATIVITY",
    )
    state = {"before": before, "candidate": built, "output": built["output"]}
    STATE.write_text(json.dumps(state, indent=2))
    cameras = execute(
        client,
        f"""
import math
assert hou.node({VIEWS!r}) is None, 'Camera rig already exists'
rig=hou.node('/obj').createNode('subnet','relativity_views')
rig.setUserData('companion_demo','recursive-relativity-v1')
cams=[]
for name,eye,target,width in [
    ('impossible',(2035,35,35),(2000,0,0),17),
    ('reveal',(2035,23,49),(2000,0,-3),24)]:
    cam=rig.createNode('cam',name)
    delta=hou.Vector3(target)-hou.Vector3(eye)
    cam.parmTuple('t').set(eye)
    cam.parmTuple('r').set((math.degrees(math.atan2(delta[1],math.hypot(delta[0],delta[2]))),math.degrees(math.atan2(-delta[0],-delta[2])),0))
    cam.parm('projection').set('ortho'); cam.parm('orthowidth').set(width)
    cam.parm('resx').set(1080); cam.parm('resy').set(1080)
    cam.parm('near').set(.1); cam.parm('far').set(250)
    cams.append(cam.path())
rig.layoutChildren()
result=cams
""",
    )
    state["cameras"] = cameras
    STATE.write_text(json.dumps(state, indent=2))
    return state


def review(client, frames, resolution):
    state = json.loads(STATE.read_text())
    seq = run(
        client,
        "render.start",
        path=state["output"],
        frames=frames,
        cameras=state["cameras"],
        resolution=resolution,
    )
    state["render"] = seq
    STATE.write_text(json.dumps(state, indent=2))
    for _frame in frames:
        run(client, "render.step", render_id=seq["render_id"])
    dest = DIRECTORY / ("review-" + str(time.time_ns()))
    publication = run(
        client,
        "review.publish",
        render_id=seq["render_id"],
        destination=str(dest),
        title="Recursive Relativity",
        annotations=[
            {
                "frame": frames[0],
                "text": "Impossible view / Revealing view — six nested stair worlds",
            }
        ],
    )
    state["publication"] = publication
    STATE.write_text(json.dumps(state, indent=2))
    label_review(publication)
    run(client, "render.release", render_id=seq["render_id"])
    return publication


def promote(client):
    state = json.loads(STATE.read_text())
    publication = state.get("publication")
    if not publication or not publication.get("review_id"):
        raise RuntimeError("Run review with the declared frames before promotion")
    result = run(
        client,
        "build.promote",
        build_id=state["candidate"]["build_id"],
        review_id=publication["review_id"],
    )
    state["output"] = result["output"]
    state["promoted"] = result
    STATE.write_text(json.dumps(state, indent=2))
    execute(
        client,
        f"""
n=hou.node({ROOT!r}); n.setUserData('companion_demo','recursive-relativity-v1')
n.setColor(hou.Color((.18,.58,.57)))
n.setComment('RECURSIVE RELATIVITY | Six nested three-gravity stair loops. Camera /obj/relativity_views/impossible; reveal camera shows the trick. Moving amber figures: 240-frame loop. Original scene untouched.')
n.setGenericFlag(hou.nodeFlag.DisplayComment,True)
result={{'root':n.path()}}
""",
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["stage", "review", "promote", "show"])
    parser.add_argument("--frames", default="1,61,121,181,241")
    parser.add_argument("--resolution", type=int, default=960)
    args = parser.parse_args()
    client = Client()
    if args.command == "stage":
        result = stage(client)
    elif args.command == "review":
        result = review(client, [float(f) for f in args.frames.split(",")], args.resolution)
    elif args.command == "promote":
        result = promote(client)
    else:
        result = run(client, "scene.show", path=ROOT, camera=VIEWS + "/impossible")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
