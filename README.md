# Houdini MCP Server

An MCP (Model Context Protocol) server for controlling SideFX Houdini via `hrpyc`, enabling AI assistants like Claude, Cursor, and Letta agents to interact with Houdini sessions.

## Persistent companion (Windows / Houdini 20.5)

The optional companion lives inside the interactive Houdini session. The
`houdini-agent` CLI and `companion_*` MCP tools share its tracked job queue,
observations, previews, undo records and rendered feedback. Closing an agent or
the panel does not stop the companion. Scene operations execute serially on
Houdini's UI thread; HTTP requests can still query or cancel queued jobs.

From an editable installation of this checkout:

```powershell
python -m pip install -e '.[dev]'
houdini-agent install --prefs "$env:USERPROFILE\houdini20.5"
houdini-agent doctor
houdini-agent schema
houdini-agent inspect --selected --geometry
houdini-agent snapshot --path /obj/geo1/OUT --views front,right,persp
```

The package starts the companion on the next Houdini launch. Set
`HOUDINI_COMPANION_AUTOSTART=0` to disable automatic startup. To attach to an
already open session with `hrpyc` on port 18811, run
`python scripts/bootstrap_companion.py`; this does not restart Houdini or save
the HIP. The Python Panel interface is named **Houdini Companion**.
`python -m houdini_companion.cli` also works if the console script is not on PATH.

Use `inspect` to get `result.observation.token`. Submit parameter edits through
`submit batch --file request.json --wait 30`, with a request shaped like:

```json
{
  "actions": [{"op": "set", "path": "/obj/geo1/box1", "values": {"sizex": 2}}],
  "expected": {"/obj/geo1/box1": "TOKEN_FROM_INSPECT"},
  "output": "/obj/geo1/box1"
}
```

Batch actions support create, set, connect, flags and delete. New nodes can be
named with an `as` alias and referenced as `$alias` later in the same batch.
Existing paths require observation tokens. Reusing a request ID with the same
payload returns the same job; changed payloads are rejected. A wait timeout
returns a trackable running job: use `job status JOB_ID`, `job wait JOB_ID` or
`job cancel JOB_ID`. Cancellation cannot forcibly interrupt a running HOM cook.

`preview` takes `path`, `expected` and `values`; it produces before/after images
using copied SOPs, frozen inputs and staged quoted VEX includes. This release
supports ordinary built-in leaf SOPs and locked standard Attribute Wrangles.
`apply_preview` takes `preview_id`, validates the original again and applies the
parameter values. It does not write source files. `undo` takes `job_id` and
refuses to undo across newer user work. Arbitrary `run script.py` / `execute`
is trusted Python, with no sandbox or atomic rollback guarantee.

MCP exposes `companion_schema`, `companion_status`, `companion_inspect`,
`companion_submit`, `companion_job`, `companion_cancel`, `companion_events` and
`companion_feedback`. Feedback returns native MCP images. Existing legacy tools
keep their current backend unless the MCP server starts with
`HOUDINI_BACKEND=companion`; unsupported legacy mappings then fail explicitly.

Descriptors and artifacts live under `%USERPROFILE%\.houdini-companion`.
The service binds to `127.0.0.1:18812` and requires the per-session token stored
in the descriptor. Do not share that file. `HOUDINI_COMPANION_HOME` and
`HOUDINI_COMPANION_PORT` override these defaults; `--pid` selects a process.
Snapshots include frozen geometry, PNG hashes, cook/render timings, bounded
geometry diagnostics and blank-image checks. These are basic checks, not proof
of artistic correctness. Source observations describe files on disk; Houdini's
existing compiled VEX cache cannot be fingerprinted reliably. Snapshot `focus`
accepts a bounding box in SOP local space for closeups.

Per-session artifact pruning keeps receipts while bounding generated content
to 64 recent jobs / approximately 1 GiB, excluding active jobs and previews.
Archived sessions remain available for recovery and need manual retention
management. Restarted sessions mark archived results stale and never replay
unfinished mutations automatically. Startup registration is installed by the
package; its next-launch behavior requires a Houdini restart to exercise.

Companion tests: `python -X utf8 -m pytest tests/test_companion_*.py` (expand the
filenames on shells without glob expansion). Live checks use
`scripts/verify_companion_live.py` and `scripts/verify_companion_service.py`;
they create and clean up owned fixtures without saving the HIP.

### Companion plugins and programmatic review

