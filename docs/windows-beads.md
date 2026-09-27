# Windows Beads and Dolt operation

Verified 2026-09-27 for `houdini-mcp-vzp.13` in `C:\houdini mcp\g`.

The issue tracker is Dolt, independently synchronized from the project Git branch.
`git push` publishes code; `bd dolt push` publishes issue data. The checked-in
`.beads/issues.jsonl` is a historical 62-record export, not the active database.
Preserve it. Do not import it over the authoritative tracker or use `bd init` to
work around a missing local database.

## Verified configuration

| Setting | Value |
| --- | --- |
| Windows Beads | 1.1.0, build `8e4e59d39`, `C:\Users\Emmanuel\bin\bd.exe` |
| Linux PM Beads (PM-reported) | 1.2.2, build `6c124203e` |
| Windows Dolt CLI | 2.0.1, `C:\Program Files\Dolt\bin\dolt.exe` |
| Backend | Embedded Dolt, database `beads` |
| Local data | `.beads/embeddeddolt/beads` (ignored by Git) |
| Dolt branch | `main`, independent of `spike/persistent-houdini-companion` |
| Dolt origin | `git+https://github.com/oculairmedia/houdini-mcp.git` |
| Git transport ref | `refs/dolt/data` |
| Effective auto-commit | `on`, queried from the cloned tracker |

This is the combination exercised on Windows, not a requirement to upgrade the
Linux PM or switch its backend. The installed command help refers generally to
SQL-server mode, but `bd context` reports this installation's embedded mode.
`schema_version: 1` in JSON command output is not evidence of the SQL migration
version. The Linux PM reported recovery to schema v53 separately.

Bootstrap rewrites local `.beads/metadata.json` to select Dolt and may update
`.beads/last-touched`. Those host-generated changes are intentionally excluded
from the Windows reconciliation code commit; do not overwrite Linux metadata
with the Windows embedded configuration. Shared `sync.remote` and ignore rules
are committed. Credentials and database contents are not.

## Recover a fresh Windows checkout

1. Read the repo instructions and inspect `git status`; preserve artist changes.
2. Back up `.beads/issues.jsonl`, `interactions.jsonl`, `metadata.json` and
   `config.yaml` outside the repository. Record their SHA-256 values.
3. Run `bd bootstrap --dry-run --json` and inspect the plan. For this repository,
   it must select **sync/clone from the verified Dolt remote**. If it selects a
   fresh database or JSONL import instead, stop and resolve the missing remote.
4. Run `bd bootstrap --yes --json` only after that plan is verified. The observed
   clone downloaded existing Dolt history and did not import/replace the export.
5. Verify `bd --readonly context --json`, `bd --readonly dolt remote list --json`,
   `bd --readonly status --json`, and `bd --readonly ready --json`.
6. Confirm `houdini-mcp-vzp.13` through `.21` exist before updating them. Do not
   recreate unpublished PM records. Ask the PM to publish their Dolt commits if
   records are absent.

The successful clone had 87 issues. All 62 historical IDs, all historical comment
text and all historical dependency edges were retained in the authoritative
records. Historical field differences are recorded in the reconciliation report;
the historical issues export remains byte-identical. The interaction log retains
its original byte prefix and receives normal appended Beads audit records. Duplicate Huly labels are evidence to
review, not authorization to merge issues.

## Normal issue workflow

```powershell
Set-Location 'C:\houdini mcp\g'
bd dolt pull
bd --readonly ready --parent houdini-mcp-vzp --json
bd --readonly show houdini-mcp-vzp.13 --json
bd --actor Codex update houdini-mcp-vzp.13 --status in_progress
# Perform the work and record evidence against the explicit issue ID.
bd --actor Codex comments add houdini-mcp-vzp.13 -f evidence.txt
bd --readonly vc status --json
# If writes remain uncommitted under the effective auto-commit policy:
bd dolt commit -m 'Describe the issue updates'
bd dolt push
```

Check the actual result after each step. Pull before publishing if the PM has
updated the remote. Resolve divergent history normally; do not force-push or
flatten it. Keep Git code commits and Dolt issue commits separate. Always pass an
issue ID: commands that use a last-touched default can target the wrong record.

`bd sync` is unsupported in Windows Beads 1.1.0. Do not assume a SQLite watcher
automatically updates Huly. Huly, BookStack and Matrix/Letta require their own
available connectors and explicit verification. Beads labels alone do not prove
the current state of the Huly issue.

`bd sql` is not implemented in this installed embedded mode. Prefer supported
Beads commands. The installed Dolt CLI can inspect the database directly when no
Beads operation is running; do not bypass Beads with direct SQL mutations.

## Acceptance and tracking limits

The full reconciliation and delivery mapping are in
[`handoffs/2026-09-27-companion-pm/windows-reconciliation.json`](handoffs/2026-09-27-companion-pm/windows-reconciliation.json)
and [`delivery-crosswalk.json`](handoffs/2026-09-27-companion-pm/delivery-crosswalk.json).

Local HTTP companion delivery does not close the hosted outbound integration
(`vzp.9`, `9sx`, `6pt`), the full live acceptance harness (`vzp.3`), general
telemetry (`vzp.11`) or all-wrapper transaction integration (`vzp.2`, `028`). The
older sans-I/O WebSocket core `xu4` was already closed upstream; it was not closed
by this reconciliation. The companion epic remains open.

The active delivery mapping is GitHub↔Beads, with Huly marked deprecated. The
user correction supersedes the historical Huly requirement in the PM intake.
Readiness follows recorded dependencies; closing `.14` releases `.16` and `.17`,
while `.15`, `.18` and `.20` do not depend on `.14`. Optional `.21` still requires
artist scope. A numerically earlier child is not automatically a blocker.
