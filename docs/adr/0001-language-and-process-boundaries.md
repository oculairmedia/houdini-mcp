# ADR 0001: Language and Process Boundaries for Houdini MCP

- **Status:** Accepted
- **Date:** 2026-07-10
- **Bead:** `houdini-mcp-vzp.10`
- **Epic:** `houdini-mcp-vzp` — Houdini MCP reliability + agentic production workflow roadmap
- **Deciders:** Houdini MCP maintainers (reviewed before companion-protocol implementation)
- **Supersedes:** none
- **Blocks:** `houdini-mcp-vzp.9`, `houdini-mcp-vzp.11`, `houdini-mcp-xu4`

<!-- ADR-BOUNDARY-ANCHOR: do not remove. The docs-link lint (tests/test_docs_links.py)
     asserts this file, its README/AGENTS links, and the "Module Boundaries" section
     all exist. Removing them fails CI. -->

## Context

The Houdini MCP server exposes ~43 MCP tools that drive SideFX Houdini over
`hrpyc` (Houdini's bundled RPyC classic server). Reliability work is about to
proliferate: a Houdini-side companion process with a secure event channel
(`houdini-mcp-vzp.9`), a resilient WebSocket client (`houdini-mcp-xu4`), and
structured telemetry with performance budgets (`houdini-mcp-vzp.11`). Before we
add processes and, potentially, new languages, we must record **which language
runs where** and **what evidence would justify introducing a non-Python
component**.

Two facts constrain the decision:

1. **`hou` is Python-native.** SideFX supports automation through the `hou`
   Python module. `hrpyc`/RPyC hands back **live Python proxy objects** (nodes,
   parms, geometry) whose semantics only exist inside Houdini's embedded
   interpreter. Any non-Python component that tried to reimplement node/geometry
   semantics would be duplicating an API SideFX owns and changes every release.
2. **The FastMCP gateway is Python.** The MCP tool surface, schemas, error
   handling, and tests are all Python today (`houdini_mcp/`), and the hosted
   roadmap (`docs/hosted-service-planning.md`) already assumes a Python
   FastAPI/`websockets` gateway.

The question is therefore **not** "rewrite or not" but "where are the process and
language boundaries, and under what measured conditions do we add a sidecar?"

## Decision

**Retain Python for both `hou` semantics and the FastMCP gateway now.** Introduce
a non-Python sidecar **only** when profiling or a concrete security/isolation
requirement crosses an explicit threshold defined in this ADR, and only behind a
**versioned, language-neutral protocol**. A sidecar must never duplicate
`hou`/node/geometry semantics — those stay in the Python component that talks to
Houdini.

This bead authorizes **no rewrite**. Any future non-Python component requires a
follow-up bead backed by the measurements described here.

## Options Considered

Five architectures were evaluated. Each is scored below across eight dimensions.

### Option A — Python-only (current)

A single Python process runs FastMCP and talks to Houdini over `hrpyc`. This is
what ships today (`houdini_mcp/server.py`, `houdini_mcp/connection.py`,
`houdini_mcp/tools/`).

### Option B — Embedded Python + external Python

Two Python processes with a clear boundary: a Houdini-embedded companion
(`hython`, `houdini_plugin/`) that owns all `hou` access and event streaming, and
an external Python gateway (FastMCP) that owns MCP transport, schemas, and
session routing. They communicate over a versioned protocol (WebSocket/JSON or
msgpack), *not* raw RPyC proxy passing. This is the direction `houdini-mcp-vzp.9`
and `houdini-mcp-xu4` already imply.

### Option C — Python + Rust/Go sidecar

Options A or B, plus a compiled sidecar for narrow, hot, language-neutral jobs:
artifact/screenshot streaming, WebSocket termination for many hosted sessions,
process supervision/sandboxing. The sidecar never touches `hou`; it moves bytes
and enforces isolation.

### Option D — TypeScript gateway

Replace the Python FastMCP gateway with a TypeScript MCP server (the reference
MCP SDK is TS-first), keeping a Python Houdini-side worker. Adds a language
boundary at the busiest layer.

### Option E — C++ HDK plugin

Implement Houdini-side logic as a native HDK plugin instead of Python, exposing a
custom protocol. Maximum in-process fidelity to Houdini internals, maximum cost.

## Comparison Matrix

Legend: ✅ strong · 🟨 acceptable/mixed · ⚠️ weak · ❌ disqualifying.

| Dimension | A: Python-only | B: Embedded+External Py | C: +Rust/Go sidecar | D: TS gateway | E: C++ HDK |
|---|---|---|---|---|---|
| **API fidelity** (`hou`) | ✅ native `hou`, exact proxy semantics | ✅ native `hou` on Houdini side | ✅ (Py keeps `hou`) | 🟨 Py worker keeps `hou`; TS can't touch it | ✅ deepest access, but reimplements automation SideFX ships in Python |
| **Debugging** | ✅ one stack, `pdb`, tracebacks | 🟨 two Py stacks, correlate via request id | ⚠️ cross-language, two toolchains | ⚠️ Py+TS stacks, source maps | ❌ gdb + Houdini symbols, slow cycle |
| **Deployment** | ✅ one image, existing `Dockerfile`/`compose.yaml` | 🟨 two artifacts (plugin + server) | ⚠️ compiled binary per platform + Py | 🟨 Node + Py runtimes | ❌ compile per Houdini version/OS/ABI |
| **Concurrency** | 🟨 GIL + RPyC sync calls; async at MCP edge | ✅ isolate blocking `hou` behind async boundary | ✅ true parallel byte-moving/WS fan-out | ✅ Node event loop for many conns | 🟨 native threads, but Houdini APIs mostly single-threaded |
| **Performance** | 🟨 fine for control-plane; RPyC round-trips add latency | 🟨 same `hou` cost; protocol adds a hop | ✅ best for artifact throughput/fan-out | 🟨 marshalling parity with Py at gateway | ✅ in-proc, no RPC — but only for HDK-expressible work |
| **Security/isolation** | ⚠️ `execute_code` = arbitrary code in one process | 🟨 can sandbox gateway from Houdini host | ✅ sidecar can supervise/sandbox worker | 🟨 similar to A/B at gateway | ⚠️ native crashes take down Houdini |
| **Testability** | ✅ 400+ pytest, unit+integration, mocked `hou` | ✅ each side unit-testable; contract tests on protocol | 🟨 need cross-lang contract + fuzz tests | 🟨 two test stacks | ⚠️ needs Houdini in CI, hard to mock |
| **Team/ecosystem fit** | ✅ codebase, CI, skills all Python | ✅ still all-Python | ⚠️ new toolchain to own | ⚠️ split expertise | ❌ specialist skill, slow hiring |

### Reading of the matrix

- **A** is the correct default: it maximizes API fidelity, debuggability,
  deployment simplicity, and testability, which are the dimensions that dominate
  a control-plane MCP server.
- **B** is the natural *next* step for reliability (isolating blocking `hou`
  calls, event streaming) **without** adding a language. It is pre-approved as an
  evolution because it stays in Python and only formalizes a protocol boundary
  that `vzp.9`/`xu4` need anyway.
- **C** is justified only for **byte-moving and isolation** jobs that profiling
  shows are hot, and only behind the same versioned protocol. It must never own
  `hou` semantics.
- **D** trades our strongest asset (one Python stack around `hou`) for MCP-SDK
  ergonomics we already get from FastMCP. Rejected now.
- **E** is disqualified for general use: it reimplements automation SideFX ships
  in Python, needs Houdini in CI, and couples crashes to the host. Revisit only
  for a specific in-proc capability `hou` cannot express.

## Profiling Baseline

We cannot authorize a non-Python component on intuition. This section defines a
**baseline** we measure before and after each reliability change. Values below
marked *(profile plan)* are not yet measured on this hardware and are the
protocol to fill in; values marked *(observed)* are rough envelopes seen in
current local/dev usage and should be re-measured with the harness before being
cited in a follow-up bead. **A follow-up that proposes Option C/D/E MUST attach a
run of this harness.**

### What to measure

| Metric | Definition | Baseline (current) | How to capture |
|---|---|---|---|
| **Tool-call latency (control)** | Wall time for a light tool (`get_scene_info`, `find_nodes`) start→result | ~20–80 ms *(observed)* | `pytest-benchmark` around the tool fn with a mocked/real conn; `.benchmarks/` |
| **hrpyc serialization** | Time + bytes to marshal an RPyC result across the boundary (per node / per parm / per geo blob) | dominated by round-trips, ~1–10 ms per proxy touch *(profile plan)* | wrap `connection` calls with timing; count RPyC round-trips |
| **Screenshots / artifacts** | End-to-end for `capture_pane_screenshot` / `render_viewport` incl. PNG transfer | ~200 ms–2 s depending on resolution *(profile plan)* | time the tool; record payload size at the MCP edge |
| **Geometry summaries** | `get_geo_summary` on small (<10k pts) and large (>1M pts) geometry | small: tens of ms; large: hundreds of ms–seconds *(profile plan)* | benchmark with sampling on/off; record round-trips |
| **Concurrent sessions** | Throughput / p95 latency as N MCP sessions drive one gateway | 1 session validated; N unmeasured *(profile plan)* | load script issuing parallel tool calls; record p50/p95/p99 + error rate |

### Harness

- Add `pytest-benchmark` cases under `tests/` (guarded so they no-op without a
  live Houdini) that emit JSON into `.benchmarks/`.
- A separate load script (out of scope for this bead) drives concurrent sessions
  and records p50/p95/p99 latency, error rate, and CPU/RSS of the gateway.
- Capture **payload sizes** at the MCP edge (screenshots, geo summaries) because
  artifact throughput — not `hou` CPU — is the most likely trigger for a sidecar.

## Thresholds That Justify a Non-Python Component

A sidecar (Option C) or a language change (D/E) becomes *evaluable* only when a
measured threshold is crossed **and** it is attributable to the gateway/transport
layer rather than to Houdini itself (adding a language cannot speed up `hou`).

| Trigger | Threshold | Candidate response | Ruled out |
|---|---|---|---|
| Artifact throughput | Screenshot/render transfer > **200 MB/min sustained** OR gateway CPU >70% spent on (de)serialization/IO for artifacts | Rust/Go sidecar for artifact streaming behind versioned protocol (Option C) | Rewriting `hou` access |
| Concurrent-session fan-out | p95 tool-call latency degrades **>2×** vs single-session at ≥ **50 concurrent sessions**, and profiling attributes it to Python WS/event-loop handling (not RPyC/`hou`) | Compiled WS-termination sidecar OR horizontal Python scaling first | TS gateway rewrite |
| Blocking-call starvation | Async event-loop stalls > **250 ms p95** caused by synchronous `hou`/RPyC work despite offloading to threads | Option B process split (still Python) before any sidecar | — |
| Security/isolation | A concrete requirement to sandbox `execute_code` / supervise the Houdini worker as a separate trust domain (e.g. hosted multi-tenant) | Supervisor/sandbox sidecar (Option C) owning process lifecycle only | Reimplementing tools |
| Protocol at the edge | An MCP transport feature is materially better in the TS SDK and cannot be met by FastMCP | Re-open Option D with a spike + benchmark | Speculative migration |

If a trigger fires but profiling attributes the cost to Houdini/`hou`/RPyC
round-trips, the answer is **batching, caching, and fewer round-trips in
Python** — not a new language.

## Module Boundaries

<!-- ADR-BOUNDARY-SECTION: the docs-link lint asserts this heading exists. -->

The system is layered. **Dependencies point downward only**; lower layers must
not import from or know about higher layers.

```
        ┌──────────────────────────────────────────────┐
  L4    │  MCP clients (Claude, Cursor, Letta agents)  │
        └───────────────────────┬──────────────────────┘
                                 │ MCP over HTTP/stdio/SSE
        ┌───────────────────────▼──────────────────────┐
  L3    │  Gateway (Python/FastMCP)                     │
        │  houdini_mcp/server.py  — tool registration   │
        │  schemas, response sizing, summarization      │
        └───────────────────────┬──────────────────────┘
                                 │ in-process function calls
        ┌───────────────────────▼──────────────────────┐
  L2    │  Tool implementations (Python)                │
        │  houdini_mcp/tools/*.py                        │
        │  own MCP-facing semantics, NOT transport       │
        └───────────────────────┬──────────────────────┘
                                 │ connection API only
        ┌───────────────────────▼──────────────────────┐
  L1    │  Connection / transport (Python)              │
        │  houdini_mcp/connection.py — RPyC, retry,      │
        │  backoff, timeouts. The ONLY layer that        │
        │  touches the wire to Houdini.                  │
        └───────────────────────┬──────────────────────┘
                                 │ hrpyc / RPyC (proxy objects)
        ┌───────────────────────▼──────────────────────┐
  L0    │  Houdini + hou (Python, in Houdini process)   │
        │  houdini_plugin/ (embedded), authoritative     │
        │  source of node/geometry/parm semantics        │
        └──────────────────────────────────────────────┘
```

### Allowed dependency direction

- `server.py` (L3) → `tools/*` (L2) → `connection.py` (L1) → Houdini/`hou` (L0).
- `tools/*` may use `tools/_common.py` and `tools/cache.py` but **must not**
  import `server.py`.
- `connection.py` **must not** import `tools/*` or `server.py`.
- No layer reimplements a layer below it. In particular, **only L0 defines
  `hou`/node/geometry semantics**; L1–L3 pass through, shape, and size responses.

### Rules for any future sidecar (Option C) or split (Option B)

1. It attaches **only at L1 (transport) or below L3 (edge)** — never inside L2
   tool semantics.
2. It communicates over a **versioned, language-neutral protocol** (explicit
   schema + version field), not by passing RPyC proxies across a language
   boundary.
3. It **may not** import, embed, or reimplement `hou`. If a job needs `hou`, it
   belongs in the Python worker at L0/L1.
4. It owns exactly one of: **byte transport**, **WS session fan-out**, or
   **process supervision/sandboxing** — not tool logic.
5. Its contract is covered by **contract/fuzz tests** independent of Houdini.

## Migration & Compatibility Plan

This ADR changes **no runtime code**. Compatibility is preserved by construction.

- **Now (this bead):** documentation only. No API, schema, or transport change.
  Existing MCP clients and the `Dockerfile`/`compose.yaml` deployment are
  untouched. Application integrations are explicitly out of scope.
- **Step 1 — protocol seam (Option B), future beads `vzp.9`/`xu4`:** introduce a
  versioned message protocol between the Houdini-embedded worker and the gateway.
  Keep the current in-process path working; the seam is additive and feature-
  flagged. Add contract tests for the protocol.
- **Step 2 — evaluate sidecar (Option C), only if a threshold fires:** a
  follow-up bead attaches a profiling run from the harness above, proposes the
  narrowest possible sidecar, and keeps the Python path as fallback. Protocol
  version bumps must be backward compatible for at least one minor release.
- **Rollback:** because every step is additive and flagged, reverting to
  Python-only is always a configuration change, not a rewrite.
- **Versioning:** the wire protocol carries an explicit version. Gateway and
  worker negotiate capabilities (aligns with `houdini-mcp-vzp.9` capability
  negotiation). Mismatched versions degrade to the last common capability set.

## Consequences

**Positive**

- One debuggable Python stack around `hou`; fastest iteration and richest tests.
- Reliability work (`vzp.9`, `xu4`, `vzp.11`) proceeds without a language
  decision blocking it, inside pre-approved Option B if needed.
- Any future non-Python component is bounded, evidence-gated, and cannot
  duplicate Houdini semantics.

**Negative / accepted trade-offs**

- Python's GIL and synchronous RPyC calls cap raw concurrency; we accept this for
  a control-plane server and mitigate with async at the edge + batching.
- Deferring a sidecar means we may temporarily under-serve extreme
  artifact-throughput or many-session workloads until measurements justify the
  investment. This is intentional — we optimize for evidence, not speculation.

**Follow-ups (not authorized here)**

- `houdini-mcp-vzp.9` — companion process, secure event channel, capability
  negotiation (implements the Option B seam).
- `houdini-mcp-xu4` — resilient WebSocket client with backoff.
- `houdini-mcp-vzp.11` — structured telemetry + performance budgets (feeds the
  profiling harness).

## Review & Links

This decision is **reviewed before companion-protocol implementation** and is
linked from:

- [`README.md`](../../README.md) → "Architecture Decisions" section.
- [`AGENTS.md`](../../AGENTS.md) → "Architecture Decisions (ADRs)" section.

A lightweight docs-link lint (`tests/test_docs_links.py`) fails CI if this ADR,
its README/AGENTS links, or the **Module Boundaries** section disappear.
