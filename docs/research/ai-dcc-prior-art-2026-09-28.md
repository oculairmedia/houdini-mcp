# AI working inside 3D applications: control, tooling and sensing

Research snapshot: **28 September 2026**. Prepared for Emmanuel and the Houdini companion project. Tracking: `houdini-mcp-vzp.32`.

## What I would take from this research

My recommendation is to combine three ideas: a persistent companion that owns the artist's live state, a CLI that exposes repeatable operations and evidence, and a review loop that checks both geometry and rendered appearance. The interesting advances are in the feedback contract, rather than in MCP versus CLI alone.

The most useful references for our next iteration are **Blender CLI** for command contracts and saved-artifact verification; **DCC-MCP and Epic's Toolset Registry** for modular discovery; **BlenderAlchemy and LL3M** for visual correction; **Blender Agent Studio** for staged quality gates; and **Blender-VideoBench** for time-aware, executable evaluation. These are my assessments, not results of a comparative runtime test. Their evidence is examined below.

Several distinctions materially change the comparison. A screenshot tool does not establish that an agent actually critiques its output. Animation tools do not establish that motion is reviewed. A successful script, a valid mesh, an attractive image, and a portable editable scene are different outcomes. Our harness should produce evidence for each outcome we require.

## Scope and evidence method

This report covers **20 implementations or research systems and two benchmark references**, across Blender, Houdini, Maya, Rhino/Grasshopper, FreeCAD, Unreal, Unity and Omniverse/USD. Game editors are included because their editor automation, runtime tests and camera workflows are relevant to DCC integration. Text-to-mesh services are discussed where they connect to an editable DCC workflow; this is not a survey of every generative 3D model.

I read primary project documentation, selected implementation files and research papers. Twenty-two Git repositories were pinned to commit IDs, including the four repositories grouped under DCC-MCP. The companion [source manifest](ai-dcc-prior-art-2026-09-28.sources.json) records commits, retrieved paths and content hashes. Retrieval is not a whole-repository audit. No third-party agent was installed or exercised in our live scene, and no upstream performance result was reproduced here.

**Evidence labels used below:** “documented” means a primary source describes the feature; “code inspected” means a selected implementation path supports it; “paper reports” and “maintainer reports” remain their results. “Implication” is my interpretation. “Not established” means the reviewed evidence does not settle the question, rather than proving a feature absent. Repository recency and popularity are not reliability scores.

## Eight philosophies

These categories are my classification; individual projects can occupy several.

| Philosophy | The central idea | Main advantage | Main trade-off |
|---|---|---|---|
| Prompt to script | Generate Python and execute it in the host | Very broad API reach with a small bridge | Weak quality guarantees unless observation and repair are added |
| Persistent editor bridge | Keep a listener inside the running application | Direct access to unsaved state and artist context | Identity, UI-thread scheduling, recovery and listener lifecycle matter |
| Process-based CLI | Operate on saved files through supervised host processes | Repeatability, machine-readable results and process isolation | Startup cost; saved files cannot stand in for unsaved live state |
| Domain recipe compiler | Generate a constrained procedural description | Smaller search space and reproducible builds | Recipe coverage limits arbitrary scene editing |
| Perceptual search | Render candidates and select or repair using vision | Appearance becomes part of the loop | Render and model costs; visual plausibility is not geometric proof |
| Modular control plane | Discover typed skills independently of transport | Host adapters and plugins can share a stable contract | A registry still needs real host-specific sensing and lifecycle tests |
| External generation into DCC | Generate assets remotely, then prepare and import | Access to image, texture and mesh generation | Cost, provenance, uncertain submissions and import compatibility |
| Evaluation sandbox | Require executable artifacts under a common budget | Comparable measurements and reproducible fixtures | Benchmark success does not establish live artist-session reliability |

## What “sensing” means here

**Structured sensing** includes scene hierarchy, evaluated dimensions, attributes, topology, constraints and object identity. **Visual sensing** includes viewport images, diagnostic views and authored-camera renders. **Diagnostic sensing** includes exceptions, cook times, logs, compiler results and runtime tests. **Temporal sensing** includes sampled frame state, video and motion-specific checks. **Provenance sensing** connects observations to exact sources, revisions, jobs and exported artifacts.

API retrieval and documentation search help an agent choose commands; they do not observe the current scene. Likewise, recording a trajectory for telemetry is different from returning it to the agent for immediate correction.

## Comparison at a glance

The rows summarize reviewed paths. “Controls” in the time column means the system can edit animation; it does not imply motion acceptance. Profiles provide evidence links and qualifications.

