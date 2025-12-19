# Houdini MCP Server Documentation

## Implementation Details

Detailed implementation notes for each feature in the SOP Workflow MVP:

| Document | Feature | Issue |
|----------|---------|-------|
| [overview.md](implementation/overview.md) | Implementation summary | - |
| [network-introspection.md](implementation/network-introspection.md) | list_children, find_nodes, get_node_info | HDMCP-5 |
| [node-wiring.md](implementation/node-wiring.md) | connect_nodes, disconnect, flags, reorder | HDMCP-6 |
| [parameter-schema.md](implementation/parameter-schema.md) | get_parameter_schema | HDMCP-7 |
| [error-introspection.md](implementation/error-introspection.md) | get_node_info with errors | HDMCP-8 |
| [geometry-summary.md](implementation/geometry-summary.md) | get_geo_summary | HDMCP-9 |
| [examples-docs.md](implementation/examples-docs.md) | Example workflows | HDMCP-10 |

## Quick Reference

Quick reference guides for using the tools:

| Document | Description |
|----------|-------------|
| [quick-reference.md](reference/quick-reference.md) | General quick reference |
| [error-introspection-ref.md](reference/error-introspection-ref.md) | Error introspection usage |
| [geometry-summary-ref.md](reference/geometry-summary-ref.md) | Geometry summary usage |
| [examples-ref.md](reference/examples-ref.md) | Example patterns reference |

## Examples

See the [examples/](../examples/) directory for complete runnable examples:

- `build_from_scratch.py` - Create sphere -> xform -> color -> OUT chain
- `augment_existing_scene.py` - Insert node into existing chain
- `parameter_workflow.py` - Discover and set parameters
- `error_handling.py` - Detect and handle errors
