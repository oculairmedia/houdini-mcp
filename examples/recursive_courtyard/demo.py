"""Build/render an isolated recursive courtyard through the live companion.

No HIP save and no changes to existing geometry, cameras or timeline settings.
Example: python examples/recursive_courtyard/demo.py build
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from houdini_companion.client import Client

HERE = Path(__file__).resolve().parent
OUTPUT = Path.home() / ".houdini-companion" / "recursive-courtyard"
ROOT = "/obj/recursive_courtyard_demo"

# Generated background belongs to the demo; no artist image is modified.
SKY_CODE = """
try:
    from PySide2.QtGui import QImage,QColor
except ImportError:
    from PySide6.QtGui import QImage,QColor
img=QImage(1280,720,QImage.Format_RGB32)
for y in range(720):
    t=y/719
    color=QColor(int(24+75*t),int(51+74*t),int(72+67*t))
    for x in range(1280): img.setPixelColor(x,y,color)
assert img.save(str(directory/'sky.png'))
rop.parm('bgimage').set(str(directory/'sky.png'))
"""


def execute(code):
    client = Client()
    job = client.run("execute", {"code": code, "feedback": False}, timeout=1)
    print(json.dumps({"job_id": job["job_id"], "state": job["state"]}), flush=True)
    while job["state"] in {"queued", "running"}:
        job = client.wait(job["job_id"], timeout=10)
    if job["state"] != "succeeded":
        raise RuntimeError(json.dumps(job))
    return job["result"]["value"]


def build():
    source = (HERE / "courtyard.vfl").read_text(encoding="utf-8")
    return execute(f"""
import json
from pathlib import Path
rootpath={ROOT!r}
if hou.node(rootpath):
    raise RuntimeError("Demo already exists; use refresh to update its owned wrangle")
before={{"frame":hou.frame(),"fps":hou.fps(),"range":list(hou.playbar.frameRange()),
        "playback":list(hou.playbar.playbackRange()),"playing":hou.playbar.isPlaying(),
        "hip":hou.hipFile.path(),
        "cameras":{{n.path():n.asCode() for n in hou.node('/obj').children() if n.type().name()=='cam'}}}}
directory=Path({str(OUTPUT)!r}); directory.mkdir(parents=True,exist_ok=True)
(directory/'artist-state-before.json').write_text(json.dumps(before,indent=2))
root=hou.node('/obj').createNode('subnet','recursive_courtyard_demo')
root.setUserData('recursive_demo_owner','recursive-courtyard-v1')
root.parmTuple('t').set((1000,0,0))
root.setColor(hou.Color((.1,.5,.5)))
root.setComment('INFINITE COURTYARD | Scrub frames 1-240. Camera: walkthrough. Scale ratio 0.58; 13 resident generations. Original town untouched.')
geo=root.createNode('geo','architecture')
geo.setDisplayFlag(False)
w=geo.createNode('attribwrangle','recursive_city')
w.parm('class').set(0)
ptg=w.parmTemplateGroup()
ptg.append(hou.FloatParmTemplate('journey','Journey (generations)',1,default_value=(-.2,)))
ptg.append(hou.FloatParmTemplate('ratio','Scale per threshold',1,default_value=(.58,),min=.3,max=.85))
w.setParmTemplateGroup(ptg)
w.parm('journey').setExpression('($FF-1)/72.0-0.2')
w.parm('snippet').set({source!r})
n=geo.createNode('normal','stone_normals'); n.setInput(0,w)
out=geo.createNode('null','OUT_RECURSIVE_CITY'); out.setInput(0,n)
out.setDisplayFlag(True); out.setRenderFlag(True)
cam=root.createNode('cam','walkthrough')
cam.parmTuple('t').set((0,1.65,0)); cam.parmTuple('r').set((0,180,0))
cam.parm('focal').set(24); cam.parm('near').set(.025); cam.parm('far').set(1000)
cam.parm('resx').set(1280); cam.parm('resy').set(720)
lights=[]
for i,(rotation,intensity,color) in enumerate([((-42,145,0),.95,(1,.87,.68)),((-35,-30,0),.65,(.65,.83,1)),((-75,20,0),.35,(1,1,1))]):
    light=root.createNode('hlight::2.0','demo_light_'+str(i))
    light.parm('light_type').set('distant'); light.parmTuple('r').set(rotation)
    light.parm('light_intensity').set(intensity); light.parmTuple('light_color').set(color)
    lights.append(light.path())
