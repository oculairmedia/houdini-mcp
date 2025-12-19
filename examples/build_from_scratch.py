#!/usr/bin/env python3
"""
HDMCP-10 Example 1: Build from Scratch
======================================

Demonstrates building a complete SOP network from scratch:
sphere → xform → color → OUT

This example shows:
- Creating a geo container at /obj
- Creating SOP nodes (sphere, xform, color, null)
- Wiring nodes together sequentially
- Setting display flag on OUT node
- Setting parameters on each node
- Verifying results with get_geo_summary
"""

import requests
import json
from typing import Dict, Any

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


def main():
    """Build a complete SOP network from scratch."""
    
    print("=" * 70)
    print("HDMCP-10 Example 1: Build from Scratch")
    print("Building: sphere → xform → color → OUT")
    print("=" * 70)
    
    # Step 1: Create geo container at /obj
    print("\n[Step 1] Creating geo container at /obj...")
    geo_result = call_tool(
        "create_node",
        node_type="geo",
        parent_path="/obj",
        name="example_geo"
    )
    geo_path = geo_result["node_path"]
    print(f"✓ Created: {geo_path}")
    
    # Step 2: Create sphere SOP
    print("\n[Step 2] Creating sphere node...")
    sphere_result = call_tool(
        "create_node",
        node_type="sphere",
        parent_path=geo_path,
        name="sphere1"
    )
    sphere_path = sphere_result["node_path"]
    print(f"✓ Created: {sphere_path}")
    
    # Step 3: Set sphere parameters (radius = 2.0)
    print("\n[Step 3] Setting sphere radius to 2.0...")
    call_tool(
        "set_parameter",
        node_path=sphere_path,
        param_name="rad",
        value=[2.0, 2.0, 2.0]  # XYZ radius
    )
    print(f"✓ Set sphere radius: [2.0, 2.0, 2.0]")
    
    # Step 4: Create transform node
    print("\n[Step 4] Creating transform (xform) node...")
    xform_result = call_tool(
        "create_node",
        node_type="xform",
        parent_path=geo_path,
        name="xform1"
    )
    xform_path = xform_result["node_path"]
    print(f"✓ Created: {xform_path}")
    
    # Step 5: Set transform parameters (translate Y = 3.0)
    print("\n[Step 5] Setting transform translate Y = 3.0...")
    call_tool(
        "set_parameter",
        node_path=xform_path,
        param_name="t",
        value=[0.0, 3.0, 0.0]  # XYZ translate
    )
    print(f"✓ Set translate: [0.0, 3.0, 0.0]")
    
    # Step 6: Create color node
    print("\n[Step 6] Creating color node...")
    color_result = call_tool(
        "create_node",
        node_type="color",
        parent_path=geo_path,
        name="color1"
    )
    color_path = color_result["node_path"]
    print(f"✓ Created: {color_path}")
    
    # Step 7: Set color parameters (red)
    print("\n[Step 7] Setting color to red [1.0, 0.0, 0.0]...")
    call_tool(
        "set_parameter",
        node_path=color_path,
        param_name="color",
        value=[1.0, 0.0, 0.0]  # RGB red
    )
    print(f"✓ Set color: [1.0, 0.0, 0.0]")
    
    # Step 8: Create OUT null node
    print("\n[Step 8] Creating OUT null node...")
    out_result = call_tool(
        "create_node",
        node_type="null",
        parent_path=geo_path,
        name="OUT"
    )
    out_path = out_result["node_path"]
    print(f"✓ Created: {out_path}")
    
    # Step 9: Wire nodes together
    print("\n[Step 9] Wiring nodes together...")
    print("  Connecting sphere → xform...")
    call_tool(
        "connect_nodes",
        src_path=sphere_path,
        dst_path=xform_path,
        dst_input_index=0
    )
    print("  ✓ sphere → xform")
    
    print("  Connecting xform → color...")
    call_tool(
        "connect_nodes",
        src_path=xform_path,
        dst_path=color_path,
        dst_input_index=0
    )
    print("  ✓ xform → color")
    
    print("  Connecting color → OUT...")
    call_tool(
        "connect_nodes",
        src_path=color_path,
        dst_path=out_path,
        dst_input_index=0
    )
    print("  ✓ color → OUT")
    
    # Step 10: Set display flag on OUT
    print("\n[Step 10] Setting display flag on OUT node...")
    call_tool(
        "set_node_flags",
        node_path=out_path,
        display=True,
        render=True
    )
    print(f"✓ Display and render flags set on {out_path}")
    
    # Step 11: Verify with get_geo_summary
    print("\n[Step 11] Verifying geometry with get_geo_summary...")
    geo_summary = call_tool(
        "get_geo_summary",
        node_path=out_path,
        max_sample_points=10,
        include_attributes=True,
        include_groups=True
    )
    
    print(f"\n{'='*70}")
    print("GEOMETRY SUMMARY")
    print(f"{'='*70}")
    print(f"Node: {geo_summary['node_path']}")
    print(f"Cook State: {geo_summary['cook_state']}")
    print(f"Point Count: {geo_summary['point_count']}")
    print(f"Primitive Count: {geo_summary['primitive_count']}")
    print(f"Vertex Count: {geo_summary['vertex_count']}")
    
    if geo_summary.get('bounding_box'):
        bbox = geo_summary['bounding_box']
        print(f"\nBounding Box:")
        print(f"  Min: {bbox['min']}")
        print(f"  Max: {bbox['max']}")
        print(f"  Size: {bbox['size']}")
        print(f"  Center: {bbox['center']}")
    
    if geo_summary.get('attributes'):
        attrs = geo_summary['attributes']
        print(f"\nAttributes:")
        print(f"  Point: {len(attrs['point'])} attributes")
        for attr in attrs['point'][:5]:  # Show first 5
            print(f"    - {attr['name']} ({attr['type']}, size={attr['size']})")
        print(f"  Primitive: {len(attrs['primitive'])} attributes")
        print(f"  Vertex: {len(attrs['vertex'])} attributes")
    
    if geo_summary.get('sample_points'):
        print(f"\nSample Points (first 3):")
        for i, pt in enumerate(geo_summary['sample_points'][:3]):
            print(f"  Point {pt['index']}: P={pt.get('P', 'N/A')}")
            if 'Cd' in pt:
                print(f"              Cd={pt['Cd']}")
    
    print(f"\n{'='*70}")
    print("✓ BUILD COMPLETE!")
    print(f"{'='*70}")
    print(f"\nCreated network: {geo_path}")
    print(f"  ├─ {sphere_path}")
    print(f"  ├─ {xform_path}")
    print(f"  ├─ {color_path}")
    print(f"  └─ {out_path} [DISPLAY]")
    print("\nAll nodes created, wired, and verified successfully!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
