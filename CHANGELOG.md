# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
