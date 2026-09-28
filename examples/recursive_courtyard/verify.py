"""Live checks for geometry, sampled walking clearance and preserved artist state."""

import json

from demo import OUTPUT, ROOT, execute


def main():
    result = execute(f"""
import json, hashlib, time
from pathlib import Path
import numpy as np
from houdini_companion.diagnostics import audit
root=hou.node({ROOT!r})
assert root and root.userData('recursive_demo_owner')=='recursive-courtyard-v1'
directory=Path({str(OUTPUT)!r})
out=root.node('architecture/OUT_RECURSIVE_CITY')
before=json.loads((directory/'artist-state-before.json').read_text())
original=hou.frame()
samples=[]; collisions=[]; hashes={{}}
for frame in sorted(set(list(range(1,241,4))+[240,15.399,15.401,87.399,87.401,159.399,159.401,231.399,231.401])):
    started=time.perf_counter(); g=out.geometryAtFrame(frame)
    positions=np.frombuffer(g.pointFloatAttribValuesAsString('P'),dtype=np.float32).reshape(-1,3)
    assert np.isfinite(positions).all(), frame
    assert not out.errors(), out.errors()
    assert g.attribValue('resident_generations')==13
    # Probe a walking body, at several heights and eight horizontal directions.
    # This is sampled corridor clearance, not a general collision proof.
    for height in (.3,1.1,1.65,2.05):
        for angle in range(0,360,45):
            theta=np.deg2rad(angle)
            origin=hou.Vector3(0,height,0); direction=hou.Vector3(float(np.sin(theta)),0,float(np.cos(theta)))
            hit=g.intersect(origin,direction,hou.Vector3(),hou.Vector3(),hou.Vector3(),min_hit=0.001,max_hit=.30,tolerance=.001)
            if hit>=0: collisions.append({{'frame':frame,'height':height,'angle':angle,'primitive':hit}})
    origin=hou.Vector3(0,1.65,0); p,n,uv=hou.Vector3(),hou.Vector3(),hou.Vector3()
    ground=g.intersect(origin,hou.Vector3(0,-1,0),p,n,uv,max_hit=2,tolerance=.001)
    assert ground>=0 and -.1<p[1]<.1, (frame,list(p))
    hashes[str(frame)]=hashlib.sha256(positions.tobytes()).hexdigest()
    samples.append({{'frame':frame,'points':len(positions),'primitives':len(g.prims()),'cook_and_clearance_ms':round((time.perf_counter()-started)*1000,2)}})
assert not collisions, collisions[:10]
repeat=out.geometryAtFrame(1)
assert hashlib.sha256(repeat.pointFloatAttribValuesAsString('P')).hexdigest()==hashes['1']
assert len(set(hashes.values()))>50, 'No meaningful geometry motion'
frozen=directory/'audit_frame_40.bgeo.sc'
out.geometryAtFrame(40).saveToFile(str(frozen))
checks=audit(hou,frozen)['checks']
assert checks['nonfinite_point_count']==0 and checks['zero_area_count']==0 and checks['normal_mismatch_count']==0, checks
# Verify outward winding of every generated convex six-face solid.
test=root.node('architecture').createNode('attribwrangle','__demo_orientation_check')
test.setInput(0,root.node('architecture/recursive_city')); test.parm('class').set(1)
test.parm('snippet').set('vector center=0; int start=(@primnum/6)*6; for(int j=start;j<start+6;j++) center+=primuv(0,"P",j,set(.5,.5,0)); center/=6; vector here=primuv(0,"P",@primnum,set(.5,.5,0)); i@bad_winding=dot(prim_normal(0,@primnum,.5,.5),here-center)<-1e-7;')
try:
    orientation=test.geometryAtFrame(40)
    bad=sum(orientation.primIntAttribValues('bad_winding'))
    assert bad==0, bad
finally: test.destroy()
# A copied wrangle tests distant virtual generations without touching the demo controls.
far=root.node('architecture').createNode('attribwrangle','__demo_far_check')
source=root.node('architecture/recursive_city')
far.setParmTemplateGroup(source.parmTemplateGroup()); far.parm('class').set(0)
far.parm('snippet').set(source.parm('snippet').eval()); far.parm('ratio').set(.58)
far_tests=[]
try:
    for journey in (10.25,100.25,1000.25):
        far.parm('journey').set(journey); g=far.geometry()
        xyz=np.frombuffer(g.pointFloatAttribValuesAsString('P'),dtype=np.float32)
        assert np.isfinite(xyz).all() and len(g.points())<250000, journey
        far_tests.append({{'journey':journey,'points':len(g.points()),'max_coordinate':float(np.max(np.abs(xyz)))}})
finally: far.destroy()
after={{'frame':hou.frame(),'fps':hou.fps(),'range':list(hou.playbar.frameRange()),'playback':list(hou.playbar.playbackRange()),'playing':hou.playbar.isPlaying(),'hip':hou.hipFile.path(),
        'cameras':{{n.path():n.asCode() for n in hou.node('/obj').children() if n.type().name()=='cam'}}}}
assert after==before, 'Artist camera/time/HIP state changed'
result={{'passed':True,'samples':samples,'sample_count':len(samples),'collision_count':len(collisions),'clearance_radius':.30,'clearance_heights':[.3,1.1,1.65,2.05],
        'geometry_checks':checks,'bad_outward_winding':bad,'deterministic_repeat':True,'distant_generations':far_tests,'artist_state_preserved':True,
        'scope':'Sampled walking clearance and full polygon audit at frame 40; not watertightness or arbitrary self-intersection certification.'}}
(directory/'verification.json').write_text(json.dumps(result,indent=2))
""")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
