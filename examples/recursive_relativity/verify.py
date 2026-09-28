"""Verify the staged/promoted live sculpture without saving or changing the artist time."""

import json
from pathlib import Path

from demo import DIRECTORY, STATE, execute, run

from houdini_companion.client import Client


def main():
    client = Client()
    state = json.loads(STATE.read_text())
    path = state["output"]
    report = {"frames": [], "hip_saved": False, "bounded_generations": 6}
    for frame in (1, 41, 81, 121, 161, 201, 241):
        result = run(client, "geometry.validate", path=path, profile="closed_solids", frame=frame)
        assert result["accepted"], result
        report["frames"].append({"frame": frame, **result})
    report["loop"] = run(
        client, "timeline.boundary", path=path, before=1, after=241, tolerance=0.001
    )
    assert report["loop"]["accepted"]
    report["motion"] = run(client, "timeline.boundary", path=path, before=1, after=41, tolerance=0)
    assert "POSITION_JUMP" in report["motion"]["reasons"], "Motion must be measurable"
    publication = json.loads(Path(state["publication"]["manifest"]).read_text())
    files = [
        [str(Path(state["publication"]["index"]).parent / image["name"]) for image in row["images"]]
        for row in publication["rows"]
    ]
    checks = execute(
        client,
        f"""
import hashlib, math
from houdini_companion.state_guard import time_state,StateGuard
from houdini_companion.saved_scene import geometry_signature
from houdini_companion.continuity import compare_images,image_pixels
node=hou.node({path!r})
with StateGuard(hou):
    a=geometry_signature(node.geometryAtFrame(41))
    node.geometryAtFrame(201)
    b=geometry_signature(node.geometryAtFrame(41))
    node.geometry()
    camera=hou.node('/obj/relativity_views/impossible')
    matrix=camera.worldTransform().inverted()
    axis=hou.Vector3((1,1,1)).normalized()
    screen_errors=[]
    # Homogeneous orthographic coordinates ignore camera-space depth.
    for generation in range(6):
        angle=math.radians(-14*generation+8*generation*math.sin(2*math.pi*(hou.frame()-1)/240))
        rotation=hou.Quaternion(math.degrees(angle),axis)
        center=hou.Vector3((8,5.2,.6)); scale=.53**generation
        points=[]
        for p in ((0,0,0),(13.8,13.8,13.8)):
            world=rotation.rotate((hou.Vector3(p)-center)*scale)-axis*generation*3.5+hou.Vector3((2000,0,0))
            points.append(world*matrix)
        screen_errors.append(math.hypot(points[0][0]-points[1][0],points[0][1]-points[1][1]))
    current={{'time':time_state(hou),'hip':hou.hipFile.path(),
        'camera_digest':hashlib.sha256(''.join(hou.node(p).asCode() for p in {state["before"]["camera_paths"]!r}).encode()).hexdigest()}}
    images={files!r}
    loop_images=[compare_images(image_pixels(images[0][i]),image_pixels(images[-1][i])) for i in range(2)]
result={{'deterministic':a==b,'projected_seam_errors':screen_errors,'artist_state':current,'loop_images':loop_images,'points':a['points'],'primitives':a['primitives']}}
""",
    )
    assert checks["deterministic"]
    assert max(checks["projected_seam_errors"]) < 1e-8
    for key in ("time", "hip", "camera_digest"):
        assert checks["artist_state"][key] == state["before"][key], key
    assert max(x["mean_absolute_difference"] for x in checks["loop_images"]) < 0.001
    report.update(checks)
    report["passed"] = True
    (DIRECTORY / "verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"passed": True, "report": str(DIRECTORY / "verification.json")}), flush=True)


if __name__ == "__main__":
    main()