`houdini-agent schema --live` describes the active plugin versions, operation
owners, effects and parameter contracts. Offline `schema` lists shipped plugins.
The built-in plugins are query, scene, review, execution, introspection,
acceptance and iteration. Existing operation names remain compatible.

| Operation | Result |
| --- | --- |
| `query.graph` | Bounded nodes, input connections, errors and warnings |
| `query.parameters` | Wildcard-filtered parameter values, types and menu/range metadata |
| `query.node_types` | Types installed in the running Houdini, filtered by category/name |
| `query.geometry` | Bounded samples of named point attributes, with offset and truncation |
| `query.batch` | Up to 16 read operations in one UI dispatch |
| `review.accept` | Rendered feedback, explicit acceptance checks and an evidence hash |
| `review.compare` | Point/primitive deltas, bounds and geometry hashes for retained reviews |
| `iteration.capture` | Frozen inputs, source backups, guard tokens and baseline images |
| `iteration.stage` | Candidate evaluation, complete polygon checks and paired images |
| `iteration.apply` | Guarded source/parameter application with a recovery journal |
| `iteration.restore` | Guarded restoration of original source bytes and node snippet |
| `iteration.release` | Release session handles when their restore capability is no longer needed |

For example, pass this JSON to `submit query.batch --file queries.json --wait 30`:

```json
{"queries":[
  {"operation":"query.graph","params":{"path":"/obj/geo1","depth":2,"limit":32}},
  {"operation":"query.geometry","params":{"path":"/obj/geo1/OUT","attributes":["P","Cd"],"limit":16}}
]}
```

`review.accept` accepts `path`, optional `expected`, `views`, `resolution` and
`requirements`. Requirements include `min_points`, `min_primitives`,
`max_warnings`, `required_point_attributes` and `min_coverage`. Coverage is a
sampled alpha estimate; it measures framing, not artistic quality. The default
checks require nonempty geometry, complete bounded geometry checks, finite
points, nonzero polygon areas, fresh inputs and visible images. Large geometry
outside the diagnostic budget does not receive a complete acceptance verdict.
Inspect `result.accepted` even when the job successfully executed. The CLI exits
nonzero for an explicitly rejected acceptance result; asynchronous submissions
must first be waited on. No scene file is saved by these operations.

