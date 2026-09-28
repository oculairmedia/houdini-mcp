# Build, review and delivery operations

These operations are built-in plugins in the shared CLI/MCP catalog. Discover
their complete schemas with `houdini-agent schema`. Use
`houdini-agent submit OPERATION --file params.json --wait 30` or
`Client.run(OPERATION, params)`. A timeout returns a tracked job: wait on its ID,
never resubmit a mutation with a fresh request ID to guess whether it ran.

## Operation sequence

| Bead | Operations | Behavior |
| --- | --- | --- |
| `houdini-mcp-vzp.22` | `build.stage`, `build.promote`, `build.discard` | Build an owned hidden SOP graph, cook and validate it, then expose the exact candidate after checking its observation. Failed builds remove only their owned container. |
| `.23` | `geometry.validate` | Explicit polygon profiles: `surface`, `open_cards`, `closed_solids`, `walkway`. Closed solids check welded topology, winding and each connected component's signed volume. Walking checks require explicit local-space ray probes. |
| `.24` | `render.start`, `render.step`, `render.status`, `render.cancel`, `render.release` | Pin observations and fixed cameras; render one missing or corrupt frame per job. Pause/resume without rewriting intact frames. |
| `.25` | `review.publish`, `review.release` | Verify artifact hashes and actual image decoding; publish a standalone player with synchronized views, frame scrubbing, play/pause, speed controls, annotations and linked geometry/timing evidence. Release unconsumed receipts without deleting published files. |
| `.26` | State guard, `scene.show`, `scene.save` | Restore declared temporary time and camera channels, report partial restoration; keep intentional presentation and persistence explicit. |
| `.27` | `save.verify`, `save.verify_status`, `save.release` | Reopen a saved fixture in a separate bounded hython process and compare declared outputs, cameras and dependencies. Never reload the interactive artist session. |
| `.28` | `timeline.boundary` | Match unique point IDs across fractional frames, report births/deaths and position jumps, optionally compare aligned fixed-camera images. |

The host remains Python/HOM. Plugins own operation semantics; the registry owns
schemas and effects; the UI dispatcher serializes HOM calls. CLI and MCP consume
the same contracts. No extra listener or binary sidecar is introduced.

## Example: stage and review a new object

```python
from houdini_companion.client import Client

client = Client()  # Rediscover current session, never hardcode dated IDs.

def run(operation, **params):
    job = client.run(operation, params, timeout=30)
    while job["state"] in ("queued", "running"):
        job = client.wait(job["job_id"], timeout=30)
    if job["state"] != "succeeded":
        raise RuntimeError(job)
    return job["result"]

candidate = run("build.stage", name="reviewed_box", profile="closed_solids",
                nodes=[{"id": "box", "type": "box"}], output="box",
                review_frames=[1, 1.25, 2])
# Review candidate["output"] while the object remains hidden.
sequence = run("render.start", path=candidate["output"],
               frames=[1, 1.25, 2], cameras=["/obj/review_camera"], resolution=640)
while not run("render.status", render_id=sequence["render_id"])["complete"]:
    run("render.step", render_id=sequence["render_id"])
review = run("review.publish", render_id=sequence["render_id"],
             destination="C:/reviews/unique-review-directory", title="Box review")
# After evaluating the candidate, promote it or call build.discard.
run("build.promote", build_id=candidate["build_id"], review_id=review["review_id"])
run("render.release", render_id=sequence["render_id"])
```

The camera must already exist. Published destinations and saved HIP destinations
must be new; existing files are never overwritten by these operations. Publication
is local and does not deploy to the internet. It works directly from `file://`.

## State, cancellation and recovery

Each bounded operation captures frame, FPS, frame range, playback range and
playback state. Declared camera channels/keyframes are restored where used.
Restoration attempts continue after a failure, and readback detects silent
failures. `STATE_RESTORE_FAILED` contains partial recovery evidence and the original
error. The guard is not an arbitrary Python undo mechanism or a complete viewport
snapshot. `scene.show` intentionally changes the selected viewport camera, unlocks
camera-to-view, enables the requested object and optionally changes frame.