| Example | Host and execution | Tooling philosophy | Sensing setup | Time / feedback emphasis |
|---|---|---|---|---|
| 1. Blender CLI | Fresh headless Blender | Typed JSON CLI plus bpy escape | Multiview, mesh health, export readback, camera calibration | Keyframes and export checks; artifact acceptance |
| 2. CLI-Anything Blender | JSON recipe → Blender render | Domain compiler and stateful CLI | Real preview bundles and trajectory records | Preview-session history; live editor state is separate |
| 3. MCP for Blender | Embedded add-on + external MCP | Persistent API bridge | Scene/object inspection, viewport, bounded before/after telemetry | Trajectory capture; critic loop not established |
| 4. BlenderGPT | In-editor add-on | Prompt → generated bpy | Execution exceptions in inspected path | No automatic visual critic established |
| 5. Houdini-Agent | Standalone UI + embedded bridge | Agent modes, registry and Houdini skills | Context, viewport, geometry analysis, cook profiling | Host access; durable temporal acceptance not established |
| 6. DCC-MCP | Shared core + host adapters | Versioned skills and progressive discovery | Structured probes, artifacts, viewport validity checks | Jobs/checkpoints and adapter examples |
| 7. Maya MCP | MCP → Maya command bridge | Typed operations plus retrieval | Scene snapshot, playblast, turntable, color policy | Keyframes/tangents and captured sequences |
| 8. RhinoMCP | Python MCP → C# plugin | Rhino and Grasshopper operations | Objects, layers, viewport and graph state | Parametric solution state; motion review not established |
| 9. FreeCAD MCP | GUI, background or isolated process | Explicit execution modes | Object properties, screenshots, FEM results | Async status and timeout semantics |
| 10. Community Unreal MCP | Python → native editor plugin | Actor and Blueprint bridge | Actor state, screenshot, compile response | Editor manipulation; runtime acceptance separate |
| 11. Epic Unreal MCP | In-editor HTTP MCP | Reflection-based Toolset Registry | Editor/Slate inspection and automation tests | Serial game-thread execution |
| 12. Unity MCP | Editor package + external server | Focused tool groups | Scene/assets, screenshots, tests, profiler/logs | Animation controls and runtime tools |
| 13. Scenario Blender plugin | Local MCP + remote APIs | Generation jobs and staged imports | Scene details, still references, job provenance | Image/video generation lanes; still capture has limits |
| 14. BlenderAlchemy | Rendered code candidates | Vision-guided search and selection | Candidate renders and pairwise evaluation | Iterative appearance refinement |
| 15. LL3M | Modular Blender code | Planner/coder/critic/verifier | Adaptive multiview and before/after verification | Localized edits; public hosted server discontinued |
| 16. SceneCraft | Relational scene generation | Constraints plus visual feedback | Layout constraints and render critique | Iterative spatial refinement |
| 17. EZBlender | Semantic domain agents | Local propose/verify/refine | Render feedback and benchmark scoring | Local repair; reported latency study |
| 18. 3D-GPT | Infinigen procedural tools | Tool selection and parameter assignment | Tool documentation and procedural representation | Procedural generation; partial public implementation |
| 19. USD Code / ChatUSD | USD service + Kit integration | Knowledge, code and scene-query nodes | Explicit stage queries; immediate visualization | Stage editing; image critic not established |
| 20. Blender Agent Studio | Saved scene + headless tools | Skills and staged delivery gates | Fixed views, dimensions, overlays, fresh export reopen | Animation workflows and bounded render budgets |
| 21. BlenderGym | Research benchmark | Start-to-goal graphics editing | Target/render comparisons | Five editing families; not a live companion |
| 22. Blender-VideoBench | Fresh Blender sandbox | Budgeted programmatic reconstruction | Source frames, rendered video, independent scoring | Animated executable result and temporal metrics |

## Implementation profiles

### 1. Blender CLI — an agent-facing command contract

