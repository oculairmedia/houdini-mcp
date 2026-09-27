# PM takeover: persistent Houdini companion

**Update after PM publication and Windows reconciliation:** Huly is deprecated by
explicit user instruction. Active tracking is Beads/Dolt. The Linux PM published
`houdini-mcp-vzp.13`–`.21` to Dolt `origin/main`; Windows now has a working clone.
Read [Windows operation](../../windows-beads.md),
[reconciliation evidence](windows-reconciliation.json) and the
[GitHub↔Beads delivery mapping](delivery-crosswalk.json) before the dated snapshot
below. Earlier Huly requirements and statements that the beads are unpublished
are superseded. Linux PM Beads is 1.2.2; verified Windows Beads is 1.1.0.

**Remote PM entry point:** This committed packet is self-contained for project-management intake. Windows paths below identify the artist's host; they are not expected to exist on the PM's machine. Use the adjacent JSON exports and benchmark records for reconciliation. Live renders and the unsaved scene remain on the artist's host. The implementation snapshot is commit `4efb723`; this packet is a later documentation-only commit.

- [Proposed Beads intake](beads-intake.json)
- [Completed GitHub issues](github-delivered-issues.json)
- [Historical Beads snapshot](historical-beads-snapshot.json)
- [Observed runtime and operation schemas](runtime-snapshot.json)
- [Temporal verification evidence](live-temporal-2026-09-27.json)
- [Earlier iteration evidence](live-iteration-2026-09-27.json)

These are dated snapshots, not a replacement for the authoritative project systems. No authentication descriptor or token is included.

Prepared 2026-09-27 for **Huly - Houdini MCP Server**, project **HDMCP**, Letta agent `agent-0a0867cb-09a4-4a9d-ad97-884773b7cbbc`.

## Takeover mandate

Take over project management: reconcile the existing Huly/Beads roadmap, backfill the work shipped on the companion spike, create dependency-linked follow-ups, and restore durable tracking. This handoff is evidence and an intake proposal, not a claim that Beads/Huly have already been updated.

Emmanuel wants an agent-native Houdini experience: fast programmatic access, compact discoverable interfaces, reliable rendered feedback, modular plugins over a strong core, and performance tests that catch regressions. Each implementation wave must use its own tools to improve the real scene, record shortcomings, fix them, and verify again. A compile or successful job alone does not demonstrate geometry or artistic quality. Current Windows/Houdini 20.5 comes first; keep the architecture extensible.