`scene.save` saves the entire current HIP to a new destination. Copy mode uses
Houdini's backup writer (or native `mwrite -n` copy mode for a never-saved HIP),
preserving the original active filename and dirty flag;
`activate=true` intentionally performs Save As and clears the dirty flag. Call it
only for an authorized save or a disposable fixture. Verification certifies only declared SOP outputs/cameras and
discoverable source dependencies; it does not package sources or prove whole-town
portability. `save.release` removes pinned receipts, never the destination HIP.

Render cancellation is cooperative between phases, not a way to interrupt a
blocked native cook/render. `render.cancel` pauses future frame jobs;
`render.step(resume=true)` resumes explicitly. The durable manifest records per-frame
jobs, hashes, geometry checks, timings and restoration. Resume is supported in the
same runtime and scene. After restart, archived receipts remain evidence; mutation
and rendering are not automatically replayed. Stateful simulation must be cached.

The sequence freezes cameras at its anchor frame; it is intended for comparable
geometry review, not an animated-camera movie. Changed source/camera observations
reject subsequent frame work. Image differences are threshold measurements, not
perceptual or artistic quality judgments. Boundary correspondence requires unique
scalar integer/string point IDs, never an assumption that point ordering is stable.

Each rendered row records its source observation and evaluated geometry signature
at that exact frame. Boundary acceptance and publication revalidate sampled source,
geometry and artifact hashes. Old rows without this evidence must be re-rendered.
`build.promote` requires the `review_id` from a completed `review.publish`, covering
the candidate's declared `review_frames` (default: its staging frame). It checks
the unchanged candidate and published evidence again before exposing it. This
enforces complete sampled review evidence, not an artist's aesthetic approval.
Pending review receipts are limited to 16 and consumed on promotion; `review.release`
unpins an unconsumed receipt, and discarding a candidate drops its associated receipts. Verifier handles and saved receipts
survive HIP replacement; runtime shutdown terminates and reaps managed workers.

## Bounds and performance

Builds allow 64 nodes and 16 pending candidates. Render sequences allow 300 frames,
three views, 128–1280 resolution, a 256-million square-pixel budget and 16 pinned
sequences. Saved receipts and verifier handles are each limited to 16, with at
most two running verification processes and a 10–300 second timeout. Release
finished receipts to let ordinary artifact retention reclaim them.

Geometry profiles accept at most one million points and two million vertices;
boundary correspondence accepts one million points. Profiles do not prove
self-intersection freedom; clearance is limited to supplied rays. Deliberately
open cards must not be certified as closed solids.

Each render step returns to the UI between frames. Status uses a bounded cache of
artifact hashes keyed by path, size and timestamps, avoiding repeated full reads
of every completed frame. Publication independently rehashes every referenced
artifact. The portable regression suite tests cache read counts and a 10,000-polygon
topology workload against a 600 ms median budget, with existing transport/dispatch
performance gates retained.

## Repeatable acceptance

```powershell
python -X utf8 -m pytest tests/test_companion_workflow.py
$env:HOUDINI_COMPANION_AUTOSTART = '0'
& "$env:HFS/bin/hython.exe" scripts/verify_companion_workflow.py C:/reviews/new-acceptance-run
python -m pip install playwright
python scripts/verify_review_player.py C:/reviews/new-acceptance-run/review/index.html --browser 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
```

Use a new output directory every run. The hython script creates its own disposable
scene and launches another fresh process for reopen verification. It does not
load the artist HIP. The browser check uses an isolated headless context, asserts
actual image decode and controls, and writes a screenshot plus JSON evidence.
Playwright is an optional developer test tool, not a companion runtime dependency.

The acceptance script exercises failed VEX cleanup, stale candidate rejection,
orientation/clearance failures, pause/resume, corrupt-frame repair, changed camera
and source rejection, continuous/discontinuous geometry and images, fresh reopen,
changed dependencies and explicit receipt release. Portable fault tests cover
partial state restoration, worker failure/timeout, resource bounds and unsafe
publication. Wider recovery, portable packaging and external plugin lifecycle
remain separate roadmap Beads.
