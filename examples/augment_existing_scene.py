#!/usr/bin/env python3
"""
HDMCP-10 Example 2: Augment Existing Scene
===========================================

Demonstrates augmenting an existing node network by inserting a new node:
grid → noise  becomes  grid → mountain → noise

This example shows:
- Using list_children to discover existing network topology
- Using get_node_info to see current connections
- Creating a new mountain SOP node
- Inserting mountain between grid and noise using wiring tools
- Verifying geometry changed with get_geo_summary
"""

import requests
import json
from typing import Dict, Any, List

# MCP server URL
MCP_URL = "http://localhost:3055"


def call_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """Call an MCP tool and return the result."""
    response = requests.post(
        f"{MCP_URL}/tools/{tool_name}",
        json=kwargs
    )
    response.raise_for_status()
    result = response.json()
    
    # Check for error status
    if isinstance(result, dict) and result.get("status") == "error":
        raise RuntimeError(f"Tool error: {result.get('message', 'Unknown error')}")
    
    return result


def find_node_by_type(children: List[Dict[str, Any]], node_type: str) -> Dict[str, Any]:
    """Find first node matching the given type."""
    for child in children:
        if child["type"] == node_type:
            return child
    raise ValueError(f"No node of type '{node_type}' found")


def main():
    """Augment existing scene by inserting a mountain node."""
    
    print("=" * 70)
    print("HDMCP-10 Example 2: Augment Existing Scene")
    print("Insert mountain between grid → noise")
    print("=" * 70)
    
    # Step 1: Create initial network (grid → noise)
    print("\n[Setup] Creating initial network: grid → noise...")
    
    # Create geo container
    geo_result = call_tool(
        "create_node",
        node_type="geo",
        parent_path="/obj",
        name="augment_example"
    )
    geo_path = geo_result["node_path"]
    print(f"✓ Created: {geo_path}")
    
    # Create grid
    grid_result = call_tool(
        "create_node",
        node_type="grid",
        parent_path=geo_path,
        name="grid1"
    )
    grid_path = grid_result["node_path"]
    print(f"✓ Created: {grid_path}")
    
    # Create noise
    noise_result = call_tool(
        "create_node",
        node_type="noise",
        parent_path=geo_path,
        name="noise1"
    )
    noise_path = noise_result["node_path"]
    print(f"✓ Created: {noise_path}")
    
    # Wire grid → noise
    call_tool(
        "connect_nodes",
        src_path=grid_path,
        dst_path=noise_path,
        dst_input_index=0
    )
    print(f"✓ Wired: grid → noise")
    
    # Set display flag on noise
    call_tool("set_node_flags", node_path=noise_path, display=True)
    print(f"✓ Set display flag on noise")
    
    print(f"\n{'='*70}")
    print("Initial network created successfully!")
    print(f"{'='*70}")
    
    # Step 2: Use list_children to discover network topology
    print("\n[Step 1] Using list_children to discover network topology...")
    children_result = call_tool(
        "list_children",
        node_path=geo_path,
        recursive=False
    )
    
    print(f"\nFound {children_result['count']} nodes in {geo_path}:")
    for child in children_result['children']:
        inputs_str = f"{len(child['inputs'])} inputs" if child['inputs'] else "no inputs"
        outputs_str = f"{len(child['outputs'])} outputs" if child['outputs'] else "no outputs"
        print(f"  - {child['name']} ({child['type']}): {inputs_str}, {outputs_str}")
        
        # Show input details
        if child['inputs']:
            for inp in child['inputs']:
                print(f"      Input {inp['index']}: {inp['source_node']} [output {inp['output_index']}]")
    
    # Step 3: Use get_node_info to see current connections
    print("\n[Step 2] Using get_node_info to inspect noise node connections...")
    noise_info = call_tool(
        "get_node_info",
        node_path=noise_path,
        include_params=False,
        include_input_details=True
    )
    
    print(f"\nNoise node info:")
    print(f"  Path: {noise_info['path']}")
    print(f"  Type: {noise_info['type']}")
    print(f"  Inputs: {noise_info['inputs']}")
    
    if noise_info.get('input_connections'):
        print(f"  Input connections:")
        for conn in noise_info['input_connections']:
            print(f"    Input {conn['input_index']}: {conn['source_node']} [output {conn['source_output_index']}]")
    
    # Store original connection info
    original_source = noise_info['inputs'][0] if noise_info['inputs'] else None
    print(f"\n✓ Original connection: {original_source} → noise")
    
    # Step 4: Get geometry summary BEFORE inserting mountain
    print("\n[Step 3] Getting geometry summary BEFORE mountain insertion...")
    geo_before = call_tool(
        "get_geo_summary",
        node_path=noise_path,
        max_sample_points=5,
        include_attributes=True
    )
    
    print(f"\nGeometry BEFORE:")
    print(f"  Points: {geo_before['point_count']}")
    print(f"  Primitives: {geo_before['primitive_count']}")
    if geo_before.get('bounding_box'):
        bbox = geo_before['bounding_box']
        print(f"  Bounding box size: {bbox['size']}")
    
    # Step 5: Create mountain SOP
    print("\n[Step 4] Creating mountain node...")
    mountain_result = call_tool(
        "create_node",
        node_type="mountain",
        parent_path=geo_path,
        name="mountain1"
    )
    mountain_path = mountain_result["node_path"]
    print(f"✓ Created: {mountain_path}")
    
    # Step 6: Set mountain parameters
    print("\n[Step 5] Setting mountain parameters...")
    call_tool(
        "set_parameter",
        node_path=mountain_path,
        param_name="height",
        value=2.0
    )
    print(f"✓ Set mountain height: 2.0")
    
    # Step 7: Insert mountain between grid and noise
    print("\n[Step 6] Inserting mountain between grid and noise...")
    
    # First, disconnect noise from grid
    print("  Disconnecting noise input 0...")
    call_tool(
        "disconnect_node_input",
        node_path=noise_path,
        input_index=0
    )
    print("  ✓ Disconnected")
    
    # Connect grid → mountain
    print("  Connecting grid → mountain...")
    call_tool(
        "connect_nodes",
        src_path=grid_path,
        dst_path=mountain_path,
        dst_input_index=0
    )
    print("  ✓ grid → mountain")
    
    # Connect mountain → noise
    print("  Connecting mountain → noise...")
    call_tool(
        "connect_nodes",
        src_path=mountain_path,
        dst_path=noise_path,
        dst_input_index=0
    )
    print("  ✓ mountain → noise")
    
    # Step 8: Verify new connections with get_node_info
    print("\n[Step 7] Verifying new connections with get_node_info...")
    noise_info_after = call_tool(
        "get_node_info",
        node_path=noise_path,
        include_params=False,
        include_input_details=True
    )
    
    print(f"\nNoise node info AFTER insertion:")
    print(f"  Inputs: {noise_info_after['inputs']}")
    if noise_info_after.get('input_connections'):
        for conn in noise_info_after['input_connections']:
            print(f"    Input {conn['input_index']}: {conn['source_node']} [output {conn['source_output_index']}]")
    
    # Step 9: Get geometry summary AFTER inserting mountain
    print("\n[Step 8] Getting geometry summary AFTER mountain insertion...")
    geo_after = call_tool(
        "get_geo_summary",
        node_path=noise_path,
        max_sample_points=5,
        include_attributes=True
    )
    
    print(f"\nGeometry AFTER:")
    print(f"  Points: {geo_after['point_count']}")
    print(f"  Primitives: {geo_after['primitive_count']}")
    if geo_after.get('bounding_box'):
        bbox = geo_after['bounding_box']
        print(f"  Bounding box size: {bbox['size']}")
    
    # Step 10: Compare geometry
    print(f"\n{'='*70}")
    print("COMPARISON")
    print(f"{'='*70}")
    
    if geo_before.get('bounding_box') and geo_after.get('bounding_box'):
        size_before = geo_before['bounding_box']['size']
        size_after = geo_after['bounding_box']['size']
        
        print(f"\nBounding box size change:")
        print(f"  Before: {size_before}")
        print(f"  After:  {size_after}")
        
        # Check if Z changed (mountain should affect height)
        if size_after[1] > size_before[1]:
            print(f"  ✓ Y-size increased by {size_after[1] - size_before[1]:.4f}")
            print(f"    (Mountain effect visible!)")
    
    # Step 11: Show final network structure
    print(f"\n{'='*70}")
    print("✓ AUGMENTATION COMPLETE!")
    print(f"{'='*70}")
    
    final_children = call_tool(
        "list_children",
        node_path=geo_path,
        recursive=False
    )
    
    print(f"\nFinal network structure in {geo_path}:")
    for child in final_children['children']:
        symbol = "└─" if child == final_children['children'][-1] else "├─"
        display = " [DISPLAY]" if child['name'] == 'noise1' else ""
        print(f"  {symbol} {child['name']} ({child['type']}){display}")
        
        if child['inputs']:
            for inp in child['inputs']:
                print(f"       ↑ from {inp['source_node'].split('/')[-1]}")
    
    print(f"\nSuccessfully inserted mountain node into existing network!")
    print(f"New flow: grid → mountain → noise")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
