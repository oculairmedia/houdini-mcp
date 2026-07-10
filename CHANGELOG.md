# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Remote hrpyc listener activation** (`houdini_mcp_plugin.listener`): the
  Houdini plugin can now start/stop/reload a remotely reachable hrpyc listener
  with an explicit, configurable bind address/port
  (`HOUDINI_RPC_BIND_HOST` / `HOUDINI_RPC_BIND_PORT`). Start/stop/reload are
  idempotent, and a self-test reports the actual bound endpoints, reachability,
  a loopback-only warning, per-OS firewall guidance, and Houdini/plugin/protocol
  versions. New shelf tools: **Remote Status** and **Remote Self-Test**.
- **Remote listener security policy**: non-loopback binds (`0.0.0.0` or a LAN IP)
  are refused unless explicitly opted into via `HOUDINI_RPC_TRUSTED_NETWORK=1`
  or an authentication token `HOUDINI_RPC_TOKEN`. No code path silently binds
  `0.0.0.0` without auth. Documented in `docs/remote-listener.md` (including
  limitations: token is a shared-secret handshake, not TLS).
- **Opt-in live verification**: `scripts/verify_remote_listener.py` performs a
  read-only reachability/version check against an already-running listener
  (gated by `RUN_LIVE_REMOTE_CHECK=1`); it never starts/stops/restarts Houdini.
- **execute_code safety rails (policy profiles + rollback)**: `execute_code` now
  supports explicit policy profiles (`read-only`, `normal`, `privileged`).
  `read-only` blocks any scene mutation before execution; `privileged` requires
  the server bypass config gate. Bypass flags (`allow_dangerous`,
  `allow_heavy_geometry`) now require BOTH the request flag AND server config
  (`HOUDINI_MCP_ALLOW_BYPASS=true`) and fail closed otherwise. Dangerous-pattern
  detection was expanded to cover network egress (`socket`, `urllib`, `requests`,
  `http`), dynamic execution (`eval`/`exec`/`compile`/`__import__`), and trivial
  whitespace obfuscation. Every call returns a structured `audit` block (policy,
  requested bypasses, detected patterns, code hash, timeout/rollback state) and
  blocked/executed bypass attempts are logged. On timeout the run's undo group is
  reverted via `hou.undos.performUndo()` when a usable undo primitive exists;
  if none exists the call fails closed and reports that partial mutations may be
  untracked. Note: the timed-out code runs in a daemon thread that Python cannot
  forcibly kill, so `performUndo()` is a best-effort revert of what was recorded
  up to that point, not a guarantee the scene stays consistent — the thread may
  still be running and mutating the scene concurrently, and the response
  explicitly reports that risk (`rollback.thread_still_running`) instead of
  claiming a hard rollback guarantee.
- **Heavy geometry guard**: `execute_code` now detects and blocks direct SOP
  geometry access (`node.geometry()`, `geo.points()`, `geo.prims()`,
  `geo.vertices()`, `geo.iterPoints()`, `geo.iterPrims()`) which can stall the
  UI or drop the hrpyc connection on large scenes. Pass `allow_heavy_geometry=True`
  to opt in, or prefer `get_geo_summary()` for bounded inspection.
- **Windows/Codex Desktop setup guide**: `docs/codex-windows-setup.md` documents
  running the stdio MCP server outside Houdini against an `hrpyc` listener.

### Changed

- **BREAKING (safety)**: `execute_code` bypass flags no longer take effect on
  request alone. `allow_dangerous`/`allow_heavy_geometry` now also require the
  server to enable `HOUDINI_MCP_ALLOW_BYPASS`; without it the call fails closed.
- **BREAKING (default behavior)**: `execute_code` rejects heavy geometry access by
  default (see above). Existing callers that rely on raw geometry access must now
  pass `allow_heavy_geometry=True`.
- **stdio transport**: The stdio server no longer passes `host`/`port` and
  suppresses the FastMCP startup banner so stdout stays JSON-RPC clean.

### Fixed

