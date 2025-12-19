#!/usr/bin/env python3
"""
HDMCP-10 Example 4: Error Detection → Fix → Verify
===================================================

Demonstrates robust error handling workflow:
1. Detect errors using get_node_info with include_errors=True
2. Analyze error messages to understand the problem
3. Fix the error programmatically
4. Verify the fix with cook state checking

This example shows:
- Checking cook state before reading geometry
- Validating parameter types before setting
- Handling connection errors
- Using error introspection to guide fixes
"""

import requests
import json
from typing import Dict, Any, List, Optional

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
    
    # Note: We DON'T raise on error status here - we want to handle errors
    return result


def check_for_errors(node_path: str) -> Optional[Dict[str, Any]]:
    """Check if a node has cook errors. Returns cook_info or None."""
    result = call_tool(
        "get_node_info",
        node_path=node_path,
        include_params=False,
        include_errors=True,
        force_cook=True
    )
    
    if result.get("status") == "error":
        print(f"  ⚠ Could not get node info: {result.get('message')}")
        return None
    
    cook_info = result.get('cook_info')
    if not cook_info:
        return None
    
    return cook_info


def print_cook_info(cook_info: Dict[str, Any]) -> None:
    """Pretty print cook information."""
    state = cook_info['cook_state']
    errors = cook_info.get('errors', [])
    warnings = cook_info.get('warnings', [])
    
    # Color code cook state
    state_symbol = {
        'cooked': '✓',
        'error': '✗',
        'dirty': '⚠',
        'uncooked': '○'
    }.get(state, '?')
    
    print(f"  {state_symbol} Cook State: {state}")
    
    if errors:
        print(f"  Errors ({len(errors)}):")
        for err in errors:
            print(f"    ✗ {err.get('message', 'Unknown error')}")
    
    if warnings:
        print(f"  Warnings ({len(warnings)}):")
        for warn in warnings:
            print(f"    ⚠ {warn.get('message', 'Unknown warning')}")