**Philosophy:** Treat Blender as a reproducible executable asset processor. The reviewed v0.6.0 launches background Blender for operations, rather than requiring an installed resident add-on. It exposes structured JSON commands, batching, schemas with effects, and an arbitrary-bpy path. Documented sensing includes Workbench multiview contact sheets, blank-image signals, mesh checks, camera reprojection and format-aware export readback. Acceptance binds evidence to source/specification/snapshot hashes. Detached jobs have supervision, timeouts and process-tree cleanup. Upstream smoke-test results are maintainer reports, not our verification. [Pinned project documentation](https://github.com/renezander030/blender-cli/blob/6d042220b4229e5594d5df509a479634eb04b181/README.md), [command implementation](https://github.com/renezander030/blender-cli/blob/6d042220b4229e5594d5df509a479634eb04b181/blender-cli).

**Implication:** Borrow its result envelopes, exact artifact checks and explicit failure states. Fresh processes suit disposable acceptance fixtures; our artist's unsaved Houdini session still needs a persistent companion. An AST guard is not a general sandbox.

### 2. CLI-Anything's Blender harness — a recipe, not a live scene proxy

This is a separate project from Blender CLI. Its JSON scene project can be edited without Blender installed, then compiled into bpy for rendering. The harness documents a REPL and JSON results. The inspected preview path produces real hero and Workbench images; poll-mode preview stores session state, immutable bundles and trajectory history. The recipe is the authored representation, rather than a transparent reflection of every arbitrary existing Blender scene. [Pinned harness guide](https://github.com/HKUDS/CLI-Anything/blob/34f519533bc175d2fe287ab8316b0dd99bb9cc43/blender/agent-harness/cli_anything/blender/README.md), [preview implementation](https://github.com/HKUDS/CLI-Anything/blob/34f519533bc175d2fe287ab8316b0dd99bb9cc43/blender/agent-harness/cli_anything/blender/core/preview.py).

**Implication:** This is a useful philosophy for our recursive architecture demos: preserve a small declarative recipe, then compile and review it. Keep recipe authority distinct from the complete artist scene so a regeneration cannot silently erase unrelated work.

### 3. MCP for Blender — a persistent bridge with richer trajectories

Formerly named BlenderMCP, this project connects an external MCP server to a Blender add-on over TCP. It provides scene/object information, viewport images, Python execution and asset-provider integrations. The inspected trajectory module records before/after state and bounded scene summaries, supports older-add-on fallbacks, and can rate-limit optional image capture. Its trajectory upload is Supabase-based, not a local JSONL archive. The README distinguishes default minimal usage telemetry from consent-dependent content capture and documents an all-telemetry disable option. [Pinned README](https://github.com/ahujasid/mcp-for-blender/blob/41a184322db3ccdcb2fdbc1f6994afe71bf9163c/README.md), [trajectory implementation](https://github.com/ahujasid/mcp-for-blender/blob/41a184322db3ccdcb2fdbc1f6994afe71bf9163c/src/blender_mcp/trajectory.py).

**Implication:** Bounded deltas are valuable for reducing repeated scene dumps. Telemetry is not evidence that the active agent sees, judges and repairs every image. For our companion, local review receipts should be explicit outputs with defined retention, rather than depending on an analytics backend.

### 4. BlenderGPT — the useful early baseline

The 2023 add-on translates conversational requests into Blender Python. The inspected operator executes the generated code and displays execution errors, with Blender undo integration. That path does not establish an automatic render/critique cycle. Later papers may use modified BlenderGPT baselines; those should not be attributed to the original add-on. [Pinned README](https://github.com/gd3kr/BlenderGPT/blob/3fbc3bd3f169d904f8bf8a067807c4a71d3d3b4b/README.md), [operator implementation](https://github.com/gd3kr/BlenderGPT/blob/3fbc3bd3f169d904f8bf8a067807c4a71d3d3b4b/__init__.py).

**Implication:** A small script bridge is sufficient to demonstrate API reach. It is insufficient as a delivery contract: success says the code ran, not that proportions, topology, lighting or motion match the request. Treat this as historical prior art, rather than a current compatibility recommendation.

### 5. Houdini-Agent — a host-specific assistant and semantic toolkit

Its current architecture uses a standalone Qt/QML application and Houdini bridge, with Agent/Ask/Plan modes, a central tool registry, mode guards and extension hooks. The inspected bridge handles scene context, tool execution and undo requests through JSON-line TCP, dispatching host work through Houdini's main-thread mechanism. Documentation lists viewport capture, attribute/bounds/connectivity analysis, dependency inspection and cook profiling. [Pinned README](https://github.com/Kazama-Suichiku/Houdini-Agent/blob/73c5d2ca3d48e97208b09c036defc1271f58d34d/README.md), [bridge](https://github.com/Kazama-Suichiku/Houdini-Agent/blob/73c5d2ca3d48e97208b09c036defc1271f58d34d/houdini_agent/bridge/server.py), [registry](https://github.com/Kazama-Suichiku/Houdini-Agent/blob/73c5d2ca3d48e97208b09c036defc1271f58d34d/houdini_agent/utils/tool_registry.py).

**Implication:** This is the closest reference for useful Houdini semantics and read-versus-write modes. Separate those semantics from the chosen model/chat UI. The reviewed paths do not establish durable job recovery, portable source packaging or exact pre-apply temporal acceptance; those need their own contracts and tests.

### 6. DCC-MCP — modular infrastructure across hosts

The core describes a Rust-first control plane with Python bindings, CLI/MCP/REST access, versioned skills, effects, jobs, artifacts, checkpoints and policies. Progressive discovery separates listing/searching/describing from loading and calling skills. Host adapters provide the actual DCC operations; this is infrastructure, not itself a model or artistic planner. The Maya adapter distinguishes process, dispatcher and DCC readiness. [Pinned core](https://github.com/dcc-mcp/dcc-mcp-core/blob/7b8a76afe9c1a87e032f60be86982a4bc01efe28/README.md), [Maya adapter](https://github.com/dcc-mcp/dcc-mcp-maya/blob/7178b242d0b1417469de39a0c964c398acc538d5/README.md).

The inspected Houdini viewport script checks image dimensions and rejects black or single-color captures while reporting viewport/display/camera context; a headless host can report capture unavailability. The Blender adapter documents matched beauty and evaluated-wireframe examples. These checks make a screenshot result more informative, but they do not prove artistic correctness. [Houdini capture implementation](https://github.com/dcc-mcp/dcc-mcp-houdini/blob/890d53d984cf871f894a691b82187fa7d44ac698/src/dcc_mcp_houdini/skills/houdini-render/scripts/capture_viewport.py), [Blender adapter](https://github.com/dcc-mcp/dcc-mcp-blender/blob/cf520d0ce18c5084757e06ac704caffe94c5f344/README.md).

**Implication:** Borrow stable plugin interfaces, progressive discovery, readiness distinctions and capture validity. A Rust implementation elsewhere is not evidence that rewriting our Python host core would improve performance. Our existing ADR requires measured justification for a language/process change.

### 7. Maya MCP — semantics, knowledge and imaging policy

This project exposes typed Maya operations through a Python MCP server and Maya command bridge: modeling, materials, transforms, animation, snapshots, playblasts and turntables. It documents retrieval using semantic and lexical search, validated learned patterns, and a dockable assistant. The inspected color policy manages review view transforms. Its Arnold still workflow can export an ASS scene and invoke external `kick`, separating expensive rendering from the GUI rendering path. [Pinned README](https://github.com/abrahamADSK/maya-mcp/blob/a9f0af10ad327a052a12b8b7cfc4aa812be265e2/README.md), [bridge](https://github.com/abrahamADSK/maya-mcp/blob/a9f0af10ad327a052a12b8b7cfc4aa812be265e2/src/maya_mcp/maya_bridge.py), [color policy](https://github.com/abrahamADSK/maya-mcp/blob/a9f0af10ad327a052a12b8b7cfc4aa812be265e2/src/maya_mcp/color_policy.py).

**Implication:** Units, color management and rendering mode belong in observation metadata. API retrieval helps repair commands, while playblasts and geometry probes assess results. Undo chunks should not be described as crash-atomic transactions spanning external files.

### 8. RhinoMCP — editable CAD and Grasshopper graphs

A Python MCP server communicates with a C# RhinoCommon plugin. The documented surface includes object/layer/material inspection and editing, viewport capture, exports and undo/redo. Grasshopper support covers components, connections, sliders, solutions and baking. The project also documents server/plugin version checks. [Pinned project documentation](https://github.com/jingcheng-chen/rhinomcp/blob/70b63a2b86e4f92f3250f9a5e4a5813c2a38c163/README.md).

**Implication:** For procedural work, keep the editable graph and inspect its health alongside the baked geometry. A correct image can conceal a broken dependency or a graph that cannot regenerate. Our analogous sensors should include node dependencies, cook errors and evaluated output. The reviewed documentation does not establish a motion-quality loop.

### 9. FreeCAD MCP — explicit execution modes and honest timeouts

The bridge distinguishes GUI execution, independent background geometry followed by explicit GUI commit, and isolated `freecadcmd` work. Tools inspect documents/properties and capture configurable views; FEM operations provide quantitative engineering outputs. Its execution documentation separates queue and execution timeout budgets. A queued task may expire before running; a started GUI task cannot necessarily be interrupted when the caller times out. Completed async history is bounded and process-local. [Pinned README](https://github.com/neka-nat/freecad-mcp/blob/d6bbe4b38be3a622b5981d9d2afa7037ee080534/README.md), [execution contract](https://github.com/neka-nat/freecad-mcp/blob/d6bbe4b38be3a622b5981d9d2afa7037ee080534/docs/execution.md), [tool reference](https://github.com/neka-nat/freecad-mcp/blob/d6bbe4b38be3a622b5981d9d2afa7037ee080534/docs/tools.md).

**Implication:** This is an especially useful recovery reference. Report whether an operation was queued, running, completed or uncertain. A client timeout must not imply the mutation stopped. Separate heavy disposable computations from live edits, and make any later import explicit.

### 10. Community Unreal MCP — native editor dispatch

The older community project bridges Python MCP to a C++ editor plugin for actors and Blueprints. The inspected command routing includes both `focus_viewport` and `take_screenshot`, and dispatches operations onto the game thread. It is therefore inaccurate to characterize it as wholly visually blind. Blueprint compilation is another feedback channel. Its pinned repository snapshot is from April 2025; this review does not establish compatibility with current Unreal releases. [Pinned README](https://github.com/chongdashu/unreal-mcp/blob/4e5f00da50733190481311e254d16d137a84ef33/README.md), [bridge implementation](https://github.com/chongdashu/unreal-mcp/blob/4e5f00da50733190481311e254d16d137a84ef33/MCPGameProject/Plugins/UnrealMCP/Source/UnrealMCP/Private/UnrealMCPBridge.cpp).

**Implication:** Screenshots and compile diagnostics complement one another. Neither alone validates runtime collision, navigation or behavior. Keep this distinct from Epic's newer official integration.

### 11. Epic's Unreal MCP — separate the tool registry from transport

Epic's Unreal 5.8 documentation labels its in-editor MCP feature Experimental. Tools come from a separate Toolset Registry, with reflected Python/C++ definitions and structured schemas. The default discovery mode offers toolset listing, description and invocation rather than exposing every tool at once. Calls run serially on the game thread; clients are instructed not to overlap them. Documented capabilities include actors, lighting, material instances, Slate inspection and automation tests. Tool refresh is supported, but new C++ reflected functions require restart. [Official Unreal MCP documentation](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor).

**Implication:** A host operation should be reusable through CLI, MCP and other interfaces. The registry should own its schema and lifecycle. This overview does not establish an autonomous screenshot critic; editor introspection and automation tests are its clearly documented sensing channels.

### 12. Unity MCP — combine visual and runtime feedback

The current main-branch README describes focused editor tools for scenes, assets, scripts, tests, profiling and builds, with tool groups and multi-instance routing. The inspected camera implementation detects capabilities such as Cinemachine and delegates screenshot and multiview capture to scene tooling. This confirms capture entry points on main; richer beta documentation should not silently be treated as the same release. [Pinned README](https://github.com/CoplayDev/unity-mcp/blob/8be7d96d95aa3e262894c64412f0df3b432efa05/README.md), [camera implementation](https://github.com/CoplayDev/unity-mcp/blob/8be7d96d95aa3e262894c64412f0df3b432efa05/MCPForUnity/Editor/Tools/Cameras/ManageCamera.cs).

**Implication:** Tests, logs and profiler signals should travel alongside images, and capability-dependent tools should state their fallback. Animation authoring access is useful; reliable motion acceptance still needs explicit frame sampling and behavior checks.

### 13. Scenario's Blender plugin — durable external jobs and staged import

Scenario connects local Blender MCP operations to remote generation services. Its canonical tool reference covers scene/object inspection, opt-in Python execution, generation jobs, still-reference capture and staged imports. It documents quote-bound approvals, credential-scoped job recovery, revision/context checks, and uncertain submission handling without blind replay. The protocol separates main-thread preparation and completion from worker HTTP activity. Capture references are still images; video generation and clip/mesh preparation are distinct capabilities. Some UI lanes remain prototype workflows. [Pinned README](https://github.com/scenario-labs/blender-plugin/blob/6fa30d06b43c6d3ce4e903b45e8635034e4ecb39/README.md), [canonical MCP reference](https://github.com/scenario-labs/blender-plugin/blob/6fa30d06b43c6d3ce4e903b45e8635034e4ecb39/docs/MCP.md), [protocol](https://github.com/scenario-labs/blender-plugin/blob/6fa30d06b43c6d3ce4e903b45e8635034e4ecb39/scenario/mcp/protocol.py).

**Implication:** Prepare/apply handles, exact quote/source provenance and honest uncertainty are good models for any external asset service. An imported generated asset still needs DCC-side geometry, materials and portability checks. This plugin is not evidence of a complete autonomous scene-quality loop.

### 14. BlenderAlchemy — render candidates, compare, retain the best

BlenderAlchemy represents an editable scene subsystem as Python and uses vision to propose and evaluate changes. Its paper describes multiple candidates, rendered comparisons, larger “leap” edits and smaller “tweak” edits. The inspected refinement code preserves candidate/winner programs and images, uses pairwise selection, and bounds concurrency. The experiments emphasize appearance edits such as materials, lighting and procedural parameters; this is not universal scene reconstruction. [Paper](https://arxiv.org/html/2404.17672v2), [pinned refinement code](https://github.com/ianhuang0630/BlenderAlchemyOfficial/blob/4444411592150a72d01d55ef84b1ac844b0b2ad0/refinement_process.py), [agent code](https://github.com/ianhuang0630/BlenderAlchemyOfficial/blob/4444411592150a72d01d55ef84b1ac844b0b2ad0/agents.py).

**Implication:** Use small candidate sets when a visual decision is ambiguous, then show the artist the winner and alternatives. Preserve the baseline and reject regressions. Rendering several variants costs more than inspecting one; this should be a deliberate review mode with a budget, rather than the default for every parameter change.

### 15. LL3M — modular programs and separate critique from verification

LL3M's paper combines planning, retrieval, coding, criticism, verification and user feedback around readable modular Blender programs. Its critic uses multiple adaptive views; verification checks before/after edits against specific critiques. Localized revisions retain broader code context. The public repository describes a client/server arrangement, but its current README states that the hosted server was discontinued after the paper's model was retired. An academic/evaluation license is present; this is not an unrestricted production reuse assumption. [Paper](https://arxiv.org/html/2508.08228v1), [pinned current repository documentation](https://github.com/threedle/ll3m/blob/b5e79c3efa862efcc6e4105ce48245230fee3ebf/README.md).

**Implication:** A useful critique names an object, a defect and evidence; verification checks whether that specific defect changed. These can be logical roles within one agent workflow. They do not require multiple model processes or simultaneous mutations of the host. LL3M remains valuable methodological prior art, not a currently functioning drop-in hosted dependency.

### 16. SceneCraft — relational intent becomes spatial constraints

Here SceneCraft means **Hu et al., arXiv:2403.01248**, not the distinct diffusion project with the same name. The paper describes relational scene intent, numerical spatial constraints and code generation, followed by rendered feedback and reusable function/library learning. Experiments use retrieved assets and evaluate scene construction. No official public executable implementation was verified in this review. [Primary paper](https://arxiv.org/html/2403.01248v1).

**Implication:** Turn artistic intent into a combination of constraints and appearance goals. For our recursive city, door alignment, minimum passage width, scale relationships and camera traversal can become measurable contracts. Vision judges mood and composition; it should not be asked to infer exact clearance from an attractive perspective image.

### 17. EZBlender — domain specialists and local repair

EZBlender's paper routes semantic instructions through planning and domain agents for geometry/modifiers, materials, lighting and cameras. Its propose/verify/refine loops repair locally instead of always replanning the whole scene. The evaluation uses specified BlenderGym tasks and rendering/model configurations, including a reported latency improvement under those conditions. The public repository packages skills/presets and launch workflows. That evidence does not establish a general speedup on our Houdini setup. [Paper](https://arxiv.org/html/2601.07143v1), [pinned repository](https://github.com/Aztech-Lab/EZ_Blender/blob/7c15b5b20fdd7a8513d75bc26613e955190ffb43/README.md).

**Implication:** Organize plugins by domain with cheap local validators and targeted repair instructions. Independently preparing materials and geometry may be useful; parallel planning does not authorize concurrent access to Houdini's host API. Measure total edit-to-review time, including rendering and failed candidates.

### 18. 3D-GPT — language drives an existing procedural generator

3D-GPT decomposes requests into tool selection, concept enrichment and parameter assignment for a predefined procedural modeling system, using Infinigen. Tool descriptions and procedural parameters are central to the representation. The official repository is a partial implementation; its README describes a richer configuration-file parser as upcoming, not already shipped. The reviewed evidence does not establish a general multiview visual correction loop. [Paper](https://arxiv.org/html/2310.12945v1), [pinned repository](https://github.com/Chuny1/3DGPT/blob/590bf71bde9b854582d60913e054cda4d6cb38c2/README.md).

**Implication:** This is a good conceptual fit for Houdini: improve the procedural vocabulary and expose meaningful parameters, rather than regenerate arbitrary low-level code every time. For self-referential architecture, a seed, recursion rule, transform family and termination/LOD policy provide compact reproducible control.

### 19. NVIDIA USD Code and ChatUSD — query stage context explicitly

USD Code exposes expertise for USD questions and code generation. Documentation distinguishes a code-generation node without current-stage context from interactive execution in a Kit stage. ChatUSD's SceneInfoNetworkNode produces scene-query code for hierarchy, names, dimensions and positions before interactive edits. Immediate visualization is part of the editor workflow; the reviewed documentation does not establish an autonomous image-evaluation loop. [Service overview](https://docs.omniverse.nvidia.com/services/latest/services/usd-code/overview.html), [usage](https://docs.omniverse.nvidia.com/services/latest/services/usd-code/usage.html), [scene-query node](https://docs.omniverse.nvidia.com/kit/docs/omni.ai.chat_usd.bundle/latest/components/scene-info-network-node.html).

**Implication:** Make the difference between model knowledge and authoritative live scene context explicit. USD can become a cross-DCC artifact and interchange boundary, while Houdini-specific node and cook semantics remain in Houdini. A generated USD program is not evidence that its referenced assets resolve on another machine.

### 20. Blender Agent Studio — staged quality and evidence caveats

This independent plugin combines specialist skills and local tools around saved Blender scenes and build-source Python. It documents graybox review, evaluated dimensions and constraints, fixed diagnostic views, smaller repair views, authored-camera beauty renders, reference overlays and fresh-process export reopen. An optional Rust SceneIR runtime adds baseline comparisons; the core tools do not require it. Its README reports five matched workflow pairs with better technical gates and mixed visual gains, at higher token cost and sometimes higher elapsed time. The study used skills without the optional MCP tools, so it does not measure their added benefit. [Pinned documentation](https://github.com/ifBars/blender-agent-studio/blob/ef707f828410ab2059424cad15925e24c975cbd3/README.md).

**Implication:** This is a strong reporting example precisely because it separates technical validity, aesthetic preference and cost. Use graybox acceptance before detail, preserve the editable build source, and measure the full workflow. Five pairs are illustrative evidence, not an arbitrary-task success rate.

## Benchmark references

### 21. BlenderGym — controlled graphics editing fixtures

The CVPR 2025 project provides 245 handcrafted scenes spanning procedural geometry, lighting, materials, shape keys and object placement. Its start/goal tasks create controlled graphics-editing comparisons. This is an evaluation resource rather than a persistent editor companion, and coverage of those families does not establish animation continuity, live-session recovery or whole-scene portability. [Primary project page](https://blendergym.github.io/), [paper](https://arxiv.org/abs/2504.01786), [pinned repository](https://github.com/richard-guyunqi/BlenderGym-Open/blob/67c8b48bf8c548c701b6873db6fcc6527d756385/README.md).

**Implication:** Borrow the fixture discipline: the same initial scene, goal, camera and budget across harness revisions. Our fixtures should include intentional failure cases and artistic exceptions, rather than only easy demonstrations of successful execution.

### 22. Blender-VideoBench — an animated executable result under a budget

This September 2026 benchmark reconstructs source videos in fresh Blender 4.2 sandboxes. Its agent-facing harness uses bash and frame inspection under a common cost limit; external asset libraries are excluded. The submission is an animated Blender scene. Scoring runs separately from the agent loop, using paired video-question retention and frozen V-JEPA 2.1 video similarity. Failed reconstructions remain in the evaluation pool. The public repository supplies protocol and reproduction instructions; large datasets were not downloaded or run here. [Pinned repository/protocol](https://github.com/yunlong10/BVB/blob/69b7a488e972b648819cc12cd2752256f84efbc3/README.md), [paper](https://arxiv.org/abs/2609.15478).

**Implication:** Time awareness should be tested on a reopened, rendered artifact, not inferred from keyframe creation. Keep judging separate from editing so a harness cannot grade only its own favorable intermediate output. Video similarity is useful perceptual evidence; it does not certify exact physical contacts or a seamless recursion transition.

## Findings that should shape our harness

These are recommendations derived from the comparisons, not claims that the current companion already implements every item.

### The observation should identify the state it describes

Return a versioned observation envelope with host build, session identity, scene/revision identity, selected objects, object references, source hashes, frame/time range, FPS, camera transform and projection, units, color settings, render mode, timings and truncation. State whether geometry is evaluated, sampled or complete. Include the last acknowledged mutation and outstanding jobs.

Without that envelope, an agent can mistake an old image for a new edit, compare different cameras, or apply evidence from another HIP. Scene paths alone are not stable object identity. A reopened file should create a new session identity even when its filename matches.

### Make cheap feedback frequent and expensive feedback deliberate

The useful loop is: query relevant objects, make one bounded change, inspect deltas and errors, capture a small diagnostic review, then escalate to full multiview or beauty rendering when needed. Cache only against explicit revision/time/camera keys. Coalesce host events and report invalidation; do not silently reuse stale artifacts.

Adaptive views help find hidden defects, while fixed views make before/after comparisons fair. Use both: a fixed comparison set plus additional views chosen for the defect. Workbench/wireframe and authored beauty images answer different questions and should retain their own settings.

### Treat review as a decision with evidence

A review should produce: the brief's criteria, changed objects, quantitative checks, visual findings, known omissions, artifact links and an accept/reject decision. Each finding needs a target and a testable statement. For example, “the lower landing intersects the door sweep at frames 44–51” is actionable; “make it nicer” is not.

Keep technical pass/fail separate from aesthetic preference. Our Escher geometry deliberately violates ordinary perspective expectations, and fractured neon may intentionally contain gaps. Validators should declare relevant constraints and approved exceptions, rather than reject a style because it resembles a defect in another task.

### Cancellation, undo and recovery need different words

Cancellation can remove a queued operation without guaranteeing interruption after host execution starts. Undo may restore a scene edit without removing generated external files. A saved journal may recover job records without making a mutation crash-atomic.

The contract should expose queued/running/completed/failed/cancelled/uncertain states. Reconciliation should inspect actual host state before retrying an uncertain mutation. A timeout must return enough information to ask about the same operation, rather than encouraging a duplicate apply.

### A plugin is more than a list of tools

Use a small shared core for identity, scheduling, schemas, jobs, artifacts, revisions, budgets and error conventions. Domain plugins contribute operations, sensors and validators. The same operations should be accessible through CLI and MCP adapters. Plugins declare versions, effects, host/thread requirements, lifecycle hooks and capability limitations.

Discovery should be inexpensive: search and describe before loading large catalogs. Test load, failed load, reload, unload and listener cleanup. A catalog describing a release must not be confused with capabilities available in the current live instance. Logical specialist roles can share this infrastructure without requiring multiple simultaneous agents.

### Exact editable artifacts beat an attractive screenshot alone

Archive exact source bytes, inline snippets, dependencies, hashes and build settings beside the review. Reopen a disposable copy, relink from its manifest, cook again and compare geometry and rendered evidence. Record what was compared and with what tolerance. Export readback checks the export; it does not by itself prove the native procedural scene is portable.

For our town, do not assume a clean Git checkout contains companion-owned revisions or unsaved artist work. Package from an identified source state, and test separately from the live artist HIP.

## Time-aware sensing for the recursive city

I would make a motion review a bounded sampling plan plus a small video, with all state restored afterward. Record the frame range, sampling policy, FPS, shutter, simulation/cache assumptions and cameras. Probe transitions and extrema, not only the first and final frames.

| Intended effect | Structured check | Visual evidence | Failure to distinguish |
|---|---|---|---|
| Door into a repeating hallway | Passage width, door sweep, transform alignment | Eye-level approach/open/crossing sequence | A beautiful closed-door render can hide blocked traversal |
| Scale recursion | Transform ratios, bounds growth, LOD/termination policy | Continuous camera traversal and scale cues | Finite geometry should not be advertised as physically infinite |
| Escher gravity changes | Camera-relative projection, landing continuity, declared gravity domains | Authored illusion view plus diagnostic alternatives | Off-axis “wrongness” may be intentional; landing gaps may not be |
| Animated stair or portal | Clearance/contact over sampled frames | Contact sheet and short clip near extrema | Sparse sampling can miss collisions and popping |
| Neon/material animation | Parameter ranges and temporal change statistics | Fixed-exposure/color-managed clip | Exposure changes can masquerade as material improvements |
| Repeating camera loop | End/start pose, projection and image continuity | Boundary frames and looped playback | Matching position alone can hide orientation or lighting discontinuity |

Each check should report sampling coverage. A bounded sample can find defects, but cannot prove all intermediate times safe unless a suitable continuous bound or solver is used. “Infinite” visual recursion should be described through its finite representation, camera strategy and regeneration/LOD behavior.

## How this maps to our existing work

This is a research mapping to recorded follow-ups, not a status audit or new implementation plan. Dependencies and full acceptance remain in Beads. The report creates no duplicate engineering tasks.

| Existing Bead | Relevant prior art | Concrete evidence to seek |
|---|---|---|
| `houdini-mcp-vzp.15` — fresh-process acceptance | Blender CLI, host readiness distinctions in DCC-MCP | Disposable restart; new identity; archived jobs; stale-session rejection; no replay or duplicate listener |
| `.16` — portable scene/source packaging | CLI export readback, Blender Agent Studio, USD boundaries | Exact source manifest; isolated relink/reopen; geometry equivalence; linked review artifacts |
| `.17` — recovery and retention | FreeCAD timeouts, Scenario job recovery | Fault-injected partial/uncertain outcomes; retained referenced sources; bounded cleanup; no duplicate mutation |
| `.18` — pre-apply temporal review | BlenderAlchemy, LL3M, BVB | Rejected candidate leaves baseline intact; accepted exact source applied once; stable camera/time restoration |
| `.19` — external plugin lifecycle | DCC-MCP, Epic Toolset Registry | Failed load/reload/unload; catalog parity; listener cleanup; clear capability errors |
| `.20` — edit-review scorecard | Blender Agent Studio, BlenderGym, BVB | Same fixtures and budgets; linked artifacts; cold/warm phase timings; quality alongside speed |

Retain Python for Houdini semantics and the gateway, consistent with [ADR 0001](../adr/0001-language-and-process-boundaries.md). A compiled sidecar is an evidence-gated option for byte transport or supervision, not a reason to duplicate HOM. None of this research establishes that our transport is the dominant current bottleneck.

## Proposed evaluation protocol

Use disposable saved fixtures and a fixed operation brief. Run both cold-process and warm-session cases. Measure discovery, observation, queue wait, mutation/cook, capture, artifact transfer, critique and acceptance separately. Record end-to-end time, context bytes, artifact bytes, render/model cost, retries, failures and quality outcomes. Compare distributions across repeated runs; label sample size and hardware. A single fast success is not a regression baseline.

The initial fixture set should include a small static object, a dense procedural street, a deliberately broken source dependency, a door/clearance animation, a recursion boundary, an intentional anamorphic illusion, an unavailable viewport, an uncertain timed-out mutation and a failed plugin reload. Failures belong in the denominator.

Performance gates should require the same quality and coverage. A quicker result obtained by skipping motion frames or export verification is a different service level. Set numerical thresholds after collecting a baseline, then investigate regressions by phase. Do not import a paper's speedup as our target or call a stricter workflow inefficient simply because it does more validation.

For an artist-facing comparison, show a fixed before/after pair and a short motion clip, with technical findings visible separately. Keep aesthetic preference open to the artist. Record why a candidate was rejected so the next edit repairs the issue instead of repeating it.

## Source inventory and limits

The following pinned repository snapshots support the profiles. Full commit IDs, retrieved file hashes and additional implementation paths are in the [machine-readable source manifest](ai-dcc-prior-art-2026-09-28.sources.json). Official documentation URLs and paper versions are also listed there. Versionless vendor pages can change after this date.

| Repository | Pinned commit | Commit date (UTC) |
|---|---|---|
| [renezander030/blender-cli](https://github.com/renezander030/blender-cli) | [6d042220b422](https://github.com/renezander030/blender-cli/commit/6d042220b4229e5594d5df509a479634eb04b181) | 2026-09-27 |
| [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) | [41a184322db3](https://github.com/ahujasid/mcp-for-blender/commit/41a184322db3ccdcb2fdbc1f6994afe71bf9163c) | 2026-09-27 |
| [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent) | [73c5d2ca3d48](https://github.com/Kazama-Suichiku/Houdini-Agent/commit/73c5d2ca3d48e97208b09c036defc1271f58d34d) | 2026-09-04 |
| [dcc-mcp/dcc-mcp-core](https://github.com/dcc-mcp/dcc-mcp-core) | [7b8a76afe9c1](https://github.com/dcc-mcp/dcc-mcp-core/commit/7b8a76afe9c1a87e032f60be86982a4bc01efe28) | 2026-09-28 |
| [dcc-mcp/dcc-mcp-houdini](https://github.com/dcc-mcp/dcc-mcp-houdini) | [890d53d984cf](https://github.com/dcc-mcp/dcc-mcp-houdini/commit/890d53d984cf871f894a691b82187fa7d44ac698) | 2026-09-25 |
| [dcc-mcp/dcc-mcp-blender](https://github.com/dcc-mcp/dcc-mcp-blender) | [cf520d0ce18c](https://github.com/dcc-mcp/dcc-mcp-blender/commit/cf520d0ce18c5084757e06ac704caffe94c5f344) | 2026-09-27 |
| [dcc-mcp/dcc-mcp-maya](https://github.com/dcc-mcp/dcc-mcp-maya) | [7178b242d0b1](https://github.com/dcc-mcp/dcc-mcp-maya/commit/7178b242d0b1417469de39a0c964c398acc538d5) | 2026-09-28 |
| [abrahamADSK/maya-mcp](https://github.com/abrahamADSK/maya-mcp) | [a9f0af10ad32](https://github.com/abrahamADSK/maya-mcp/commit/a9f0af10ad327a052a12b8b7cfc4aa812be265e2) | 2026-08-16 |
| [jingcheng-chen/rhinomcp](https://github.com/jingcheng-chen/rhinomcp) | [70b63a2b86e4](https://github.com/jingcheng-chen/rhinomcp/commit/70b63a2b86e4f92f3250f9a5e4a5813c2a38c163) | 2026-09-13 |
| [chongdashu/unreal-mcp](https://github.com/chongdashu/unreal-mcp) | [4e5f00da5073](https://github.com/chongdashu/unreal-mcp/commit/4e5f00da50733190481311e254d16d137a84ef33) | 2025-04-22 |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | [34f519533bc1](https://github.com/HKUDS/CLI-Anything/commit/34f519533bc175d2fe287ab8316b0dd99bb9cc43) | 2026-09-22 |
| [gd3kr/BlenderGPT](https://github.com/gd3kr/BlenderGPT) | [3fbc3bd3f169](https://github.com/gd3kr/BlenderGPT/commit/3fbc3bd3f169d904f8bf8a067807c4a71d3d3b4b) | 2023-06-10 |
| [ianhuang0630/BlenderAlchemyOfficial](https://github.com/ianhuang0630/BlenderAlchemyOfficial) | [444441159215](https://github.com/ianhuang0630/BlenderAlchemyOfficial/commit/4444411592150a72d01d55ef84b1ac844b0b2ad0) | 2024-12-06 |
| [threedle/ll3m](https://github.com/threedle/ll3m) | [b5e79c3efa86](https://github.com/threedle/ll3m/commit/b5e79c3efa862efcc6e4105ce48245230fee3ebf) | 2026-03-07 |
| [scenario-labs/blender-plugin](https://github.com/scenario-labs/blender-plugin) | [6fa30d06b43c](https://github.com/scenario-labs/blender-plugin/commit/6fa30d06b43c6d3ce4e903b45e8635034e4ecb39) | 2026-09-27 |
| [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) | [d6bbe4b38be3](https://github.com/neka-nat/freecad-mcp/commit/d6bbe4b38be3a622b5981d9d2afa7037ee080534) | 2026-09-24 |
| [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) | [8be7d96d95aa](https://github.com/CoplayDev/unity-mcp/commit/8be7d96d95aa3e262894c64412f0df3b432efa05) | 2026-09-27 |
| [Chuny1/3DGPT](https://github.com/Chuny1/3DGPT) | [590bf71bde9b](https://github.com/Chuny1/3DGPT/commit/590bf71bde9b854582d60913e054cda4d6cb38c2) | 2025-03-05 |
| [Aztech-Lab/EZ_Blender](https://github.com/Aztech-Lab/EZ_Blender) | [7c15b5b20fdd](https://github.com/Aztech-Lab/EZ_Blender/commit/7c15b5b20fdd7a8513d75bc26613e955190ffb43) | 2026-07-17 |
| [ifBars/blender-agent-studio](https://github.com/ifBars/blender-agent-studio) | [ef707f828410](https://github.com/ifBars/blender-agent-studio/commit/ef707f828410ab2059424cad15925e24c975cbd3) | 2026-09-28 |
| [richard-guyunqi/BlenderGym-Open](https://github.com/richard-guyunqi/BlenderGym-Open) | [67c8b48bf8c5](https://github.com/richard-guyunqi/BlenderGym-Open/commit/67c8b48bf8c548c701b6873db6fcc6527d756385) | 2025-07-08 |
| [yunlong10/BVB](https://github.com/yunlong10/BVB) | [69b7a488e972](https://github.com/yunlong10/BVB/commit/69b7a488e972b648819cc12cd2752256f84efbc3) | 2026-09-28 |

License values in the manifest are GitHub metadata at retrieval, not legal clearance. Missing/`NOASSERTION` metadata does not establish permission; inspect the actual license before reuse. LL3M's evaluation restrictions deserve particular attention. Do not copy upstream code merely because its architecture is useful.

The largest remaining uncertainty is **real edit-to-review reliability on our Windows/Houdini workload**. This report establishes patterns and source-backed capabilities, not a winner under that workload. The next evidence should come from bounded disposable comparisons with the same scene, quality criteria and budgets—not from adding tools until the catalog becomes larger.