- **hrpyc remote stop**: The Houdini plugin now starts the listener via
  `hrpyc.ThreadedServer` and stops it through the server object's `close()`,
  replacing the missing `hrpyc.stop_server()` API. The bind host defaults to
  `127.0.0.1` and is configurable via `HOUDINI_RPC_BIND_HOST`.
- **CI**: Added the missing `hypothesis` test dependency (used by the
  `execute_code` safety-rail property/fuzz tests) to the `dev` extra,
  `requirements.txt`, and the CI fallback install list.

## [1.0.0] - 2025-12-28

### Added

#### Core Tools
- **Scene Management**: `get_scene_info`, `save_scene`, `load_scene`, `new_scene`, `serialize_scene`
- **Node Operations**: `create_node`, `delete_node`, `get_node_info`, `list_children`, `find_nodes`, `list_node_types`
- **Node Wiring**: `connect_nodes`, `disconnect_node_input`, `reorder_inputs`, `set_node_flags`
- **Parameters**: `set_parameter`, `get_parameter_schema`
- **Geometry**: `get_geo_summary` with point/primitive counts, bounding box, and attribute metadata
- **Materials**: `create_material`, `assign_material`, `get_material_info`
- **Rendering**: `render_viewport`, `render_quad_view` (4 canonical views in one call)
- **Render Configuration**: `list_render_nodes`, `get_render_settings`, `set_render_settings`, `create_render_node`
- **Layout**: `layout_children`, `set_node_position`, `set_node_color`, `create_network_box`
- **Error Introspection**: `find_error_nodes` with cook state and error/warning details
- **Code Execution**: `execute_code` with safety rails and scene diff tracking
- **Documentation**: `get_houdini_help` fetches SideFX documentation for nodes and VEX functions

#### Houdini Plugin
- **stdio MCP mode**: Run MCP server directly inside Houdini without network configuration
- **Shelf tools**: Start MCP, Stop MCP, MCP Status, Start Remote, Stop Remote
- **Package configuration**: Easy installation via Houdini packages system

#### Performance Optimizations
- **Node type caching**: First call fetches and caches all node types; subsequent calls filter from cache (<1ms)
- **Parameter schema caching**: Cached per node type for instant repeated queries
- **Response pagination**: `offset`, `max_results`, `has_more`, `next_offset` for large result sets
- **Response size metadata**: Automatic warnings for large responses with size estimates
- **Parallel execution utilities**: `semaphore_gather`, `batch_items`, `run_in_executor` for bounded concurrency

#### Architecture
- **Modular tools structure**: All tools organized in `houdini_mcp/tools/` with separate modules:
  - `_common.py` - Shared utilities and connection management
  - `cache.py` - In-memory caching infrastructure
  - `code.py` - Python code execution
  - `errors.py` - Error introspection
  - `geometry.py` - Geometry operations
  - `help.py` - Documentation fetching
  - `hscript.py` - HScript execution
  - `layout.py` - Node organization
  - `materials.py` - Material operations
  - `nodes.py` - Node operations
  - `parameters.py` - Parameter operations
  - `rendering.py` - Viewport and ROP rendering
  - `scene.py` - Scene management
  - `summarization.py` - AI-powered summarization
  - `wiring.py` - Node connections

#### Reliability
- **Connection retry with exponential backoff**: Automatic reconnection on connection loss
- **Jitter for thundering herd prevention**: Randomized delays to prevent connection storms
- **Comprehensive error handling**: Graceful handling of RPyC connection errors
- **394 unit tests**: Comprehensive test coverage for all tools

### Changed
- Upgraded from monolithic `tools.py` to modular package structure
- Improved node type validation in `connect_nodes` (validates SOP/OBJ compatibility)
- Enhanced `get_node_info` with optional error introspection and compact mode

### Fixed
- RPyC 6.x compatibility issues (pinned to 5.x for hrpyc compatibility)
- Remote file operations now correctly use RPyC's remote modules

## [0.3.0] - 2025-12-27

### Added
- Initial public release
- Basic MCP server with hrpyc integration
- Core scene and node operations

[1.0.0]: https://github.com/oculairmedia/houdini-mcp/compare/v0.3.0...v1.0.0
[0.3.0]: https://github.com/oculairmedia/houdini-mcp/releases/tag/v0.3.0