def main():
    """Demonstrate error detection, diagnosis, and fixing."""
    
    print("=" * 70)
    print("HDMCP-10 Example 4: Error Handling Workflow")
    print("Detect → Fix → Verify")
    print("=" * 70)
    
    # Setup: Create geo container
    print("\n[Setup] Creating test network...")
    
    geo_result = call_tool(
        "create_node",
        node_type="geo",
        parent_path="/obj",
        name="error_example"
    )
    geo_path = geo_result["node_path"]
    print(f"✓ Created: {geo_path}")
    
    # Scenario 1: Missing input connection error
    print(f"\n{'='*70}")
    print("SCENARIO 1: Missing Input Connection")
    print(f"{'='*70}")
    
    print("\n[Step 1] Creating noise node WITHOUT input...")
    noise_result = call_tool(
        "create_node",
        node_type="noise",
        parent_path=geo_path,
        name="noise1"
    )
    noise_path = noise_result["node_path"]
    print(f"✓ Created: {noise_path}")
    
    print("\n[Step 2] Checking for errors...")
    cook_info = check_for_errors(noise_path)
    if cook_info:
        print_cook_info(cook_info)
        
        # Note: Noise without input might not error, it just has no geometry
        # Let's check geometry
        geo_result = call_tool(
            "get_geo_summary",
            node_path=noise_path,
            max_sample_points=0
        )
        
        if geo_result.get('status') == 'success':
            if geo_result['point_count'] == 0:
                print(f"\n  ⚠ Warning: Noise has no geometry (0 points)")
                print(f"     This is expected - noise needs input geometry!")
    
    print("\n[Step 3] Fixing: Adding grid input...")
    grid_result = call_tool(
        "create_node",
        node_type="grid",
        parent_path=geo_path,
        name="grid1"
    )
    grid_path = grid_result["node_path"]
    
    call_tool(
        "connect_nodes",
        src_path=grid_path,
        dst_path=noise_path,
        dst_input_index=0
    )
    print(f"✓ Connected: grid → noise")
    
    print("\n[Step 4] Verifying fix...")
    cook_info = check_for_errors(noise_path)
    if cook_info:
        print_cook_info(cook_info)
    
    geo_result = call_tool(
        "get_geo_summary",
        node_path=noise_path,
        max_sample_points=0
    )
    
    if geo_result.get('status') == 'success' and geo_result['point_count'] > 0:
        print(f"\n  ✓ Fix successful! Noise now has {geo_result['point_count']} points")
    
    # Scenario 2: Invalid parameter value
    print(f"\n{'='*70}")
    print("SCENARIO 2: Invalid Parameter Type")
    print(f"{'='*70}")
    
    print("\n[Step 1] Creating sphere node...")
    sphere_result = call_tool(
        "create_node",
        node_type="sphere",
        parent_path=geo_path,
        name="sphere1"
    )
    sphere_path = sphere_result["node_path"]
    print(f"✓ Created: {sphere_path}")
    
    print("\n[Step 2] Attempting to set vector parameter with scalar...")
    # This should fail - 'rad' expects a vector
    bad_result = call_tool(
        "set_parameter",
        node_path=sphere_path,
        param_name="rad",
        value=5.0  # Wrong! Should be [5.0, 5.0, 5.0]
    )
    
    if bad_result.get('status') == 'error':
        print(f"  ✗ Error (expected): {bad_result.get('message')}")
        print(f"     This error helps us understand the correct parameter format!")
    
    print("\n[Step 3] Checking parameter schema to find correct type...")
    schema = call_tool(
        "get_parameter_schema",
        node_path=sphere_path,
        parm_name="rad"
    )
    
    if schema.get('status') == 'success' and schema['parameters']:
        param = schema['parameters'][0]
        print(f"  ℹ Parameter 'rad' schema:")
        print(f"    Type: {param['type']}")
        print(f"    Tuple Size: {param.get('tuple_size', 'N/A')}")
        print(f"    Default: {param.get('default', 'N/A')}")
        
        if param['type'] == 'vector':
            print(f"\n  → Insight: 'rad' is a vector, requires list/tuple of {param.get('tuple_size', 3)} values")
    
    print("\n[Step 4] Fixing: Setting parameter with correct type...")
    good_result = call_tool(
        "set_parameter",
        node_path=sphere_path,
        param_name="rad",
        value=[5.0, 5.0, 5.0]  # Correct!
    )
    
    if good_result.get('status') == 'success':
        print(f"  ✓ Parameter set successfully!")
        print(f"     Value: {good_result['value']}")
    
    # Scenario 3: Incompatible node connection
    print(f"\n{'='*70}")
    print("SCENARIO 3: Incompatible Node Types")
    print(f"{'='*70}")
    
    print("\n[Step 1] Creating camera node at /obj level...")
    cam_result = call_tool(
        "create_node",
        node_type="cam",
        parent_path="/obj",
        name="cam1"
    )
    cam_path = cam_result["node_path"]
    print(f"✓ Created: {cam_path}")
    
    print("\n[Step 2] Attempting to connect SOP to OBJ (invalid)...")
    # This should fail - can't connect different node categories
    bad_connection = call_tool(
        "connect_nodes",
        src_path=grid_path,  # SOP node
        dst_path=cam_path,   # OBJ node
        dst_input_index=0
    )
    
    if bad_connection.get('status') == 'error':
        print(f"  ✗ Error (expected): {bad_connection.get('message')}")
        print(f"     The error message tells us we can't mix SOP and Object nodes!")
    
    print("\n[Step 3] Fix: Only connect nodes of the same category")
    print(f"     → SOP nodes can only connect to other SOP nodes")
    print(f"     → OBJ nodes can only connect to other OBJ nodes")
    print(f"     This validation prevents invalid network structures!")
    
    # Scenario 4: Cook state validation before geometry access
    print(f"\n{'='*70}")
    print("SCENARIO 4: Safe Geometry Access Pattern")
    print(f"{'='*70}")
    
    print("\n[Best Practice] Always check cook state before accessing geometry:")
    print("""
    1. Call get_node_info with include_errors=True
    2. Check cook_info['cook_state'] == 'cooked'
    3. If 'error', examine cook_info['errors'] for diagnostics
    4. If 'dirty' or 'uncooked', may need to force cook
    5. Only access geometry if cook_state is 'cooked'
    """)
    
    print("\nDemonstrating safe geometry access...")
    
    # Create a node that might have geometry
    test_result = call_tool(
        "create_node",
        node_type="box",
        parent_path=geo_path,
        name="box1"
    )
    test_path = test_result["node_path"]
    
    # Step 1: Check cook state
    print(f"\n  Step 1: Checking cook state of {test_path}...")
    cook_info = check_for_errors(test_path)
    
    if cook_info:
        print_cook_info(cook_info)
        
        # Step 2: Decide whether to access geometry
        if cook_info['cook_state'] == 'cooked':
            print(f"\n  Step 2: Cook state is 'cooked' - safe to access geometry")
            
            geo = call_tool(
                "get_geo_summary",
                node_path=test_path,
                max_sample_points=3
            )
            
            if geo.get('status') == 'success':
                print(f"  ✓ Successfully read geometry:")
                print(f"     Points: {geo['point_count']}")
                print(f"     Primitives: {geo['primitive_count']}")
        else:
            print(f"\n  Step 2: Cook state is '{cook_info['cook_state']}' - NOT safe!")
            print(f"     Would need to handle errors before accessing geometry")
    
    # Final summary
    print(f"\n{'='*70}")
    print("✓ ERROR HANDLING WORKFLOW COMPLETE!")
    print(f"{'='*70}")
    
    print(f"\nKey error handling patterns demonstrated:")
    print(f"  1. ✓ Use get_node_info(include_errors=True) to detect issues")
    print(f"  2. ✓ Examine cook_info to understand error type")
    print(f"  3. ✓ Use get_parameter_schema to validate parameter types")
    print(f"  4. ✓ Check cook_state before accessing geometry")
    print(f"  5. ✓ Handle connection validation errors gracefully")
    
    print(f"\nBest practices:")
    print(f"  • Always check return status from MCP tools")
    print(f"  • Use include_errors=True when debugging")
    print(f"  • Validate parameter types with schema before setting")
    print(f"  • Test node connections for category compatibility")
    print(f"  • Check cook state before reading geometry")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