The registry approach is informed by
[Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent), and the
discoverable command/evidence workflow by
[Blender CLI](https://github.com/renezander030/blender-cli). This implementation
does not vendor their code.

An extension exports `plugin() -> PluginSpec` from an importable Python module.
See `examples/companion_plugins/diagnostics.py` for a working example.
Set `HOUDINI_COMPANION_PLUGINS=your_package.your_module` before starting the
companion; comma-separated module names are supported. Stop/restart the idle
companion to change its catalog. Installed packages are never auto-enabled.

Plugin API v1 uses `OperationSpec(name, effect, schema, handler, description)`.
Handlers receive `(context, job, **params)` and return a finite JSON object,
limited to 4 MiB. The context provides `hou`, `ledger`, scene-scoped `state` and
`call(operation, job, **params)` for composition. Store state under your plugin
name. Call `ledger.checkpoint(job['job_id'])` between expensive phases. Handlers
execute on Houdini's UI thread, and must not retain HOM objects on worker threads.
Effects describe trusted code; they are not a security sandbox. Grouped queries
reject operations with mutating effects and reject recursive grouped calls.

Manifests declare plugin name/version, `api_version=1` and plugin dependencies.
Duplicate names, operation collisions, unsupported API versions, missing/cyclic
dependencies and unsupported schema keywords fail before the listener starts.
The supported schema subset covers objects/properties/required fields, arrays,
primitive types, enums, numeric bounds and length bounds. It does not support
`$ref`, combinators or arbitrary JSON Schema keywords.

### Agent-native animation and temporal review

The CLI supports scoped discovery and small job receipts, inspired by
[Blender CLI](https://github.com/renezander030/blender-cli). The same registered
operations are available through MCP; Houdini semantics stay in embedded plugins.

```powershell
houdini-agent schema --live --command 'animation.*' --compact
houdini-agent schema --command 'timeline.*' --effects read,artifacts --compact
houdini-agent time inspect --path /obj/town/road_generator/ANIMATE_STREET_LIFE --wait 1 --compact
houdini-agent animate --file keys.json --wait 1 --compact
houdini-agent time sample --path /obj/town/OUT --frames 1,49,97,145,193,240,97.5,1 --require-motion --max-cook-ms 500 --resolution 640 --wait 1 --compact
houdini-agent job wait JOB_ID --timeout 30 --compact
```

`submit --file -` and `animate --file -` accept JSON on stdin. Recipes accept
UTF-8 with or without a BOM. Argument errors and rejected acceptance gates return
JSON and a nonzero exit status. A running receipt gives the exact continuation
command; a timeout does not cancel or resubmit it. New runtimes provide bounded
waits for existing jobs, with two wait slots; older runtimes use polling backoff.

An animation recipe addresses scalar numeric parameters by absolute path:

```json
{"tracks":[{"path":"/obj/geo1/transform1/tx",
 "keys":[{"frame":1,"value":0},{"frame":49,"value":4}],
 "interpolation":"linear"}],
 "expected":{"/obj/geo1/transform1":"token from timeline.inspect"}}
```

`animation.control` adds a new named float control to an explicitly guarded node.
It refreshes wrangle source identity when needed so a previously missing `chf()`
binding does not remain constant. `animation.keyframes` validates the entire
batch before mutation, replaces channels using batched HOM keyframes, and returns
an `animation_id`. Use `animation.restore` with that ID to restore original keys,
extrapolation and constant values while rejecting subsequent channel/FPS edits.
Journals retain original channel code for manual recovery; restore handles are
session scoped. The contract supports linear/constant scalar channels and does
not change timeline ranges, FPS, or save the HIP. This is handled rollback,
not crash-atomic recovery.

`timeline.sample` evaluates 2–32 explicit frames through `geometryAtFrame`,
including fractional frames and repeat samples. It records frame, seconds, FPS,
cook counts, initial access cost, per-frame timings, complete polygon diagnostics,
position changes and ordered topology hashes. Camera framing spans the sampled
bounds and stays fixed; an optional `focus` box supports detailed reviews. Output
includes a labeled contact sheet, individual images, frozen geometry and a hashed
`sequence.json` manifest. The original time/playback state is restored on handled
failure or cancellation. Artist cameras are not edited.

Acceptance can require motion, stable topology, a geometry-evaluation budget and
maximum sampled average point speed. Repeated frames test determinism. Motion
comparison assumes stable point ordering; it does not prove continuous collision
freedom or semantic point identity. Known DOP/solver inputs are rejected: arbitrary
stateful simulations need an explicit cache/preroll contract. The render budget
is 32 million pixels. Render, audit and geometry timing are distinct; a cached
access is not presented as forced regeneration.

Inline VEX candidates can also use the iteration workflow: pass `snippet` to
`iteration.stage` instead of `files`. Existing quoted-include restrictions and
guarded apply/restore remain in effect. No scene-specific Python is needed for
channel authoring, inline VEX review, or multi-frame acceptance.

Run the live disposable acceptance fixture with:

```powershell
python scripts/verify_companion_temporal.py
```

It exercises moving and static controls, fractional/repeated frames, channel
restoration, and a wrangle compiled before its new control exists. Portable CI
tests cover output bounds, schema filtering, frame limits, failure restoration,
long-job request counts, and a 250 ms million-point motion-analysis budget.

[Recorded temporal iteration evidence](benchmarks/live-temporal-2026-09-27.json)
includes a 31-frame town review, seven moving vehicles, complete geometry checks,
static-generator cook counts, transport request counts and rejected candidates.
The scene motion approaches and stops before intersections; it is not a seamless
traffic simulation. Scene edits remain live until the artist saves the HIP.

### Iteration performance regression checks

The iteration plugin replaces custom staging scripts for built-in attribute
wrangles with trusted VEX and quoted source includes. A typical capture request
passed to `houdini-agent submit iteration.capture --file capture.json --wait 30` is:

```json
{"path":"/obj/town/building_generator/GENERATE_BUILDINGS",
 "guards":["/obj/town/TOWN_CONTROLS"],
 "cameras":["/obj/town_oblique_cam","/obj/town_street_cam"],
 "views":["camera_0","camera_1","persp"],"resolution":1100}
```

Pass its `capture_id` to `iteration.stage`, with `files` containing objects with
`path` (a captured include) and `content` (candidate UTF-8 text). Optional
`benchmark_samples: 3` measures regeneration by changing an input detail
attribute on a disposable input. Stage temporarily binds the target node to
frozen inputs and candidate code, then restores its original code and connections
before returning. This keeps relative channel references and Houdini's node-local
compiled cache, avoiding a second compile on apply. A `stage-transaction.json`
records recovery state before preview. This is a transient scene mutation, not
an isolated process or crash-atomic preview; handled failures restore state. Sibling
display/render flags are restored, including on failure. Unchanged sources use
content-addressed paths without timestamp churn; modified cache files fail closed.
Apply promotes the exact compiled source revision. The runtime snippet references
that immutable revision under `%USERPROFILE%/.houdini-companion/sources`, while
the editable include files are updated separately. A node source manifest retains
the editable snippet and fingerprints both sets of dependencies. Later captures
continue to target editable includes. Persistent revisions are not artifact-pruned;
do not delete them while a scene references them. External source edits require
another staged apply (or explicitly restoring the authored snippet); they do not
silently mutate an already reviewed runtime revision.

Inspect `before`, `after`, `accepted_basic_checks` and the actual images. Apply
with `{"stage_id":"..."}` to `iteration.apply`; restore with its `apply_id` to
`iteration.restore`. These are available through the generic CLI and MCP submit
interfaces and the live schema. A client timeout returns the running job: wait
on that job instead of resubmitting it. No operation saves the HIP.

Full iteration diagnostics use bulk point buffers and a native parallel VEX
polygon pass. Results enumerate coverage, exclusions and bounded examples;
checks allow surface cards and make no watertightness/self-intersection claim.
Mesh comparison hashes ordered primitive topology and point/vertex/primitive
tuple attributes plus detail attributes. It excludes groups and file metadata
(bgeo embeds timestamps); array attributes currently fail explicitly. Byte
hashes remain available for artifact integrity. NumPy comes with Houdini and is
a development dependency for portable regression tests.

Review cameras preserve captured transforms, lens settings and output aspect.
Scale-aware clipping and an owned diffuse material remove depth stripes and
specular glare; diagnostic lights disable shadows. Artist cameras, materials
and lights are not edited. These are geometry review images, not final lighting.
Automatic views fit projected geometry points, avoiding empty space caused by
sparse tall bounding boxes. Capture freezes those camera recipes so before/after
images use identical framing. Explicit focus boxes retain their requested bounds.

Timings distinguish geometry access, freeze, diagnostics, render and total time.
Cook counters reveal cached access. A first candidate access combines VEX
compilation and cooking; no compiler-only timing is inferred. Invalidated
regeneration samples exclude initial compilation and include input processing.

Source writes use expected hashes, atomic replacement per file, and a durable
`transaction.json` containing original bytes and snippets. Handled failures
restore files and parameters; a competing edit is preserved and reported as
`ROLLBACK_FAILED`. This is not atomic across a process crash. Journals survive
artifact pruning for manual recovery, while automatic restore handles are
session/scene scoped. Use `iteration.restore` for coordinated restoration;
ordinary Houdini undo cannot restore external files. This contract does not
discover arbitrary VEX file/network reads or undeclared scene dependencies.

Live verification and a matched-asset audit performance gate:

```powershell
python scripts/verify_companion_iteration.py
python scripts/benchmark_companion_geometry.py frozen.bgeo.sc --output audit.json
```

The fixture exercises nested-subnet capture, failed-preview recovery, candidate
application, full audit, stable paired framing, recapture of editable sources,
invalidated regeneration and source restoration. The audit benchmark compares
the previous complete Python checks with native checks on the same asset and
injects known defects. Its gate requires at least 2x speedup and a native median
under 2 seconds. CI separately enforces a 250 ms million-point buffer budget,
transaction failure behavior, semantic comparison and immutable-source contracts.

[Recorded Windows/Houdini 20.5 measurements](benchmarks/live-iteration-2026-09-27.json)
include four town improvement cycles: a matched-asset full audit fell from
14.52 seconds to a 199 ms median (73x), and the final reviewed apply took
2.00 seconds after eliminating duplicate compilation. A new VEX candidate still
required about 51 seconds for its first compile and cook on that scene.

Short operations reuse HTTP connections and cached session identity. A bounded
server wait can return the completed job in the submit response, avoiding a
polling round trip. Only two HTTP workers may wait; others remain available for
status/cancellation. Identity failures are returned without replaying edits.

The companion CI workflow runs contract tests, request-count guards and a
`pytest-benchmark` dispatch budget on Windows and Linux. It uploads the timing
report even on failure. CI does not pretend to test live Houdini performance.
For that, run a read-only baseline on a stable lightweight node:

```powershell
python scripts/benchmark_companion.py --path /obj/town_cam --output baseline.json
python scripts/benchmark_companion.py --path /obj/town_cam --baseline baseline.json --output candidate.json
```

The live gate records p50/p95, UI queue time, execution time and response bytes.
It rejects host/platform/Houdini/target mismatches and fails if a workload's p95
exceeds the larger of 1.35 times its baseline or baseline plus 20 ms. Keep the
target and scene comparable between runs. Tests for the gate itself verify that
an intentional regression fails. Run `scripts/verify_companion_plugins_live.py`
with a frozen `.bgeo.sc` specimen to verify grouped queries, successful and
rejected review gates, comparison and fixture cleanup.

## Architecture

```
+-----------------+      MCP (HTTP)       +------------------+      hrpyc:18811      +-------------+
|  Claude/Cursor  | <------------------> |   MCP Server     | <------------------> |   Houdini   |
|  Letta Agents   |                      |  (Python/FastMCP)|                      |   Session   |
+-----------------+                      +------------------+                      +-------------+
```

## Architecture Decisions

Architecture Decision Records (ADRs) live in [`docs/adr/`](docs/adr/):

- [ADR 0001: Language and Process Boundaries](docs/adr/0001-language-and-process-boundaries.md)
  — why the server stays Python for `hou` semantics and the FastMCP gateway, the
  module boundaries and allowed dependency direction, and the measured thresholds
  that would justify a future non-Python sidecar.

## Features

- **43 MCP tools** across 15 modular categories
- **Full hou module access** - Execute any Houdini Python code remotely
- **Scene management** - Create, load, save scenes
- **Node operations** - Create, delete, modify nodes and parameters
- **Rendering** - Viewport renders, quad views, Karma GPU/CPU support
- **Pane screenshots** - Capture NetworkEditor, SceneViewer, and other panes
- **Scene serialization** - Diff scene states before/after operations
- **Connection management** - Auto-reconnect with exponential backoff + jitter
- **Error handling** - Consistent error responses with recovery hints
- **Response optimization** - Size limits, truncation, AI summarization
- **In-memory caching** - Node type cache with TTL for performance

## Prerequisites

1. **Houdini with RPC enabled** - Start Houdini's RPC server:
   - In Houdini: `Windows > Python Shell`, then run:
     ```python
     import hrpyc
     hrpyc.start_server(port=18811)
     ```
   - Or add to your `123.py` startup script for automatic startup

2. **Network access** - The MCP server must be able to reach Houdini's RPC port (default: 18811)

## Installation

For Codex Desktop on Windows, see the dedicated setup notes in
[`docs/codex-windows-setup.md`](docs/codex-windows-setup.md).

### Option 1: Houdini Plugin (stdio mode)

The Houdini plugin runs the MCP server directly inside Houdini, using stdio transport. This is the simplest setup with no network configuration required.

**Installation:**

1. Copy the `houdini_plugin` folder to your Houdini packages directory:
   ```bash
   # Windows
   copy houdini_plugin %USERPROFILE%\Documents\houdini20.5\packages\houdini_mcp
   
   # Linux/Mac
   cp -r houdini_plugin ~/houdini20.5/packages/houdini_mcp
   ```

2. Copy the package JSON:
   ```bash
   # Windows
   copy houdini_plugin\houdini_mcp.json %USERPROFILE%\Documents\houdini20.5\packages\
   
   # Linux/Mac
   cp houdini_plugin/houdini_mcp.json ~/houdini20.5/packages/
   ```

3. Install FastMCP in Houdini's Python:
   ```bash
   # Windows (from Houdini's Python)
   hython -m pip install fastmcp
   
   # Or from Houdini's Python Shell
   import subprocess
   subprocess.run(["pip", "install", "fastmcp"])
   ```

4. Restart Houdini and find the "Houdini MCP" shelf

**Usage:**
- Click "Start MCP" on the shelf to start the server
- Configure your MCP client (Claude Desktop, Cursor, etc.) to use stdio transport
- Click "Stop MCP" to stop the server

**MCP Client Configuration (stdio mode):**
```json
{
  "mcpServers": {
    "houdini": {
      "command": "hython",
      "args": ["-c", "from houdini_mcp_plugin import start_server; start_server(use_thread=False)"]
    }
  }
}
```

### Option 2: Docker (Remote mode)

For production use or when Houdini runs on a different machine, use the Docker-based remote mode. This connects to Houdini via hrpyc/RPyC.

**Step 1: Start hrpyc in Houdini**

If you have the Houdini MCP plugin installed:
- Click **"Start Remote"** on the Houdini MCP shelf
- Use **"Remote Status"** / **"Remote Self-Test"** to confirm the actual bound
  endpoint, reachability, and firewall guidance
- By default the listener binds to `127.0.0.1` (loopback-only). To let a
  remote client (e.g. the Docker gateway on another host) connect, set
  `HOUDINI_RPC_BIND_HOST` **and** opt in with `HOUDINI_RPC_TRUSTED_NETWORK=1`
  or `HOUDINI_RPC_TOKEN`. See [docs/remote-listener.md](docs/remote-listener.md).

Or manually in Houdini's Python Shell (unchanged, still supported):
```python
import hrpyc
hrpyc.start_server(port=18811)
```

**Step 2: Run the Docker MCP server**

```bash
# Clone the repository
git clone https://github.com/oculairmedia/houdini-mcp.git
cd houdini-mcp

# Copy and configure environment
cp .env.example .env
# Edit .env with your Houdini host IP (from Step 1)

# Run with Docker Compose
docker compose up -d
```

**Step 3: Configure your MCP client**

```json
{
  "mcpServers": {
    "houdini": {
      "url": "http://localhost:3055"
    }
  }
}
```

**Benefits of Remote Mode:**
- Houdini can run on a different machine (e.g., render farm)
- MCP server runs in Docker for easy deployment
- Full tool set with advanced features
- Server-side processing capabilities

### Local Development

```bash
# Clone and install
git clone https://github.com/oculairmedia/houdini-mcp.git
cd houdini-mcp
pip install -r requirements.txt

# Run
HOUDINI_HOST=192.168.50.90 python -m houdini_mcp
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOUDINI_HOST` | `localhost` | Houdini machine IP/hostname |
| `HOUDINI_PORT` | `18811` | hrpyc server port |
| `MCP_PORT` | `3055` | MCP server HTTP port |
| `MCP_TRANSPORT` | `http` | Transport type (http, stdio, sse) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Tool Categories (43 Tools)

The server is organized into 15 modular tool categories in `houdini_mcp/tools/`:

### Scene & Nodes (`scene.py`, `nodes.py`)
| Tool | Description |
|------|-------------|
| `get_scene_info` | Get current scene info (file, version, nodes) |
| `serialize_scene` | Serialize scene structure for diffs |
| `new_scene` | Create empty scene |
| `save_scene` | Save current scene |
| `load_scene` | Load a .hip file |
| `create_node` | Create a new node |
| `delete_node` | Delete a node by path |
| `get_node_info` | Get node details, parameters, connections, errors |
| `list_children` | List child nodes with connection details |
| `find_nodes` | Find nodes by name pattern or type |
| `list_node_types` | List available node types by category |

### Wiring & Layout (`wiring.py`, `layout.py`)
| Tool | Description |
|------|-------------|
| `connect_nodes` | Wire nodes together |
| `disconnect_node_input` | Break a connection |
| `reorder_inputs` | Reorder node inputs |
| `set_node_flags` | Set display/render/bypass flags |
| `layout_children` | Auto-layout child nodes |
| `set_node_position` | Set node position in network |
| `set_node_color` | Set node color |
| `create_network_box` | Create network box around nodes |

### Parameters (`parameters.py`)
| Tool | Description |
|------|-------------|
| `set_parameter` | Set a parameter value |
| `get_parameter_schema` | Get parameter metadata (types, ranges, menus) |

### Geometry & Materials (`geometry.py`, `materials.py`)
| Tool | Description |
|------|-------------|
| `get_geo_summary` | Get geometry statistics and metadata |
| `create_material` | Create a new material |
| `assign_material` | Assign material to geometry |
| `get_material_info` | Get material parameters and shaders |

### Rendering (`rendering.py`)
| Tool | Description |
|------|-------------|
| `render_viewport` | Render viewport with camera control |
| `render_quad_view` | Render Front/Left/Top/Perspective views |
| `list_render_nodes` | List all ROPs in /out |
| `get_render_settings` | Get ROP configuration |
| `set_render_settings` | Modify ROP settings |
| `create_render_node` | Create new ROP with settings |

### Pane Screenshots (`pane_screenshot.py`)
| Tool | Description |
|------|-------------|
| `capture_pane_screenshot` | Capture any Houdini pane as PNG |
| `list_visible_panes` | List capturable panes |
| `capture_multiple_panes` | Batch capture multiple panes |
| `render_node_network` | Navigate to node and capture network |

### Code Execution (`code.py`, `hscript.py`)
| Tool | Description |
|------|-------------|
| `execute_code` | Execute Python with `hou` available |
| `execute_hscript` | Execute HScript commands |

### Error Handling (`errors.py`)
| Tool | Description |
|------|-------------|
| `find_error_nodes` | Find all nodes with cook errors |

### Help & Summarization (`help.py`, `summarization.py`)
| Tool | Description |
|------|-------------|
| `get_houdini_help` | Get help for node types |
| `summarize_response` | AI-summarize large responses |
| `estimate_tokens` | Estimate token count |
| `get_summarization_status` | Get summarization config |

### Infrastructure (`_common.py`, `cache.py`)
- **Error handling**: `@handle_connection_errors` decorator
- **Connection retry**: Exponential backoff with jitter
- **Response size**: Thresholds, truncation, metadata
- **Caching**: Node type cache with TTL
- **Parallel execution**: `semaphore_gather`, `batch_items`

## Common Patterns

### Creating SOP Chains

Build a complete SOP network from scratch:

```python
# 1. Create geo container
geo = create_node("geo", "/obj", "my_geo")

# 2. Create SOP nodes
sphere = create_node("sphere", geo["node_path"], "sphere1")
xform = create_node("xform", geo["node_path"], "xform1")
color = create_node("color", geo["node_path"], "color1")
out = create_node("null", geo["node_path"], "OUT")

# 3. Wire nodes together
connect_nodes(sphere["node_path"], xform["node_path"])
connect_nodes(xform["node_path"], color["node_path"])
connect_nodes(color["node_path"], out["node_path"])

# 4. Set display flag
set_node_flags(out["node_path"], display=True, render=True)
```

### Inserting Nodes Into Existing Chains

Insert a new node between existing connections:

```python
# 1. Discover existing network
children = list_children("/obj/geo1")
# Find grid and noise nodes from children

# 2. Get current connections
noise_info = get_node_info("/obj/geo1/noise1", include_input_details=True)
# See that noise is connected to grid

# 3. Create new node
mountain = create_node("mountain", "/obj/geo1", "mountain1")

# 4. Rewire: grid → mountain → noise
disconnect_node_input("/obj/geo1/noise1", 0)  # Break noise ← grid
connect_nodes("/obj/geo1/grid1", "/obj/geo1/mountain1")  # grid → mountain
connect_nodes("/obj/geo1/mountain1", "/obj/geo1/noise1")  # mountain → noise
```

### Setting Parameters Intelligently

Use parameter schema to set values correctly:

```python
# 1. Discover parameter metadata
schema = get_parameter_schema("/obj/geo1/sphere1", parm_name="rad")
param = schema["parameters"][0]

# 2. Check parameter type
if param["type"] == "vector":
    # Set vector parameter correctly
    set_parameter("/obj/geo1/sphere1", "rad", [3.0, 3.0, 3.0])
elif param["type"] == "menu":
    # Use menu items
    first_option = param["menu_items"][0]["value"]
    set_parameter("/obj/geo1/sphere1", "type", first_option)
```

### Verifying Results

Always verify geometry after operations:

```python
# Get comprehensive geometry summary
summary = get_geo_summary(
    "/obj/geo1/OUT",
    max_sample_points=10,
    include_attributes=True
)

# Check cook state
if summary["cook_state"] != "cooked":
    # Handle errors
    node_info = get_node_info("/obj/geo1/OUT", include_errors=True)
    errors = node_info["cook_info"]["errors"]
    # Fix errors...

# Verify geometry metrics
assert summary["point_count"] > 0
assert summary["primitive_count"] > 0

# Check bounding box
bbox = summary["bounding_box"]
# Verify expected size/position
```

## Error Handling Best Practices

### Check Cook State Before Reading Geometry

```python
# 1. Check cook state first
node_info = get_node_info(
    node_path,
    include_errors=True,
    force_cook=True
)

cook_state = node_info["cook_info"]["cook_state"]

# 2. Handle different states
if cook_state == "error":
    # Examine errors
    errors = node_info["cook_info"]["errors"]
    for err in errors:
        print(f"Error: {err['message']}")
    # Fix errors...
elif cook_state == "cooked":
    # Safe to access geometry
    geo = get_geo_summary(node_path)
```

### Validate Parameter Types

```python
# Always check parameter schema before setting
schema = get_parameter_schema(node_path, parm_name="rad")
param = schema["parameters"][0]

if param["type"] == "vector":
    # Use list/tuple for vector parameters
    set_parameter(node_path, "rad", [5.0, 5.0, 5.0])
else:
    # Use scalar for single parameters
    set_parameter(node_path, "rad", 5.0)
```

### Handle Connection Errors

```python
# Connection validation
result = connect_nodes(src_path, dst_path)

if result["status"] == "error":
    if "incompatible" in result["message"].lower():
        # Different node categories (e.g., SOP vs OBJ)
        print("Can't connect nodes of different types")
    elif "not found" in result["message"].lower():
        # Node doesn't exist
        print("Source or destination node not found")
```

### Debugging with Error Introspection

```python
# Use include_errors=True to diagnose issues
node_info = get_node_info(
    node_path,
    include_errors=True,
    force_cook=True
)

cook_info = node_info["cook_info"]

# Check for errors
if cook_info["errors"]:
    print(f"Node has {len(cook_info['errors'])} errors:")
    for error in cook_info["errors"]:
        print(f"  - {error['message']}")

# Check for warnings
if cook_info["warnings"]:
    print(f"Node has {len(cook_info['warnings'])} warnings:")
    for warning in cook_info["warnings"]:
        print(f"  - {warning['message']}")
```

## Example Workflows

Complete working examples are available in the `examples/` directory:

- **`build_from_scratch.py`** - Build sphere → xform → color → OUT from scratch
- **`augment_existing_scene.py`** - Insert mountain between grid → noise
- **`parameter_workflow.py`** - Discover → set → verify parameters
- **`error_handling.py`** - Detect → fix → verify errors

Run examples:

```bash
cd examples
python build_from_scratch.py
python augment_existing_scene.py
python parameter_workflow.py
python error_handling.py
```

## Usage Examples

### With Claude/Cursor

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "houdini": {
      "url": "http://localhost:3055"
    }
  }
}
```

### With Letta

Add as an MCP server in Letta's configuration to give agents Houdini control.

### Example Prompts

- "Create a sphere → transform → color → OUT network"
- "Insert a mountain node between the grid and noise"
- "Discover what parameters are available on the sphere node"
- "Check if the noise node has any cook errors"
- "Set the sphere radius to 3.0 using the parameter schema"

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt pytest

# Run tests
pytest tests/

# Run server locally
python -m houdini_mcp
```