The reference command workflow is [renezander030/blender-cli](https://github.com/renezander030/blender-cli), with [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent) also reviewed. Scoped discovery, recipes, job continuation and rendered evidence informed the implementation. Their code was not vendored. The resulting architecture remains a persistent embedded Houdini companion, with both CLI and MCP adapters.

## Verified checkout and running configuration

| Item | Current value |
| --- | --- |
| Repository | `https://github.com/oculairmedia/houdini-mcp` |
| Windows checkout | `C:\houdini mcp\g` (parent `C:\houdini mcp` is not the repo root) |
| Branch | `spike/persistent-houdini-companion` |
| HEAD, pushed and matched to origin | `4efb7232859378d106e7375075cb366d25b5078c` |
| Python outside Houdini | `.venv\Scripts\python.exe`, 3.12.1 |
| CLI | `.venv\Scripts\houdini-agent.exe` |
| Live application | Houdini 20.5.278, embedded Python 3.11, PID 314936 |
| Companion | Authenticated HTTP on `127.0.0.1:18812`, Houdini `hwebserver` |
| Legacy bootstrap bridge | `hrpyc` on 18811; RPyC must stay 5.x, not 6.x |
| Session ID | `5180bafc38524ee6ac827871de525c5e` |
| Scene ID | `bd23d988c56e4b6f928301150db2571d` |
| Companion data | `C:\Users\Emmanuel\.houdini-companion` |
| Descriptor | `sessions\314936.json` under that directory; contains a secret token, do not publish it |
| Installed Houdini package | `C:\Users\Emmanuel\houdini20.5\packages\houdini_companion.json` |
| Package paths | Prepends `C:/houdini mcp/g` to PYTHONPATH; hpath `C:/houdini mcp/g/houdini_plugin` |
| HIP path | `E:/PROJECTS/houdini building generator/building generator.hip` |
| Live health at handoff | Accepting, no active job, no queued jobs |
| Live time at handoff | Frame **194**, 24 FPS, frame/playback ranges 1–240, stopped |

The artist has moved the timeline since the last verification, which restored frame 61. Do not reset it to the older evidence snapshot. The session IDs, PID and frame are observations, not deployment constants. Rediscover them through the client.

The running companion was updated in place during the spike to preserve the artist session and restore handles. Core methods and plugin registries were refreshed without restarting Houdini. This validates the current live workflow; it is not evidence that the latest code has passed a fresh application restart. The package is installed for startup, but an end-to-end next-launch test remains a follow-up when the artist has saved and a restart is appropriate.

Environment controls: `HOUDINI_COMPANION_HOME`, `HOUDINI_COMPANION_PORT`, `HOUDINI_COMPANION_AUTOSTART=0`, and `HOUDINI_COMPANION_PLUGINS` (explicit comma-separated module list). MCP may select a PID with `HOUDINI_COMPANION_PID`. `HOUDINI_BACKEND=companion` opts supported legacy tool mappings into the companion; it is not necessary for the dedicated companion tools, and the MCP process environment was not reconfigured in this handoff.

## Shipped architecture and interfaces

Read `AGENTS.md`, `README.md`, and `docs/adr/0001-language-and-process-boundaries.md` in the repository. ADR 0001 retains Python for HOM semantics and the FastMCP gateway. No general rewrite or non-Python sidecar is authorized without its profiling threshold and a follow-up decision. The local companion is not the historical hosted WSS gateway.

| Layer | Responsibility |
| --- | --- |
| `houdini_companion/core.py`, `runtime.py`, `schema.py` | Versioned jobs, identity, queue, deduplication, cancellation, retention, UI dispatch and contract validation |
| `registry.py`, `plugins/` | Explicit Plugin API v1 manifests, dependencies, effects, schemas and operation handlers |
| `client.py`, `cli.py`, `agent_output.py` | Discovery, submission, bounded waits, JSON recipes and compact agent output |
| `observation.py`, `transactions.py` | Staleness guards and recoverable scene edits |
| `rendering.py`, `diagnostics.py`, `temporal.py` | Evidence rendering, native full geometry audit, topology/semantic hashes and bulk motion analysis |
| `houdini_mcp/companion_tools.py` | MCP adapter to the same companion operation surface |
| `houdini_plugin/` | Houdini installation, startup and panel integration |

Plugin API: `plugin() -> PluginSpec`; operations use `OperationSpec(name, effect, schema, handler, description)`. Handlers receive `(context, job, **params)`. The context supplies `hou`, `ledger`, namespaced scene state and composition via `call`. All HOM work runs on the Houdini UI thread. Worker threads must not retain HOM objects. Plugins are trusted Python, not sandboxed code. Explicit configuration is required; installed packages are not automatically enabled. Collision, dependency and schema errors fail registration. Results must be finite JSON objects, at most 4 MiB; larger content belongs in artifacts.

There are **nine active built-in plugins and 26 operations**. Query, scene, review, execution, introspection and acceptance are v0.2.0; iteration is v0.3.0; animation and timeline are v0.1.0. `runtime-snapshot.json` contains the complete observed catalog and parameter contracts.

- Introspection: `inspect`, `validate_observation`, `query.batch`, `query.graph`, `query.parameters`, `query.node_types`, `query.geometry`.
- Scene edits: `batch`, `undo`; batch supports aliases, create/set/connect/flags/delete and observation guards.
- Review: `snapshot`, `preview`, `apply_preview`, `discard_preview`, `review.accept`, `review.compare`.
- Iteration: `iteration.capture`, `.stage`, `.apply`, `.restore`, `.release`; supports external quoted VEX includes and inline snippets.
- Animation: `animation.control`, `.keyframes`, `.restore`.
- Time: `timeline.inspect`, `.sample`.
- Escape hatch: `execute`, explicitly trusted and without atomic rollback guarantees.

MCP tools include `companion_schema`, `companion_status`, `companion_inspect`, `companion_submit`, `companion_job`, `companion_cancel`, `companion_events`, `companion_feedback`. Schema discovery and dispatch share the same registry. Feedback returns native MCP images.

Operational contracts to preserve:

- Guards detect scene/source/channel changes; observe again after artist edits. Keyframe content and FPS affect observations.
- Identical request ID and payload deduplicate. Changed payloads under the same ID are rejected. Never resubmit a mutation merely because a wait timed out.
- Cancellation is cooperative at phase boundaries; it does not forcibly interrupt a running HOM cook.
- New clients negotiate bounded existing-job waits, using two wait slots; old runtimes get polling backoff.
- A succeeded job can contain `accepted: false`. Check acceptance as well as transport/job success. CLI rejected acceptance exits nonzero.
- Animation supports scalar numeric channels with linear/constant keys. It preserves original keys, extrapolation and constant values for guarded session restoration. Journals support recovery; this is not crash-atomic recovery.
- Temporal review accepts 2–32 explicit frames, fractional/repeated samples, up to three views and 32 million rendered pixels. It evaluates with `geometryAtFrame`, records timings and checks, and restores the original time/playback state.
- Native polygon audits check all point positions and closed polygons, including zero area and point-normal alignment. They do not prove watertightness or self-intersection freedom.
- Time comparison assumes stable point ordering. Known DOP/solver inputs are rejected; arbitrary stateful simulation is not supported without a cache/preroll contract.
- Capture/stage freezes inputs at the captured time. Applying a candidate then doing temporal review works; pre-apply multi-frame candidate acceptance is not yet a unified transaction.
- Retention targets 64 recent artifact jobs / about 1 GiB, with active work and restore-related exceptions. Archived sessions and persistent source revisions need deliberate retention management.

## Delivery history and Beads backfill

Four pushed implementation milestones:

| Commit | Delivered work | PM disposition |
| --- | --- | --- |
| `10cfd38` | Persistent companion, job/session protocol, CLI/MCP adapters, installation and review foundations | Reconcile against existing companion/protocol roadmap; backfill completed evidence |
| `71ff0e7` | Modular plugins, programmatic queries/review and performance gates | Backfill completed foundation milestone |
| `1f9153b` | Guarded capture/stage/apply/restore, native audits, immutable VEX revision reuse and paired framing | GitHub #19–29 closed |
| `4efb723` | Agent CLI, temporal sampling, typed animation, bounded waits and inline iteration | GitHub #30–37 closed |

All issue links below are under `https://github.com/oculairmedia/houdini-mcp/issues/`. Full issue titles, bodies and closure state are exported in `github-delivered-issues.json`. Import or reconcile them as **completed work**, not as a fresh implementation backlog.

| GitHub | Delivered scope |
| --- | --- |
| #19 | Reusable guarded capture, stage, compare, apply and restore |
| #20 | Coordinated recovery of scene and external source edits |
| #21 | Fast complete native audits for large geometry |
| #22 | Better review detail and depth precision |
| #23 | Distinguish cached access from regeneration timing |
| #24 | Repeatable live iteration and performance gates |
| #25 | Preserve sibling display/render flags during staging |
| #26 | Reuse immutable staged VEX sources on identical retries |
| #27 | Ignore bgeo serialization timestamps in equivalence checks |
| #28 | Promote reviewed VEX without recompiling identical code |
| #29 | Fit cameras to projected geometry; freeze paired framing |
| #30 | Scoped CLI schemas, stdin recipes, compact actionable receipts |
| #31 | Explicit time context and frame-safe geometry sampling |
| #32 | Guarded typed keyframe batches and restoration |
| #33 | Fixed-camera sequence evidence and motion gates |
| #34 | Live town animation layer and street/park normal fixes |
| #35 | Refresh stale VEX channel bindings when controls are added |
| #36 | Bounded job continuation and accurate live discovery |
| #37 | Inline VEX candidates in the guarded iteration workflow |

Issue #34 is **live-scene implementation complete**, with its evidence committed. Town source files and the HIP were not committed/saved by the agent. Do not infer that the scene is portable from a clean checkout.

## Tracking repair and existing IDs

This session still has no callable Huly, Matrix/Letta, Graphiti or BookStack connectors. The user reports the PM is available again; use the PM's own integrations. No PM message or external project-system update has been sent by this handoff.

Local `bd` is **1.1.0 (8e4e59d39)**. `bd where` resolves `C:\houdini mcp\g\.beads`. `bd ready` fails with **no beads database found**. `bd sync` is **not a supported command** in this installed version, although AGENTS/config instructions expect it. `.beads/metadata.json` points at `beads.db`, which is absent. There are **62 historical records** in `issues.jsonl`, plus `interactions.jsonl` and legacy configuration. No new DB was initialized and those files were not rewritten.

The PM should identify the authoritative remote database/version/sync mechanism, reconcile it with this checkout, and update stale operational instructions. Do not blindly run `bd init`, overwrite history, or create another parallel source of truth.

Important reconciliation candidates:

| Existing reference | Caution |
| --- | --- |
| `houdini-mcp-vzp`, `.9`, `.10`, `.11` | ADR references the reliability epic, companion protocol, ADR and telemetry. These IDs are absent from this local 62-record export; fetch authoritative PM state before creating replacements. |
| `houdini-mcp-vzp.2` | Existing recoverable transaction foundation appears in pre-spike commit `7e5cd7a`; avoid duplicate foundational work. |
| `houdini-mcp-xu4` / HDMCP-76 | Historical hosted WebSocket client; local companion HTTP does not satisfy the hosted WSS deployment contract. |
| `houdini-mcp-6pt` / HDMCP-71; `houdini-mcp-9sx` / HDMCP-72 | Hosted gateway/plugin roadmap remains a separate scope. |
| `houdini-mcp-38o` and `houdini-mcp-crr` / HDMCP-25 | Duplicate historical multi-view entries. Existing companion views overlap some needs; assess exact acceptance criteria. |
| `houdini-mcp-2t6` and `houdini-mcp-fr0` / HDMCP-52 | Duplicate historical pagination/size-limit entries. |
| `houdini-mcp-9e2` and `houdini-mcp-b4z` / HDMCP-11 | Duplicate historical execute safety entries; companion trusted execution is not a sandbox. |
| `houdini-mcp-00p` and `houdini-mcp-d2j` / HDMCP-23 | Duplicate historical remote/hrpyc activation entries. |
| `houdini-mcp-48x` and `houdini-mcp-e6s` / HDMCP-35 | Duplicate historical wiring extraction entries. |
| `houdini-mcp-16w` / HDMCP-16 | Export says open, but git has completed compact-list-children commit `e2a71f8` / PR #15. Export is not current truth. |

`historical-beads-snapshot.json` preserves the records for comparison. Titles or old statuses alone are insufficient grounds to close/reopen an item.

## Verification and observed performance

- Full local suite: **755 passed, 12 skipped**, using `python -X utf8 -m pytest -q`. The skipped legacy live integration tests are separate from the explicitly executed companion live fixture. Default Windows cp1252 causes four existing documentation tests to fail; UTF-8 matches CI.
- Ruff passed for companion code, new tests and fixture.
- [Windows/Linux companion CI passed for HEAD](https://github.com/oculairmedia/houdini-mcp/actions/runs/36348413962). CI is portable contract/performance testing on Python 3.11; it does not run real Houdini.
- `scripts/verify_companion_temporal.py` passed live: typed keys, restoring already-keyed and constant channels, fractional/repeated frames, static-motion rejection, and late-created control bindings. It removes only its own fixture nodes. No fixture nodes remained.
- Whole-town review: **31 frames**, **711,408 points / 179,466 polygons per frame**, zero nonfinite points, zero zero-area polygons, zero normal mismatches. Stable topology and motion passed. Separate five-frame review and disposable fixture cover repeated/fractional samples.
- Four cars and three streetcars pass 31 sampled vehicle-AABB separation/stop-clearance checks; maximum rigid translation error `7.629e-06`. Static street/building generator cook deltas: zero during motion QA.
- Street animation layer cooks about **1.75–2.64 ms** in its eight-frame review; whole town median **46.98 ms** in the final 31-frame review. These are different scopes, not interchangeable performance claims.
- Whole 31-frame evidence job took **45.3 s**, including frozen geometry, audit and rendering; **46 transport requests** (one submit, one lookup, 44 waits).
- Scoped timeline discovery: **820 bytes**, full catalog **14,135 bytes**.
- Portable median: **6.82 ms per 1,000 empty dispatches**, **16.25 ms** per million-point position audit, **30.93 ms** per million-point motion comparison. Motion CI ceiling: **250 ms**. Dispatch number is a batch of 1,000 calls, not per-call latency.
- Prior same-frozen-geometry audit comparison measured about **73x** speedup. Do not compare unrelated scene sizes as if they were a controlled benchmark.

Committed evidence: `benchmarks/live-temporal-2026-09-27.json` and `benchmarks/live-iteration-2026-09-27.json`. These contain scopes and limitations. The final full-town film preceded the small orphan-point-count topology-hash hardening; that change passed its targeted portable test and the latest live fixture, not another full 31-frame film.

Rejected attempts are useful acceptance evidence: reversing Houdini's correct clockwise card winding produced 5,543 normal mismatches and was rejected; stale missing-channel compilation produced `NO_MOTION` despite authored keys; whole-town review exposed 108 park normal mismatches that street-only review missed. The fixes were verified through the new tooling.

## Live scene and uncommitted work

Do not save the HIP, commit town source, rebuild the town, restart Houdini or overwrite artist cameras as a project-management action. Existing authorization permits tooling commits/pushes and reversible scene work; artist file persistence remains under the user's control.

Preserve `/obj/town_cam`, `/obj/town_street_cam`, `/obj/town_wire_cam`, `/obj/town_oblique_cam`. Never run the stale `%TEMP%\build_town.py`; it rebuilds the network and replaces current code. Old temp VEX exports are not canonical source.

Modified tracked files left local: `town/building.cga.h`, `town/street_life.h`. The building changes include prior user-authorized work and were not replaced in the latest animation wave. Untracked scene scripts: `apply_scene_quality.py`, `render_building_review.py`, `render_scene_quality.py`, `run_live.py`, `scene_quality_review.py`, `verify_animated_town.py`, `verify_buildings.py`, `verify_live_town.py`, all under `town/`. Preserve them; they were intentionally excluded from tooling commits.

Latest live topology: `/obj/town/road_generator/STREET_LIFE` feeds `/obj/town/road_generator/ANIMATE_STREET_LIFE`, which feeds input 2 of `OUT_ROADS`. The animation wrangle is point class. Float `progress` has linear keys `(1,0)`, `(217,1)`, `(240,1)`, with per-entity delay and smoothstep easing in VEX. Point attributes `motion_id`, `motion_kind`, `motion_delta`, `motion_delay` isolate moving pieces. Four cars and three streetcars approach stops and hold. This is **not** a seamless loop, intersection scheduler or traffic physics simulation.

Street trees had 96 normal mismatches corrected. Inline park cone code in `/obj/town/road_generator/GENERATE_STREETS` had another 108 corrected through inline capture/stage/apply. That park change is in the live node and recovery artifacts, not a committed source header. Immutable reviewed VEX revisions can be referenced by live snippets; never delete their cache simply because the canonical header exists. Cross-machine scene portability is not yet established.

Prior verification controls: streets 4, block size 55.9, road 6.74, main road 11.19, sidewalk 2.86, corner clearance 9.92, lot spacing 8.99, seed 1139, max floors 7. Treat these as evidence, not commands to override later artist edits.

Evidence directory: `C:\Users\Emmanuel\.houdini-companion\time-spike` contains `town-traffic.mp4`, `town-traffic.gif`, `fixture.json`, `town-motion-acceptance.json`, `film-job.json`, `wait-measurement.json`, source candidates and recipes.

Artifact root: `C:\Users\Emmanuel\.houdini-companion\artifacts\c2cc4d2118ce4b0890939a518f49afa3`. Its ID intentionally differs from the current session ID because the runtime was refreshed while retaining earlier evidence.

Useful handles, subject to current session validity:

| Purpose | ID |
| --- | --- |
| Final 31-frame film | `6e58ecc08bc6418d9171f481e8204e84` (`sequence.json`, images and bgeo under artifact root) |
| Town animation restore receipt | `da4e59728b99455189a24979a683d086` |
| Final street include capture / stage / apply | `34e04374f7e442a4adafbf4d5482e9ca` / `eaf16406bb0349bbaa772250a2897ebf` / `42cd8955b0cc46f888a1a7b2e0c980aa` |
| Park inline capture / stage / apply | `e770778dd22f449f8bbe148d1f0531e8` / `1a9dad19196146f983beafe989eac2ff` / `9734792ea1d343d48b98b129634d3aae` |

Do not invoke restoration or release handles during intake. Restore eligibility depends on subsequent edits and scene/session identity.

## Proposed next Beads, with acceptance and dependencies

These are **recommended follow-ups**, not newly discovered production failures or automatically approved expansion. Local IDs below are intake labels, not actual Beads IDs. Reuse existing authoritative items whenever possible.

| Intake | Priority | Work and acceptance | Dependency |
| --- | --- | --- | --- |
| PM-01 | P1 | Reconcile tracking/version mismatch. Identify authoritative DB and supported sync workflow; preserve 62 historical records; resolve duplicates; demonstrate usable `bd ready`; document the correct workflow. | None |
| PM-02 | P1 | Backfill shipped work. Map four milestones and GitHub #19–37 to Beads/Huly, with commit/evidence links and completed status. Separate live scene completion from source/HIP release. Return a GitHub↔Beads↔Huly mapping. | PM-01 |
| ENG-01 | P1 | Restart/install acceptance on a disposable or artist-approved saved scene. Verify autostart, catalog parity, descriptor discovery, stale-session rejection, archived job access and no mutation replay. Attach results without restarting the unsaved artist scene. | Existing companion foundation; coordinate artist state |
| ENG-02 | P1 | Portable scene/source packaging. Inventory cached include references and inline park code; define export/relink that preserves exact reviewed bytes. Verify identical geometry after reopen on an isolated copied scene. Saving/committing artist content requires its own authorization. | PM-02; source inventory |
| ENG-03 | P1 | Recovery/retention hardening. Fault-inject partial channel restore, journal write failure, restart with pending work and artifact pruning; make partial recovery state explicit and preserve referenced sources. Do not promise crash atomicity without proving it. | PM-02 |
| ENG-04 | P2 | Unified pre-apply temporal candidate review. Sample staged candidate over explicit frames with frozen paired cameras, reject invalid/motionless/nondeterministic cases, leave live source unchanged on rejection, and apply the exact accepted revision. | Current iteration + timeline plugins |
| ENG-05 | P2 | Fresh-process plugin lifecycle test matrix. Test explicit external plugin loading, dependency failures, CLI/MCP catalog agreement and compatible upgrades on the current Houdini version first. Extend versions/machines only after a working local gate. | ENG-01 |
| ENG-06 | P2 | Agent iteration scorecard. Track discovery/output bytes, request count, queue/evaluation/audit/render time and useful evidence per completed edit-review cycle; add comparable-host regression gates. Preserve current million-point and dispatch tests. | Existing benchmark harness |
| SCENE-01 | P2, optional | Next motion/art wave. If prioritized, implement continuous traffic or another animated element with explicit loop/range behavior, semantic entity identity and stronger motion-clearance tests. Keep static generator costs separate. Do not describe current stop motion as an unfinished promise of traffic simulation. | ENG-04 recommended; artistic scope decision |

Stateful simulation/cache/preroll, hosted WSS, multi-tenant isolation and non-Python sidecars remain separate roadmap decisions. Do not silently roll them into the current local spike.

## PM's first actions and definition of a successful takeover

1. Read this packet and authoritative Huly/Letta/BookStack state. Reconcile `houdini-mcp-vzp` and historical mappings before creating an epic.
2. Restore the supported tracking workflow; do not replace history with a blank local database.
3. Backfill completed milestones and GitHub issues, preserving their implementation/evidence links and the live-only scene caveat.
4. Create or update the prioritized follow-ups above with owners, dependencies, acceptance criteria and explicit persistence/restart constraints. A suitable epic title, if one does not already exist, is **Agent-native Houdini companion: reliable edit/review/animate workflow**.
5. Publish the authoritative roadmap in BookStack using its connector. `docs/bookstack/` is a read-only mirror. This local handoff is a transfer packet, not a replacement design source of truth.
6. Return to Emmanuel a concrete mapping of Beads/Huly IDs, completed vs open work, dependency order and the next ready implementation task. Store the key configuration in Graphiti and report through the PM's normal Matrix/Letta channel.

Minimal read-only operator check from PowerShell:

```powershell
Set-Location 'C:\houdini mcp\g'
.venv\Scripts\houdini-agent.exe doctor
.venv\Scripts\houdini-agent.exe schema --live --command 'timeline.*' --compact
.venv\Scripts\houdini-agent.exe time inspect --wait 1 --compact
git status --short --branch
```

When development resumes, use full operation discovery only as needed, obtain current observation tokens, stage source changes, inspect rendered evidence, check acceptance, and continue existing jobs by ID. The next engineer should be able to start from the pushed spike and this packet without repeating the architectural exploration or losing the artist's live work.
