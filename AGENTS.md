<!-- VIBESYNC:project-info:START -->
# Agent Instructions

## Project Tracking

- **Project Code**: `HDMCP`
- **Project Name**: Houdini MCP Server
- **Letta Agent ID**: `agent-0a0867cb-09a4-4a9d-ad97-884773b7cbbc`

Huly is deprecated (user confirmed 2026-09-27). Use the authoritative Beads/Dolt
tracker for active issues. Historical `huly:HDMCP-*` labels are provenance only;
do not require Huly access, create new Huly mappings or block work on Huly sync.
Read the assigned Bead and its dependencies before implementation. Store important
discoveries in Graphiti when its connector is available.
<!-- VIBESYNC:project-info:END -->

<!-- VIBESYNC:reporting-hierarchy:START -->
## PM Agent Communication

**Project PM Agent:** Letta agent `agent-0a0867cb-09a4-4a9d-ad97-884773b7cbbc` (legacy display name `Huly - Houdini MCP Server`; Huly tracking is deprecated).

### Reporting Hierarchy

```
Emmanuel (Stakeholder)
    ↓
Meridian (Director of Engineering)
    ↓
PM Agent (Technical Product Owner - mega-experienced)
    ↓ communicates with
You (Developer Agent - experienced)
```

### MANDATORY: Report to PM Agent

**BEFORE reporting outcomes to the user**, send a report to the PM agent via Matrix:

```json
{
  "operation": "talk_to_agent",
  "agent": "Huly - Houdini MCP Server",
  "message": "<your report>",
  "caller_directory": "/opt/stacks/houdini-mcp"
}
```

### When to Contact PM Agent

| Situation             | Action                                                              |
| --------------------- | ------------------------------------------------------------------- |
| Task completed        | Report outcome to PM before responding to user                      |
| Blocking question     | Forward to PM - they know user's wishes and will escalate if needed |
| Architecture decision | Consult PM for guidance                                             |
| Unclear requirements  | PM can clarify or contact user                                      |

### Report Format

```
**Status**: [Completed/Blocked/In Progress]
**Task**: [Brief description]
**Outcome**: [What was done/What's blocking]
**Files Changed**: [List if applicable]
**Next Steps**: [If any]
```
<!-- VIBESYNC:reporting-hierarchy:END -->

<!-- VIBESYNC:beads-instructions:START -->
## Beads Issue Tracking

The authoritative tracker is Dolt. Read [Windows Beads operation](docs/windows-beads.md)
for the verified Windows setup, non-destructive bootstrap and reconciliation evidence.
The checked-in 62-record `.beads/issues.jsonl` is historical; preserve it and do not
import it over the remote. Do not run `bd init` to replace a missing database.

```bash
bd dolt pull                         # Fetch issue history (separate from Git code)
bd ready                             # Ready work, respecting recorded dependencies
bd show <id>                         # Read acceptance criteria
bd update <id> --status in_progress
bd comments add <id> -f evidence.txt
bd close <id>                        # Only when its full acceptance criteria pass
bd dolt commit -m "Describe changes" # If effective auto-commit left pending writes
bd dolt push                         # Publish issue data; Git push is separate
```

Windows Beads is pinned to 1.2.2 to match the Linux PM; use the Dolt commands above
for synchronization. Inspect `bd context`, the effective
commit policy and `bd vc status`; do not assume Linux uses the same backend mode.
Do not force-push divergent tracker history. Huly is deprecated; retained Huly
labels are historical provenance and are not part of the active sync workflow.
<!-- VIBESYNC:beads-instructions:END -->

<!-- VIBESYNC:bookstack-docs:START -->
## BookStack Documentation

- **Source of truth**: [BookStack](https://knowledge.oculair.ca)
- **Local sync**: `docs/bookstack/` (read-only mirror, syncs hourly)
- **To read docs**: Check `docs/bookstack/{book-slug}/` in your project directory
- **To create/edit docs**: Use `bookstack-mcp` tools to write directly to BookStack
- **Never edit** files in `docs/bookstack/` locally — they will be overwritten on next sync
- **PRDs and design docs** must be stored in BookStack, not local markdown files
<!-- VIBESYNC:bookstack-docs:END -->

<!-- VIBESYNC:session-completion:START -->
## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push  # Commit pending issue changes first if needed
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- VIBESYNC:session-completion:END -->

<!-- VIBESYNC:codebase-context:START -->
## Codebase Context

**Project**: Houdini MCP Server (`HDMCP`)
**Path**: `/opt/stacks/houdini-mcp`

This project's PM agent has a `codebase_ast` memory block with live structural data including:

- File counts and function counts per directory
- Key modules and their roles
- Quality signals (doc gaps, untested modules, complexity hotspots)
- Recent file changes

Ask the PM agent for architectural guidance before making significant changes.
<!-- VIBESYNC:codebase-context:END -->

## Architecture Decisions (ADRs)

Architecture Decision Records live in [`docs/adr/`](docs/adr/). Read them before
proposing structural or language changes:

- [ADR 0001: Language and Process Boundaries](docs/adr/0001-language-and-process-boundaries.md)
  — the server stays Python for `hou` semantics and the FastMCP gateway. A
  non-Python sidecar is authorized **only** when a measured threshold in that ADR
  is crossed and only behind a versioned, language-neutral protocol; a sidecar
  must never duplicate `hou`/node/geometry semantics. No rewrite is authorized
  without a follow-up bead backed by profiling.

# Agent Instructions

This project uses **bd** with an authoritative Dolt tracker. See [Windows Beads operation](docs/windows-beads.md) before setup or recovery.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd dolt pull          # Fetch issue data
bd dolt push          # Publish issue data separately from Git
```

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push  # Commit pending issue changes first if needed
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
