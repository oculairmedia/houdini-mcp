"""Compare complete audits on one frozen asset and exercise native error detection."""

import argparse
import json
from pathlib import Path

from houdini_companion.client import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geometry", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    code = r"""
import time, math, json, platform
from pathlib import Path
from houdini_companion.diagnostics import audit, valid
path = Path(GEOMETRY)
g=hou.Geometry();g.loadFromFile(str(path))
start=time.perf_counter()
zero=normals=0
for prim in g.prims():
    if prim.type().name() != 'Polygon' or not prim.isClosed():continue
    zero += prim.intrinsicValue('measuredarea') <= 1e-9
    if g.findPointAttrib('N'):
        normal=prim.normal()
        normals += any(normal.dot(hou.Vector3(v.point().attribValue('N'))) < .999 for v in prim.vertices())
nonfinite=sum(not all(math.isfinite(v) for v in p.position()) for p in g.points())
legacy_ms=(time.perf_counter()-start)*1000
runs=[audit(hou,path) for _ in range(3)]
for run in runs:
    c=run['checks']
    assert c['polygons_checked'] > 0, c
    assert (c['zero_area_count'],c['normal_mismatch_count'],c['nonfinite_point_count']) == (zero,normals,nonfinite), c

# Deliberately bad fixture: collapsed face, reversed N, and a non-finite orphan.
fixture=hou.Geometry()
fixture.addAttrib(hou.attribType.Point,'N',(0.0,0.0,1.0))
for coords in [[(0,0,0),(1,0,0),(1,1,0),(0,1,0)],[(2,0,0)]*4]:
    face=fixture.createPolygon()
    for xyz in coords:
        pt=fixture.createPoint();pt.setPosition(xyz);face.addVertex(pt)
    for vertex in face.vertices():vertex.point().setAttribValue('N',tuple(-face.normal()))
pt=fixture.createPoint();pt.setPosition((float('nan'),0,0))
bad=path.parent/'audit_fault_fixture.bgeo.sc';fixture.saveToFile(str(bad))
failures=audit(hou,bad)
assert failures['checks']['polygons_checked']==2,failures
assert failures['checks']['zero_area_count']==1,failures
assert failures['checks']['nonfinite_point_count']==1,failures
assert failures['checks']['normal_mismatch_count']>=1,failures
assert not valid(failures)
native_ms=sorted(r['diagnostics_ms'] for r in runs)[1]
result={'environment':{'host':platform.node(),'houdini':hou.applicationVersionString(),'geometry':str(path)},
        'points':runs[0]['points'],'primitives':runs[0]['primitives'],'legacy_ms':legacy_ms,
        'native_samples_ms':[r['diagnostics_ms'] for r in runs], 'speedup':legacy_ms/native_ms,
        'checks':runs[0]['checks'],'fault_fixture':failures['checks'],
        'passed':native_ms<2000 and legacy_ms/native_ms>2}
""".replace("GEOMETRY", repr(str(args.geometry.resolve())))
    client = Client()
    job = client.run("execute", {"code": code}, timeout=1)
    print(json.dumps({"job_id": job["job_id"], "state": job["state"]}), flush=True)
    while job["state"] in {"queued", "running"}:
        job = client.wait(job["job_id"], timeout=10)
    if job["state"] != "succeeded":
        raise RuntimeError(job)
    result = job["result"]["value"]
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