rop=hou.node('/out').createNode('opengl','recursive_courtyard_preview')
rop.setUserData('recursive_demo_owner','recursive-courtyard-v1')
for name,value in dict(camera=cam.path(),vobjects='',forceobjects=geo.path(),
    alights=' '.join(lights),forcelights=' '.join(lights),tres=1,res1=1280,res2=720,
    shadingmode=6,hqlighting=1,shadows=0,ambocclusion=0,backfacecull=1,usegeocolor=1,
    usetextures=0,colorcorrect=1,gamma=2.2,aamode=3).items():
    if rop.parm(name): rop.parm(name).set(value)
{SKY_CODE}
geo.layoutChildren(); root.layoutChildren()
g=out.geometry()
if w.errors(): raise RuntimeError(w.errors())
result={{'root':root.path(),'output':out.path(),'points':len(g.points()),'primitives':len(g.prims()),'errors':list(w.errors()),'directory':str(directory)}}
""")


def refresh():
    return execute(f"""
root=hou.node({ROOT!r})
assert root and root.userData('recursive_demo_owner')=='recursive-courtyard-v1'
w=root.node('architecture/recursive_city')
w.parm('snippet').set({(HERE / "courtyard.vfl").read_text(encoding="utf-8")!r})
g=root.node('architecture/OUT_RECURSIVE_CITY').geometry()
result={{'points':len(g.points()),'primitives':len(g.prims()),'errors':list(w.errors())}}
""")


def render(frames, width, backward=False):
    return execute(f"""
import json,time
from pathlib import Path
from houdini_companion.rendering import image_metrics
from houdini_companion.runtime import instance
root=hou.node({ROOT!r}); assert root.userData('recursive_demo_owner')=='recursive-courtyard-v1'
rop=hou.node('/out/recursive_courtyard_preview')
assert rop.userData('recursive_demo_owner')=='recursive-courtyard-v1'
directory=Path({str(OUTPUT)!r}); directory.mkdir(parents=True,exist_ok=True)
original=hou.frame(); results=[]
cam=root.node('walkthrough'); original_rotation=cam.parmTuple('r').eval()
cam.parmTuple('r').set((8,0,0) if {backward!r} else (0,180,0))
rop.parm('res1').set({width}); rop.parm('res2').set({int(width * 9 / 16)})
try:
    for frame in {frames!r}:
        rt=instance(); rt.ledger.phase(rt.ledger.active,'demo_frame_'+str(frame))
        path=directory/(('back_%04d.png' if {backward!r} else 'frame_%04d.png')%frame)
        started=time.perf_counter()
        rop.parm('picture').set(path.as_posix())
        rop.render(frame_range=(frame,frame))
        assert not rop.errors(), rop.errors()
        results.append({{'frame':frame,'path':str(path),'seconds':round(time.perf_counter()-started,3),**image_metrics(path)}})
finally:
    cam.parmTuple('r').set(original_rotation)
    if hou.frame()!=original: hou.setFrame(original)
(directory/'last-render.json').write_text(json.dumps(results,indent=2))
result={{'images':results,'restored_frame':hou.frame()}}
""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "refresh", "render"])
    parser.add_argument("--frames", default="1,40,73,110,145,200,240")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--backward", action="store_true")
    args = parser.parse_args()
    if args.action == "build":
        result = build()
    elif args.action == "refresh":
        result = refresh()
    else:
        if ":" in args.frames:
            start, end = map(int, args.frames.split(":"))
            frames = list(range(start, end + 1))
        else:
            frames = [int(f) for f in args.frames.split(",")]
        result = render(frames, args.width, args.backward)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
