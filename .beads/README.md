# Beads tracker

The active issue database is Dolt on `origin/main`, stored through
`git+https://github.com/oculairmedia/houdini-mcp.git` at `refs/dolt/data`.
This is separate from the project Git branch.

Read [Windows Beads operation](../docs/windows-beads.md) for verified versions,
non-destructive clone/bootstrap, sync commands and reconciliation evidence.

- `.beads/issues.jsonl` is a preserved historical export of 62 records.
- Local database/runtime files are ignored. Do not commit tokens or Dolt files.
- Do not run `bd init` or import the historical export to replace the tracker.
- `bd sync` is unsupported on the verified Windows Beads 1.1.0 installation.
- Huly is deprecated. Old Huly labels are historical provenance only.

```powershell
bd dolt pull
bd ready
bd show houdini-mcp-vzp.15
# Update only explicit issue IDs and attach acceptance evidence.
bd vc status
# Commit pending issue changes if the effective policy did not auto-commit them.
bd dolt push
```

A Git push publishes code and documentation. It does not publish issue updates;
use `bd dolt push` and verify the remote state separately.