## Troubleshooting

### Connection refused
- Verify Houdini is running with hrpyc server started
- Check firewall allows port 18811
- Verify HOUDINI_HOST is correct

### Authentication errors
- hrpyc uses no authentication by default
- Ensure you're on a trusted network
- The plugin refuses to bind a non-loopback address unless you explicitly opt
  in (`HOUDINI_RPC_TRUSTED_NETWORK=1`) or set a shared secret
  (`HOUDINI_RPC_TOKEN`). See [docs/remote-listener.md](docs/remote-listener.md)
  for the full security model and its limitations.

## Project Structure

```
houdini_mcp/
├── server.py              # FastMCP server with 43 tool wrappers
├── connection.py          # RPyC connection with retry/backoff
└── tools/                 # Modular tool implementations
    ├── _common.py         # Shared utilities, error handling
    ├── cache.py           # Node type caching with TTL
    ├── code.py            # Python/HScript execution
    ├── errors.py          # Error node detection
    ├── geometry.py        # Geometry introspection
    ├── help.py            # Houdini help access
    ├── hscript.py         # HScript command execution
    ├── layout.py          # Node layout tools
    ├── materials.py       # Material creation/assignment
    ├── nodes.py           # Node CRUD operations
    ├── pane_screenshot.py # Pane capture tools
    ├── parameters.py      # Parameter get/set
    ├── rendering.py       # Viewport/Karma rendering
    ├── scene.py           # Scene management
    ├── summarization.py   # AI response summarization
    └── wiring.py          # Node connection tools

houdini_plugin/            # Houdini plugin for stdio mode
├── python/houdini_mcp_plugin/
├── toolbar/               # Shelf tools
└── houdini_mcp.json       # Package descriptor

tests/                     # 418 tests (406 passing)
docs/                      # Implementation documentation
examples/                  # Working example scripts
```

## Credits

- Based on hrpyc integration patterns from [OpenWebUI Houdini Pipeline](https://github.com/oculairmedia/Houdinipipeline)
- Inspired by [capoomgit/houdini-mcp](https://github.com/capoomgit/houdini-mcp)

## License

MIT
