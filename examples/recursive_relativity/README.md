# Recursive Relativity

An Escher-inspired Houdini sculpture with three gravity directions, tiled stairs,
Romanesque arcades, amber figures and six smaller copies spiraling into its center.
The inner copies twist gently while the figures pace, repeating every 240 frames.

The orthographic **impossible** camera aligns the two separated ends of the stair
chain. The **reveal** camera exposes the construction. This is an intentional
projection illusion: the world-space chain is not physically closed. Recursion is
bounded to six generations, keeping the sculpture interactive.

## Live scene

- Geometry: `/obj/recursive_relativity/OUT_RELATIVITY`
- Hero camera: `/obj/relativity_views/impossible`
- Construction camera: `/obj/relativity_views/reveal`
- Animation: play or scrub frames 1–240 at 24 FPS; frame 241 repeats frame 1.
- Source controls: `relativity` generates the architecture and figures;
  `recursive_drift` animates the nested worlds; `isolate` moves this example away
  from the existing town.

The demo is a separate object in the current HIP. The builder does not save or
reload the HIP, edit artist geometry/camera definitions, or change the timeline
settings. `show` deliberately switches the active viewport to the new hero camera.

## Reproduce in a live companion

From an editable installation of the repository:

```powershell
python examples/recursive_relativity/demo.py stage
python examples/recursive_relativity/demo.py review --frames 1,41,81,121,161,201,241 --resolution 960
python examples/recursive_relativity/verify.py
python examples/recursive_relativity/demo.py promote
python examples/recursive_relativity/demo.py show
```

The hidden candidate is reviewed before promotion. Existing demo receipts or
camera rigs are refused to prevent accidental replacement. For a second study,
explicitly discard the owned candidate and choose a separate output/rig, or use
a disposable scene. Local receipts, PNGs and standalone HTML live beneath
`~/.houdini-companion/recursive-relativity`. These media are not committed.

Review generation uses `render.start`/`render.step` and `review.publish`; each frame
returns control to Houdini. Published PNG and geometry samples remain available
after the render receipt is released. The final live preview uses 61 samples over
the complete cycle, with synchronized impossible and revealing views.

## Evidence

[verification.json](verification.json) records seven sampled solid-profile checks,
zero degenerate/inward components, stable point identity, deterministic geometry,
measured motion, loop closure, paired-image loop agreement and projected seam
alignment. The object contains 87,696 points and 21,924 polygons. The checks cover
the samples, not arbitrary continuous collisions between nested worlds.

This example also exposed a companion camera bug: orthographic recipes omitted
`orthowidth`. Bead `houdini-mcp-vzp.30` adds the missing channel to capture, render
defaults and camera-state/signature handling. The disposable workflow acceptance
now includes a non-default orthographic camera and fresh-process reopen.
