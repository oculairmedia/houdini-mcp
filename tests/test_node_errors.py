"""Tests for node error/warning introspection (HDMCP-8)."""

import pytest
from unittest.mock import MagicMock, patch
import time

from tests.conftest import MockHouNode, MockHouModule


class TestGetNodeInfoWithErrors:
    """Tests for get_node_info with include_errors parameter."""
    
    def test_get_node_info_with_errors_cooked(self, mock_connection):
        """Test getting node info with errors for a successfully cooked node."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        # Node is cooked by default with no errors
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        assert result["cook_info"]["cook_state"] == "cooked"
        assert result["cook_info"]["errors"] == []
        assert result["cook_info"]["warnings"] == []
    
    def test_get_node_info_with_errors_failed(self, mock_connection):
        """Test getting node info for a node with cook errors."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node with errors
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._cook_state = "CookFailed"
        geo1._errors = ["Invalid parameter value", "Missing input connection"]
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        assert result["cook_info"]["cook_state"] == "error"
        assert len(result["cook_info"]["errors"]) == 2
        assert result["cook_info"]["errors"][0]["severity"] == "error"
        assert result["cook_info"]["errors"][0]["message"] == "Invalid parameter value"
        assert result["cook_info"]["errors"][0]["node_path"] == "/obj/geo1"
        assert result["cook_info"]["errors"][1]["message"] == "Missing input connection"
    
    def test_get_node_info_with_warnings(self, mock_connection):
        """Test getting node info for a node with warnings."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node with warnings
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._warnings = ["Deprecated parameter used", "Performance warning: large dataset"]
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        assert result["cook_info"]["cook_state"] == "cooked"
        assert len(result["cook_info"]["warnings"]) == 2
        assert result["cook_info"]["warnings"][0]["severity"] == "warning"
        assert result["cook_info"]["warnings"][0]["message"] == "Deprecated parameter used"
        assert result["cook_info"]["warnings"][1]["message"] == "Performance warning: large dataset"
    
    def test_get_node_info_with_errors_and_warnings(self, mock_connection):
        """Test getting node info for a node with both errors and warnings."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node with both errors and warnings
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._cook_state = "CookFailed"
        geo1._errors = ["Critical error"]
        geo1._warnings = ["Minor warning"]
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        assert result["cook_info"]["cook_state"] == "error"
        assert len(result["cook_info"]["errors"]) == 1
        assert len(result["cook_info"]["warnings"]) == 1
    
    def test_get_node_info_dirty_state(self, mock_connection):
        """Test getting node info for a dirty (needs recook) node."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node in dirty state
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._cook_state = "Dirty"
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        assert result["cook_info"]["cook_state"] == "dirty"
    
    def test_get_node_info_uncooked_state(self, mock_connection):
        """Test getting node info for an uncooked node."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node in uncooked state
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._cook_state = "Uncooked"
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        assert result["cook_info"]["cook_state"] == "uncooked"
    
    def test_get_node_info_force_cook(self, mock_connection):
        """Test forcing a cook before getting errors."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node with errors
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._cook_state = "Dirty"
        geo1._errors = ["Old error"]
        mock_connection.add_node(geo1)
        
        # Force cook should update cook state and clear errors (in mock)
        result = get_node_info("/obj/geo1", include_errors=True, force_cook=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        # After cook, errors should still be there (mock keeps them)
        assert "last_cook_time" in result["cook_info"]
    
    def test_get_node_info_backward_compatible(self, mock_connection):
        """Test that include_errors=False (default) doesn't include cook_info."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._errors = ["Some error"]
        mock_connection.add_node(geo1)
        
        # Default behavior - no cook_info
        result = get_node_info("/obj/geo1", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" not in result
        
        # Explicitly False
        result = get_node_info("/obj/geo1", include_errors=False, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" not in result
    
    def test_get_node_info_with_errors_node_not_found(self, mock_connection):
        """Test error handling when node doesn't exist."""
        from houdini_mcp.tools import get_node_info
        
        result = get_node_info("/obj/nonexistent", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
    
    def test_get_node_info_multiple_errors(self, mock_connection):
        """Test node with multiple errors."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node with multiple errors
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._cook_state = "CookFailed"
        geo1._errors = [
            "Error 1: Invalid geometry",
            "Error 2: Missing attribute",
            "Error 3: Division by zero",
            "Error 4: Out of memory"
        ]
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert len(result["cook_info"]["errors"]) == 4
        assert all(e["severity"] == "error" for e in result["cook_info"]["errors"])
        assert all(e["node_path"] == "/obj/geo1" for e in result["cook_info"]["errors"])
    
    def test_get_node_info_combined_with_params(self, mock_connection):
        """Test that include_errors works together with include_params."""
        from houdini_mcp.tools import get_node_info
        
        # Create a test node with params and errors
        geo1 = MockHouNode(
            path="/obj/geo1", 
            name="geo1", 
            node_type="geo",
            params={"tx": 1.0, "ty": 2.0, "tz": 3.0}
        )
        geo1._warnings = ["Test warning"]
        mock_connection.add_node(geo1)
        
        result = get_node_info(
            "/obj/geo1", 
            include_params=True, 
            include_errors=True,
            host="localhost", 
            port=18811
        )
        
        assert result["status"] == "success"
        assert "parameters" in result
        assert result["parameters"]["tx"] == 1.0
        assert "cook_info" in result
        assert len(result["cook_info"]["warnings"]) == 1
    
    def test_get_node_info_empty_errors_and_warnings(self, mock_connection):
        """Test node with no errors or warnings returns empty arrays."""
        from houdini_mcp.tools import get_node_info
        
        # Create a clean node
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["cook_info"]["errors"] == []
        assert result["cook_info"]["warnings"] == []
        assert isinstance(result["cook_info"]["errors"], list)
        assert isinstance(result["cook_info"]["warnings"], list)


class TestEdgeCases:
    """Test edge cases for error introspection."""
    
    def test_force_cook_without_include_errors(self, mock_connection):
        """Test that force_cook without include_errors doesn't crash."""
        from houdini_mcp.tools import get_node_info
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        # force_cook without include_errors should just be ignored
        result = get_node_info("/obj/geo1", force_cook=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" not in result
    
    def test_cook_state_enum_edge_cases(self, mock_connection):
        """Test handling of unusual cook state values."""
        from houdini_mcp.tools import get_node_info
        
        # Create node with unknown cook state
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._cook_state = "UnknownState"
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "cook_info" in result
        # Should fallback to lowercase of unknown state
        assert result["cook_info"]["cook_state"] == "unknownstate"
    
    def test_special_characters_in_error_messages(self, mock_connection):
        """Test error messages with special characters."""
        from houdini_mcp.tools import get_node_info
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        geo1._errors = [
            "Error with 'quotes'",
            'Error with "double quotes"',
            "Error with\nnewline",
            "Error with\ttab"
        ]
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", include_errors=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert len(result["cook_info"]["errors"]) == 4
        # Messages should be preserved as-is
        assert "quotes" in result["cook_info"]["errors"][0]["message"]
