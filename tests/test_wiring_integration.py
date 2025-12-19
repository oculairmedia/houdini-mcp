"""Integration tests for HDMCP-6 node wiring tools."""

import pytest
from tests.conftest import MockHouNode


class TestWiringIntegration:
    """Integration tests for node wiring operations (HDMCP-6)."""
    
    def test_insert_node_in_chain(self, mock_connection):
        """
        Test acceptance criteria: Insert mountain between grid→noise to create grid→mountain→noise.
        
        This demonstrates the primary use case for the wiring tools:
        1. Create initial network: grid → noise
        2. Insert a mountain node in the middle
        3. Reconnect: grid → mountain → noise
        """
        from houdini_mcp.tools import (
            create_node,
            connect_nodes,
            disconnect_node_input,
            set_node_flags,
            get_node_info
        )
        
        # Setup: Create geo container
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        # Step 1: Create initial network (grid → noise)
        grid = geo1.createNode("grid", "grid1")
        mock_connection.add_node(grid)
        
        noise = geo1.createNode("noise", "noise1")
        mock_connection.add_node(noise)
        
        # Connect grid → noise
        result = connect_nodes("/obj/geo1/grid1", "/obj/geo1/noise1", 0, 0, "localhost", 18811)
        assert result["status"] == "success"
        assert noise._inputs[0] == grid
        
        # Verify initial connection
        info = get_node_info("/obj/geo1/noise1", False, 50, True, "localhost", 18811)
        assert len(info["input_connections"]) == 1
        assert info["input_connections"][0]["source_node"] == "/obj/geo1/grid1"
        
        # Step 2: Create mountain node
        mountain = geo1.createNode("mountain", "mountain1")
        mock_connection.add_node(mountain)
        
        # Step 3: Insert mountain in the chain
        # First, disconnect noise's input
        result = disconnect_node_input("/obj/geo1/noise1", 0, "localhost", 18811)
        assert result["status"] == "success"
        assert result["was_connected"] is True
        assert noise._inputs[0] is None
        
        # Connect grid → mountain
        result = connect_nodes("/obj/geo1/grid1", "/obj/geo1/mountain1", 0, 0, "localhost", 18811)
        assert result["status"] == "success"
        assert mountain._inputs[0] == grid
        
        # Connect mountain → noise
        result = connect_nodes("/obj/geo1/mountain1", "/obj/geo1/noise1", 0, 0, "localhost", 18811)
        assert result["status"] == "success"
        assert noise._inputs[0] == mountain
        
        # Step 4: Set display flag on noise (final node)
        result = set_node_flags("/obj/geo1/noise1", display=True, render=True, bypass=None,
                               host="localhost", port=18811)
        assert result["status"] == "success"
        assert noise._display_flag is True
        assert noise._render_flag is True
        
        # Verify final network structure
        assert len(grid._inputs) == 0  # Grid has no inputs (source)
        assert mountain._inputs[0].path() == grid.path()  # Mountain gets grid
        assert noise._inputs[0].path() == mountain.path()  # Noise gets mountain
        
        # Verify outputs are connected properly
        assert len(mountain._outputs) > 0
        assert len(grid._outputs) > 0  # Grid should have mountain as output
    
    def test_incompatible_type_validation(self, mock_connection):
        """
        Test that incompatible types return validation error.
        
        Verifies that trying to connect SOP → DOP returns an error.
        """
        from houdini_mcp.tools import connect_nodes
        
        # Create SOP node (grid)
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        mock_connection.add_node(geo1)
        mock_connection.add_node(grid)
        
        # Create DOP node (dopnet)
        dopnet = MockHouNode(path="/obj/dopnet1", name="dopnet1", node_type="dopnet")
        mock_connection.add_node(dopnet)
        
        # Try to connect SOP → DOP (should fail)
        result = connect_nodes("/obj/geo1/grid1", "/obj/dopnet1", 0, 0, "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Incompatible node types" in result["message"]
        assert "Sop" in result["message"]
        assert "Dop" in result["message"]
    
    def test_auto_disconnect_on_connect(self, mock_connection):
        """
        Test that connecting automatically disconnects existing connection.
        
        Verifies that if an input is already connected, the new connection
        replaces it automatically.
        """
        from houdini_mcp.tools import connect_nodes, get_node_info
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        # Create nodes
        grid = geo1.createNode("grid", "grid1")
        sphere = geo1.createNode("sphere", "sphere1")
        noise = geo1.createNode("noise", "noise1")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(noise)
        
        # Connect grid → noise
        result = connect_nodes("/obj/geo1/grid1", "/obj/geo1/noise1", 0, 0, "localhost", 18811)
        assert result["status"] == "success"
        assert noise._inputs[0] == grid
        
        # Connect sphere → noise (should auto-disconnect grid)
        result = connect_nodes("/obj/geo1/sphere1", "/obj/geo1/noise1", 0, 0, "localhost", 18811)
        assert result["status"] == "success"
        assert noise._inputs[0] == sphere
        assert noise not in grid._outputs
        assert noise in sphere._outputs
        
        # Verify via get_node_info
        info = get_node_info("/obj/geo1/noise1", False, 50, True, "localhost", 18811)
        assert len(info["input_connections"]) == 1
        assert info["input_connections"][0]["source_node"] == "/obj/geo1/sphere1"
    
    def test_merge_node_workflow(self, mock_connection):
        """
        Test typical merge node workflow with multiple inputs and reordering.
        
        Demonstrates:
        1. Connecting multiple inputs to a merge
        2. Reordering inputs
        3. Setting flags
        """
        from houdini_mcp.tools import (
            connect_nodes,
            reorder_inputs,
            set_node_flags,
            get_node_info
        )
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        # Create source nodes
        grid = geo1.createNode("grid", "grid1")
        sphere = geo1.createNode("sphere", "sphere1")
        box = geo1.createNode("box", "box1")
        merge = geo1.createNode("merge", "merge1")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(box)
        mock_connection.add_node(merge)
        
        # Connect all to merge
        result1 = connect_nodes("/obj/geo1/grid1", "/obj/geo1/merge1", 0, 0, "localhost", 18811)
        result2 = connect_nodes("/obj/geo1/sphere1", "/obj/geo1/merge1", 1, 0, "localhost", 18811)
        result3 = connect_nodes("/obj/geo1/box1", "/obj/geo1/merge1", 2, 0, "localhost", 18811)
        
        assert result1["status"] == "success"
        assert result2["status"] == "success"
        assert result3["status"] == "success"
        
        # Verify connections
        info = get_node_info("/obj/geo1/merge1", False, 50, True, "localhost", 18811)
        assert len(info["input_connections"]) == 3
        
        sources = [conn["source_node"] for conn in info["input_connections"]]
        assert "/obj/geo1/grid1" in sources
        assert "/obj/geo1/sphere1" in sources
        assert "/obj/geo1/box1" in sources
        
        # Reorder: swap first two inputs [1, 0, 2]
        result = reorder_inputs("/obj/geo1/merge1", [1, 0, 2], "localhost", 18811)
        assert result["status"] == "success"
        assert result["reconnection_count"] == 3
        
        # Verify new order
        assert merge._inputs[0] == sphere
        assert merge._inputs[1] == grid
        assert merge._inputs[2] == box
        
        # Set flags on merge
        result = set_node_flags("/obj/geo1/merge1", display=True, render=True, bypass=False,
                               host="localhost", port=18811)
        assert result["status"] == "success"
        assert merge._display_flag is True
        assert merge._bypass is False
    
    def test_bypass_flag_workflow(self, mock_connection):
        """Test bypassing nodes in a chain."""
        from houdini_mcp.tools import connect_nodes, set_node_flags
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        # Create chain: grid → mountain → noise
        grid = geo1.createNode("grid", "grid1")
        mountain = geo1.createNode("mountain", "mountain1")
        noise = geo1.createNode("noise", "noise1")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(mountain)
        mock_connection.add_node(noise)
        
        # Connect chain
        connect_nodes("/obj/geo1/grid1", "/obj/geo1/mountain1", 0, 0, "localhost", 18811)
        connect_nodes("/obj/geo1/mountain1", "/obj/geo1/noise1", 0, 0, "localhost", 18811)
        
        # Bypass mountain node
        result = set_node_flags("/obj/geo1/mountain1", display=None, render=None, bypass=True,
                               host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["flags_set"]["bypass"] is True
        assert mountain._bypass is True
        
        # The connection still exists, but mountain is bypassed
        assert mountain._inputs[0] == grid
        assert noise._inputs[0] == mountain
    
    def test_edge_cases(self, mock_connection):
        """Test various edge cases discovered during implementation."""
        from houdini_mcp.tools import (
            connect_nodes,
            disconnect_node_input,
            reorder_inputs
        )
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        # Edge case 1: Disconnect already disconnected input
        noise = geo1.createNode("noise", "noise1")
        noise._inputs = [None]
        mock_connection.add_node(noise)
        
        result = disconnect_node_input("/obj/geo1/noise1", 0, "localhost", 18811)
        assert result["status"] == "success"
        assert result["was_connected"] is False
        
        # Edge case 2: Reorder with gaps (some None inputs)
        merge = geo1.createNode("merge", "merge1")
        grid = geo1.createNode("grid", "grid1")
        sphere = geo1.createNode("sphere", "sphere1")
        
        mock_connection.add_node(merge)
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        
        # Connect with gap: grid→0, None→1, sphere→2
        merge.setInput(0, grid)
        merge.setInput(2, sphere)
        
        # Reorder: [2, 1, 0]
        result = reorder_inputs("/obj/geo1/merge1", [2, 1, 0], "localhost", 18811)
        assert result["status"] == "success"
        assert merge._inputs[0] == sphere
        assert merge._inputs[1] is None
        assert merge._inputs[2] == grid
        
        # Edge case 3: Connect nodes of same category (SOP→SOP)
        box = geo1.createNode("box", "box1")
        transform = geo1.createNode("transform", "transform1")
        mock_connection.add_node(box)
        mock_connection.add_node(transform)
        
        result = connect_nodes("/obj/geo1/box1", "/obj/geo1/transform1", 0, 0, "localhost", 18811)
        assert result["status"] == "success"
