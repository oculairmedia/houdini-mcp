# The City Within

A procedural concept demo requested by the artist: walking through successively
smaller courtyards while the viewpoint shrinks, with increasing architectural
subdivision. The existing town remains separate.

## Run against the live companion

From the repository root, with Houdini's companion running:

```powershell
.venv\Scripts\python.exe examples/recursive_courtyard/demo.py build
.venv\Scripts\python.exe examples/recursive_courtyard/verify.py
.venv\Scripts\python.exe examples/recursive_courtyard/demo.py render --frames 1:240
.venv\Scripts\python.exe examples/recursive_courtyard/demo.py render --frames 97:192 --backward
.venv\Scripts\python.exe examples/recursive_courtyard/package_review.py
```

The demo creates `/obj/recursive_courtyard_demo` at X=1000, a hidden geometry
object, its own camera/lights, and `/out/recursive_courtyard_preview`. It refuses
to overwrite an existing demo. `refresh` updates only the owned VEX node.
The VEX is embedded in the node, not referenced from a temporary source file.
No HIP is saved, no artist source is written, and artist cameras, frame ranges,
FPS and playback state are preserved. The render restores the incoming frame
and its own camera rotation. Build/edit operations use the companion undo group.

Artifacts are under `%USERPROFILE%/.houdini-companion/recursive-courtyard/`.
Open `index.html` for the evaluation player, or play `forward.mp4` and
`backward.mp4` directly. FFmpeg is required only for video packaging. Rendered
media and the artist-state snapshot are local, not source-controlled.

In Houdini, inspect `architecture/recursive_city` inside the demo subnet. Its
**Journey** control advances one generation per unit; its default expression
uses frames 1–240 for a ten-second preview. **Scale per threshold** defaults to
0.58. The geometry is hidden from the artist viewport; to inspect it there,
enable only this demo's geometry display and look through its `walkthrough`
camera. Removing the owned subnet and owned ROP removes the live demo.

## Spatial construction and limits

Generation k has scale `q^k` and doorway position
`z_k = 14 * (1 - q^k) / (1 - q)`. Expressing this relative to a viewer at journey
u gives scale `q^(k-u)` and relative Z `14 * (1-q^(k-u))/(1-q)`. This keeps the
local geometry stable instead of shrinking world coordinates to zero.

Thirteen generations surround the viewpoint: four behind, the current one and
eight ahead. They are regenerated as the viewpoint advances. This is a bounded
window into a recursive construction, not infinitely many resident polygons.
Ornament subdivision caps after the first few generations; scale recursion
continues. The deepest layers and old rear layers are eventually clipped by
the finite window. Arbitrary edits to the scale control require revalidation.

The live verifier checks finite positions and ray-sampled walking clearance at
69 times (including either side of each generation boundary), deterministic
repeated evaluation, a full polygon audit and outward solid orientation at
frame 40, bounded geometry at virtual generations 10/100/1000, and preserved
artist camera/time/HIP state. This is not a proof of watertightness, arbitrary
self-intersection freedom or continuous collision avoidance.

Tracking: `houdini-mcp-vzp.21`. This concept demo does not complete the independent
pre-apply temporal review infrastructure in `.18`.
