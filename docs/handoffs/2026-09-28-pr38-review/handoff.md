# PR #38 review fixes

Review base: `a0d50af`. Date: 2026-09-28. Branch: `spike/persistent-houdini-companion`.
This handoff records repairs and acceptance evidence; it is not a new architecture decision.

| Bead | Finding | Repair and evidence |
|---|---|---|
| `houdini-mcp-vzp.33` | Copy Save As clears the artist's dirty indicator | Copy uses `saveAsBackup` for an accessible original HIP, and native `mwrite -n` for a never-saved/inaccessible original. It stages in an owned directory and exclusively creates the destination. The original path/dirty state is checked on success. Disposable GUI checks cover clean, dirty, never-saved and injected-failure cases; the original file's hash remains unchanged. `activate=true` intentionally retains Save As behavior. |
| `.34` | Delete/recreate rebinds an observed path to another node | Preflight returns bound node references and tracks deletion of paths/ancestor aliases. Literal reuse is rejected before mutation; newly created nodes require explicit aliases. Execution checks session identity rather than binding paths again. Unit and real-HOM tests cover rejected literal replacement and accepted explicit aliases. |
| `.35` | Token written before permissions are restrictive | Atomic JSON uses unique exclusive temporary files. POSIX `mkstemp` is 0600 at creation; Windows `CreateFileW` receives a protected current-user/System DACL at creation. Permission failure does not publish; startup failure shuts down the listener and unregisters callbacks. Windows tests inspect the empty temporary file's ACL before bytes are written and after publication. |
| `.36` | Scene reset/shutdown loses verifier handles | Saved receipts and worker records survive scene reset, stay queryable/accounted/pinned, and runtime shutdown cancels timers and terminates/reaps workers. A real GUI BeforeClear test retains a long-running hython stand-in; real subprocess tests verify the two-worker limit after reset and process exit after stop. The separate workflow uses actual `save.verify` workers. Preferences now use the required `__HVER__` placeholder. |
| `.37` | Anchor-only checks align old images with new geometry | Render rows record a source observation at their exact frame and a semantic geometry signature. Boundary/publication validate sampled source, geometry, frame binding and strict artifact hashes; fixed cameras are checked at the anchor. A real frame-dependent file source is changed only at the non-anchor frame and rejected while time is restored. |
| `.38` | Promotion does not enforce completed review | `build.stage` declares `review_frames` (default: staging frame). `review.publish` produces a tracked digest-bound `review_id`; promotion requires the complete published samples, intact artifacts and unchanged candidate. Missing, partial, stale and corrupt evidence is rejected. A valid receipt is consumed on promotion. `review.release` unpins unused receipts without deleting published files. The Relativity demo and all five variant build commands now pass review IDs and declare their five required poses. |

Affected build, delivery, boundary, sequence and publication plugins advertise version 0.2.0.
The catalog contains 14 built-in plugins and 43 operations. Plugin API/protocol remain v1.
Older render rows without per-frame evidence require re-rendering. The current artist runtime
was not reloaded; changes are committed/tested code, not a claim of deployment into that process.

## Evidence

- [Summary and checksums](summary.json).
- [Disposable GUI acceptance](disposable-gui.json): seven grouped checks, Houdini 20.5.278.
- [Disposable hython workflow](disposable-hython.json): eight grouped checks, including actual isolated saved-HIP reopen, changed dependencies, rendering and boundary failures.
- [Rendered review sample 1](review-frame-0.png) and [sample 2](review-frame-1.png). The fixture is intentionally a simple box; the tests evaluate failure contracts, not artistic scene quality.
- 26 regression cases in [the test module](../../../tests/test_companion_review_regressions.py).
- Earlier 22-case subset against isolated `a0d50af`: 21 failed/1 passed. This includes a direct dirty-state reproduction; other failures include newly required interfaces. It is not 21 distinct Houdini runtime defects.

The local full suite uses UTF-8 mode because pre-existing document tests call
`read_text()` without an encoding and fail under Windows' default CP1252. See the
summary for the final counts. Ruff and documentation-link checks also pass.

Run portable checks from the repository:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/ -q -m 'not integration'
```

Run the disposable GUI acceptance, which creates a new directory and launches a
separate hidden process with isolated versioned preferences:

```powershell
.\.venv\Scripts\python.exe scripts/run_companion_review_acceptance.py --hfs 'C:\Program Files\Side Effects Software\Houdini 20.5.278'
```

Run the expanded workflow with `hython.exe scripts/verify_companion_workflow.py NEW_DIRECTORY`
in an isolated environment (`HOUDINI_COMPANION_AUTOSTART=0`, a versioned
`HOUDINI_USER_PREF_DIR`, and `HOUDINI_NO_ENV_FILE=1`). The scripts never open an artist HIP.
Raw JSON records contain local historical evidence paths and IDs; rediscover live identities
for future operations instead of replaying those IDs.

## Limits and PM reporting

A review receipt certifies complete, source-aligned sampled evidence, not aesthetic
approval, exhaustive clearance or continuous-time correctness. Geometry comparison
covers supported topology/scalar/tuple attributes; it is not universal simulation or
primitive-intrinsic equivalence. Native cooks/renders can still block. No crash-atomic
recovery or automatic replay is claimed. The broader restart/install, portable
packaging, recovery, animated pre-apply review, external lifecycle and scorecard
Beads `.15`–`.20` remain separate and open.

The artist's live HIP, cameras, timeline and uncommitted town sources were not edited,
saved, reloaded or committed. Test HIPs and scene resets belong only to disposable processes.
No Matrix/Letta/Graphiti connector was available; this committed handoff and Beads
evidence are the PM record. Direct PM message delivery is not claimed. Huly remains deprecated.
