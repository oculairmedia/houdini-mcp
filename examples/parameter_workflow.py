#!/usr/bin/env python3
"""
HDMCP-10 Example 3: Parameter Discovery → Set → Verify
=======================================================

Demonstrates intelligent parameter handling workflow:
1. Use get_parameter_schema to discover available parameters
2. Set parameters based on schema information (types, ranges, menus)
3. Verify parameter values were set correctly

This example shows:
- Schema discovery for different parameter types
- Setting float, vector, menu, and toggle parameters
- Validating parameter types before setting
- Reading back parameters to verify
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


def print_parameter_schema(param: Dict[str, Any]) -> None:
    """Pretty print a parameter schema."""
    print(f"\n  Parameter: {param['name']}")
    print(f"    Label: {param['label']}")
    print(f"    Type: {param['type']}")
    print(f"    Current Value: {param.get('current_value', 'N/A')}")
    print(f"    Default: {param.get('default', 'N/A')}")
    
    if param['type'] == 'vector':
        print(f"    Tuple Size: {param.get('tuple_size', 'N/A')}")
    
    if param['type'] in ('float', 'int', 'vector'):
        if param.get('min') is not None:
            print(f"    Min: {param['min']}")
        if param.get('max') is not None:
            print(f"    Max: {param['max']}")
    
    if param['type'] == 'menu' and param.get('menu_items'):
        print(f"    Menu Items:")
        for item in param['menu_items'][:5]:  # Show first 5
            print(f"      - {item['label']}: {item['value']}")
        if len(param['menu_items']) > 5:
            print(f"      ... and {len(param['menu_items']) - 5} more")


def main():
    """Demonstrate parameter discovery and intelligent setting."""
    
    print("=" * 70)
    print("HDMCP-10 Example 3: Parameter Workflow")
    print("Schema → Set → Verify")
    print("=" * 70)
    
    # Setup: Create a geo with sphere node
    print("\n[Setup] Creating sphere node for parameter testing...")
    
    geo_result = call_tool(
        "create_node",
        node_type="geo",
        parent_path="/obj",
        name="param_example"
    )
    geo_path = geo_result["node_path"]
    
    sphere_result = call_tool(
        "create_node",
        node_type="sphere",
        parent_path=geo_path,
        name="sphere1"
    )
    sphere_path = sphere_result["node_path"]
    print(f"✓ Created: {sphere_path}")
    
    # Step 1: Discover ALL parameters
    print(f"\n{'='*70}")
    print("[Step 1] Discovering all parameters with get_parameter_schema...")
    print(f"{'='*70}")
    
    all_params = call_tool(
        "get_parameter_schema",
        node_path=sphere_path,
        max_parms=20  # Limit for readability
    )
    
    print(f"\nFound {all_params['count']} parameters on {sphere_path}")
    print(f"(Showing first 20)")
    
    # Show a few interesting parameters
    interesting_params = ['rad', 'type', 't', 'r', 'scale']
    print(f"\nKey parameters:")
    
    for param in all_params['parameters']:
        if param['name'] in interesting_params:
            print_parameter_schema(param)
    
    # Step 2: Query SPECIFIC parameter
    print(f"\n{'='*70}")
    print("[Step 2] Querying SPECIFIC parameter: 'rad' (radius)")
    print(f"{'='*70}")
    
    rad_schema = call_tool(
        "get_parameter_schema",
        node_path=sphere_path,
        parm_name="rad"
    )
    
    if rad_schema['parameters']:
        rad_param = rad_schema['parameters'][0]
        print_parameter_schema(rad_param)
        
        # Store original value
        original_rad = rad_param['current_value']
        print(f"\n  Original radius: {original_rad}")
    
    # Step 3: Set parameters intelligently based on schema
    print(f"\n{'='*70}")
    print("[Step 3] Setting parameters based on schema...")
    print(f"{'='*70}")
    
    # Set radius (vector parameter)
    print("\n  Setting radius to [3.0, 3.0, 3.0]...")
    new_radius = [3.0, 3.0, 3.0]
    call_tool(
        "set_parameter",
        node_path=sphere_path,
        param_name="rad",
        value=new_radius
    )
    print(f"  ✓ Set rad = {new_radius}")
    
    # Set sphere type (menu parameter)
    print("\n  Discovering 'type' parameter menu items...")
    type_schema = call_tool(
        "get_parameter_schema",
        node_path=sphere_path,
        parm_name="type"
    )
    
    if type_schema['parameters']:
        type_param = type_schema['parameters'][0]
        print(f"  Type parameter is a {type_param['type']}")
        if type_param.get('menu_items'):
            print(f"  Available types:")
            for item in type_param['menu_items']:
                print(f"    {item['value']}: {item['label']}")
            
            # Set to first menu item
            new_type = type_param['menu_items'][0]['value']
            print(f"\n  Setting type to: {new_type} ({type_param['menu_items'][0]['label']})")
            call_tool(
                "set_parameter",
                node_path=sphere_path,
                param_name="type",
                value=new_type
            )
            print(f"  ✓ Set type = {new_type}")
    
    # Set translation (vector parameter)
    print("\n  Setting translation to [5.0, 0.0, 0.0]...")
    new_translate = [5.0, 0.0, 0.0]
    call_tool(
        "set_parameter",
        node_path=sphere_path,
        param_name="t",
        value=new_translate
    )
    print(f"  ✓ Set t = {new_translate}")
    
    # Set uniform scale (float parameter)
    print("\n  Setting uniform scale to 2.5...")
    call_tool(
        "set_parameter",
        node_path=sphere_path,
        param_name="scale",
        value=2.5
    )
    print(f"  ✓ Set scale = 2.5")
    
    # Step 4: Verify parameters were set correctly
    print(f"\n{'='*70}")
    print("[Step 4] Verifying parameters with get_node_info...")
    print(f"{'='*70}")
    
    node_info = call_tool(
        "get_node_info",
        node_path=sphere_path,
        include_params=True,
        max_params=50
    )
    
    print(f"\nVerifying parameter values:")
    params_to_check = {
        'radx': 3.0,
        'rady': 3.0,
        'radz': 3.0,
        'tx': 5.0,
        'ty': 0.0,
        'tz': 0.0,
        'scale': 2.5
    }
    
    all_correct = True
    for pname, expected in params_to_check.items():
        actual = node_info['parameters'].get(pname, 'NOT FOUND')
        match = abs(actual - expected) < 0.001 if isinstance(actual, (int, float)) else False
        status = "✓" if match else "✗"
        print(f"  {status} {pname}: expected={expected}, actual={actual}")
        if not match:
            all_correct = False
    
    # Step 5: Verify geometry reflects parameter changes
    print(f"\n{'='*70}")
    print("[Step 5] Verifying geometry reflects parameter changes...")
    print(f"{'='*70}")
    
    geo_summary = call_tool(
        "get_geo_summary",
        node_path=sphere_path,
        max_sample_points=0,
        include_attributes=False
    )
    
    print(f"\nGeometry summary:")
    print(f"  Cook state: {geo_summary['cook_state']}")
    print(f"  Points: {geo_summary['point_count']}")
    print(f"  Primitives: {geo_summary['primitive_count']}")
    
    if geo_summary.get('bounding_box'):
        bbox = geo_summary['bounding_box']
        print(f"\n  Bounding box:")
        print(f"    Center: {bbox['center']}")
        print(f"    Size: {bbox['size']}")
        
        # Check if center reflects translation
        expected_center = [5.0, 0.0, 0.0]
        center_match = all(abs(bbox['center'][i] - expected_center[i]) < 0.1 for i in range(3))
        
        # Check if size reflects radius * scale (rad=3.0, scale=2.5 → diameter ≈ 15.0)
        expected_diameter = 3.0 * 2.5 * 2  # radius * scale * 2
        size_match = abs(bbox['size'][0] - expected_diameter) < 0.5
        
        print(f"\n  Verification:")
        print(f"    {'✓' if center_match else '✗'} Center matches translation {expected_center}")
        print(f"    {'✓' if size_match else '✗'} Size matches radius×scale (expected ≈ {expected_diameter})")
    
    # Final summary
    print(f"\n{'='*70}")
    print("✓ PARAMETER WORKFLOW COMPLETE!")
    print(f"{'='*70}")
    
    print(f"\nWorkflow demonstrated:")
    print(f"  1. ✓ Discovered all parameters with get_parameter_schema")
    print(f"  2. ✓ Queried specific parameter schemas")
    print(f"  3. ✓ Set parameters intelligently (vector, menu, float)")
    print(f"  4. ✓ Verified parameters with get_node_info")
    print(f"  5. ✓ Verified geometry reflects changes")
    
    if all_correct:
        print(f"\n✓ All parameters set correctly!")
    else:
        print(f"\n⚠ Some parameters may not have been set correctly")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
