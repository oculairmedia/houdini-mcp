"""Tests for the Houdini MCP tools."""

import pytest
from unittest.mock import MagicMock, patch

from tests.conftest import MockHouNode, MockHouModule


class TestGetSceneInfo:
    """Tests for the get_scene_info function."""
    
    def test_get_scene_info_success(self, mock_connection):
        """Test getting scene info successfully."""
        from houdini_mcp.tools import get_scene_info
        
        result = get_scene_info("localhost", 18811)
        
        assert result["status"] == "success"
        assert result["hip_file"] == "/path/to/test.hip"
        assert result["houdini_version"] == "20.5.123"
    
    def test_get_scene_info_with_nodes(self, mock_connection):
        """Test getting scene info with nodes in /obj."""
        from houdini_mcp.tools import get_scene_info
        
        # Add some child nodes to /obj
        obj_node = mock_connection.node("/obj")
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        cam1 = MockHouNode(path="/obj/cam1", name="cam1", node_type="cam")
        obj_node._children = [geo1, cam1]
        
        result = get_scene_info("localhost", 18811)
        
        assert result["status"] == "success"
        assert result["node_count"] == 2
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["name"] == "geo1"
        assert result["nodes"][1]["name"] == "cam1"
    
    def test_get_scene_info_empty_scene(self, mock_connection):
        """Test getting scene info with empty scene."""
        from houdini_mcp.tools import get_scene_info
        
        result = get_scene_info("localhost", 18811)
        
        assert result["status"] == "success"
        assert result["node_count"] == 0
        assert result["nodes"] == []
    
    def test_get_scene_info_connection_error(self, reset_connection_state):
        """Test get_scene_info handles connection errors."""
        from houdini_mcp.tools import get_scene_info
        
        with patch('houdini_mcp.connection.rpyc') as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = get_scene_info("localhost", 18811)
        
        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]


class TestCreateNode:
    """Tests for the create_node function."""
    
    def test_create_node_success(self, mock_connection):
        """Test creating a node successfully."""
        from houdini_mcp.tools import create_node
        
        result = create_node("geo", "/obj", "my_geo", "localhost", 18811)
        
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/my_geo"
        assert result["node_type"] == "geo"
        assert result["node_name"] == "my_geo"
    
    def test_create_node_auto_name(self, mock_connection):
        """Test creating a node with auto-generated name."""
        from houdini_mcp.tools import create_node
        
        result = create_node("sphere", "/obj", None, "localhost", 18811)
        
        assert result["status"] == "success"
        assert "sphere" in result["node_path"]
    
    def test_create_node_parent_not_found(self, mock_connection):
        """Test creating a node with non-existent parent."""
        from houdini_mcp.tools import create_node
        
        result = create_node("geo", "/obj/nonexistent", None, "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Parent node not found" in result["message"]
    
    def test_create_node_different_types(self, mock_connection):
        """Test creating different node types."""
        from houdini_mcp.tools import create_node
        
        for node_type in ["geo", "cam", "null", "light"]:
            result = create_node(node_type, "/obj", f"test_{node_type}", "localhost", 18811)
            assert result["status"] == "success"
            assert result["node_type"] == node_type


class TestExecuteCode:
    """Tests for the execute_code function."""
    
    def test_execute_code_success(self, mock_connection):
        """Test executing code successfully."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("x = 1 + 1", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
        assert "stdout" in result
        assert "stderr" in result
    
    def test_execute_code_with_print(self, mock_connection):
        """Test executing code that prints output."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("print('hello world')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
        assert "hello world" in result["stdout"]
    
    def test_execute_code_with_error(self, mock_connection):
        """Test executing code that raises an error."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("raise ValueError('test error')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert "test error" in result["message"]
        assert "traceback" in result
    
    def test_execute_code_with_diff(self, mock_connection):
        """Test executing code with scene diff capture."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("x = 1", "localhost", 18811, capture_diff=True)
        
        assert result["status"] == "success"
        assert "scene_changes" in result
    
    def test_execute_code_syntax_error(self, mock_connection):
        """Test executing code with syntax error."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("def broken(", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert "traceback" in result
    
    def test_execute_code_has_hou_available(self, mock_connection):
        """Test that hou module is available in executed code."""
        from houdini_mcp.tools import execute_code
        
        # This should not raise - hou should be available
        result = execute_code("version = hou.applicationVersionString()", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
    
    def test_execute_code_captures_stderr(self, mock_connection):
        """Test that stderr is captured."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("import sys; sys.stderr.write('error output')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
        assert "error output" in result["stderr"]


class TestSetParameter:
    """Tests for the set_parameter function."""
    
    def test_set_parameter_success(self, mock_connection):
        """Test setting a parameter successfully."""
        from houdini_mcp.tools import set_parameter
        
        # Add a node with params
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            params={"tx": 0.0, "ty": 0.0, "tz": 0.0}
        )
        mock_connection.add_node(geo1)
        
        result = set_parameter("/obj/geo1", "tx", 5.0, "localhost", 18811)
        
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/geo1"
        assert result["param_name"] == "tx"
        assert result["value"] == 5.0
    
    def test_set_parameter_node_not_found(self, mock_connection):
        """Test setting parameter on non-existent node."""
        from houdini_mcp.tools import set_parameter
        
        result = set_parameter("/obj/nonexistent", "tx", 5.0, "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_set_parameter_param_not_found(self, mock_connection):
        """Test setting non-existent parameter."""
        from houdini_mcp.tools import set_parameter
        
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            params={"tx": 0.0}
        )
        mock_connection.add_node(geo1)
        
        result = set_parameter("/obj/geo1", "nonexistent", 5.0, "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Parameter not found" in result["message"]
    
    def test_set_parameter_vector_param(self, mock_connection):
        """Test setting a vector parameter."""
        from houdini_mcp.tools import set_parameter
        
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            params={"t": [0.0, 0.0, 0.0]}  # Vector param
        )
        mock_connection.add_node(geo1)
        
        result = set_parameter("/obj/geo1", "t", [1.0, 2.0, 3.0], "localhost", 18811)
        
        assert result["status"] == "success"


class TestGetNodeInfo:
    """Tests for the get_node_info function."""
    
    def test_get_node_info_success(self, mock_connection):
        """Test getting node info successfully."""
        from houdini_mcp.tools import get_node_info
        
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            type_description="Geometry Container",
            params={"tx": 1.0, "ty": 2.0, "tz": 3.0}
        )
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", True, 50, "localhost", 18811)
        
        assert result["status"] == "success"
        assert result["path"] == "/obj/geo1"
        assert result["name"] == "geo1"
        assert result["type"] == "geo"
        assert "parameters" in result
    
    def test_get_node_info_no_params(self, mock_connection):
        """Test getting node info without parameters."""
        from houdini_mcp.tools import get_node_info
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", False, 50, "localhost", 18811)
        
        assert result["status"] == "success"
        assert "parameters" not in result
    
    def test_get_node_info_not_found(self, mock_connection):
        """Test getting info for non-existent node."""
        from houdini_mcp.tools import get_node_info
        
        result = get_node_info("/obj/nonexistent", True, 50, "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_get_node_info_with_children(self, mock_connection):
        """Test getting node info includes children."""
        from houdini_mcp.tools import get_node_info
        
        child1 = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            children=[child1]
        )
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", False, 50, "localhost", 18811)
        
        assert result["status"] == "success"
        assert "sphere1" in result["children"]
    
    def test_get_node_info_max_params(self, mock_connection):
        """Test max_params truncation."""
        from houdini_mcp.tools import get_node_info
        
        many_params = {f"param{i}": i for i in range(100)}
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            params=many_params
        )
        mock_connection.add_node(geo1)
        
        result = get_node_info("/obj/geo1", True, 10, "localhost", 18811)
        
        assert result["status"] == "success"
        # Should have truncation indicator
        assert result["parameters"].get("_truncated") is True


class TestDeleteNode:
    """Tests for the delete_node function."""
    
    def test_delete_node_success(self, mock_connection):
        """Test deleting a node successfully."""
        from houdini_mcp.tools import delete_node
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        mock_connection.add_node(geo1)
        
        result = delete_node("/obj/geo1", "localhost", 18811)
        
        assert result["status"] == "success"
        assert result["deleted_path"] == "/obj/geo1"
    
    def test_delete_node_not_found(self, mock_connection):
        """Test deleting non-existent node."""
        from houdini_mcp.tools import delete_node
        
        result = delete_node("/obj/nonexistent", "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_delete_node_returns_name(self, mock_connection):
        """Test delete returns node name in message."""
        from houdini_mcp.tools import delete_node
        
        geo1 = MockHouNode(path="/obj/my_special_geo", name="my_special_geo", node_type="geo")
        mock_connection.add_node(geo1)
        
        result = delete_node("/obj/my_special_geo", "localhost", 18811)
        
        assert "my_special_geo" in result["message"]


class TestSceneOperations:
    """Tests for scene file operations."""
    
    def test_save_scene_success(self, mock_connection):
        """Test saving scene successfully."""
        from houdini_mcp.tools import save_scene
        
        result = save_scene(None, "localhost", 18811)
        
        assert result["status"] == "success"
        assert "Scene saved" in result["message"]
        mock_connection.hipFile.save.assert_called_once()
    
    def test_save_scene_with_path(self, mock_connection):
        """Test saving scene to specific path."""
        from houdini_mcp.tools import save_scene
        
        result = save_scene("/path/to/new.hip", "localhost", 18811)
        
        assert result["status"] == "success"
        assert result["file_path"] == "/path/to/new.hip"
    
    def test_load_scene_success(self, mock_connection):
        """Test loading scene successfully."""
        from houdini_mcp.tools import load_scene
        
        result = load_scene("/path/to/scene.hip", "localhost", 18811)
        
        assert result["status"] == "success"
        mock_connection.hipFile.load.assert_called_once_with("/path/to/scene.hip")
    
    def test_new_scene_success(self, mock_connection):
        """Test creating new scene successfully."""
        from houdini_mcp.tools import new_scene
        
        result = new_scene("localhost", 18811)
        
        assert result["status"] == "success"
        mock_connection.hipFile.clear.assert_called_once()
    
    def test_save_scene_error_handling(self, mock_connection):
        """Test save_scene handles errors."""
        from houdini_mcp.tools import save_scene
        
        mock_connection.hipFile.save.side_effect = Exception("Disk full")
        
        result = save_scene(None, "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Disk full" in result["message"]
    
    def test_load_scene_error_handling(self, mock_connection):
        """Test load_scene handles errors."""
        from houdini_mcp.tools import load_scene
        
        mock_connection.hipFile.load.side_effect = Exception("File not found")
        
        result = load_scene("/nonexistent.hip", "localhost", 18811)
        
        assert result["status"] == "error"
        assert "File not found" in result["message"]


class TestSerializeScene:
    """Tests for scene serialization."""
    
    def test_serialize_scene_success(self, mock_connection):
        """Test serializing scene successfully."""
        from houdini_mcp.tools import serialize_scene
        
        result = serialize_scene("/obj", False, 10, "localhost", 18811)
        
        assert result["status"] == "success"
        assert result["root"] == "/obj"
        assert "structure" in result
    
    def test_serialize_scene_with_children(self, mock_connection):
        """Test serializing scene with child nodes."""
        from houdini_mcp.tools import serialize_scene
        
        # Add child nodes
        obj_node = mock_connection.node("/obj")
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        obj_node._children = [geo1]
        
        result = serialize_scene("/obj", False, 10, "localhost", 18811)
        
        assert result["status"] == "success"
        assert len(result["structure"]["children"]) == 1
    
    def test_serialize_scene_not_found(self, mock_connection):
        """Test serializing from non-existent root."""
        from houdini_mcp.tools import serialize_scene
        
        result = serialize_scene("/nonexistent", False, 10, "localhost", 18811)
        
        assert result["status"] == "error"
        assert "Root node not found" in result["message"]
    
    def test_serialize_scene_with_params(self, mock_connection):
        """Test serializing scene includes params when requested."""
        from houdini_mcp.tools import serialize_scene
        
        obj_node = mock_connection.node("/obj")
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            params={"tx": 1.0}
        )
        obj_node._children = [geo1]
        mock_connection.add_node(geo1)
        
        result = serialize_scene("/obj", True, 10, "localhost", 18811)
        
        assert result["status"] == "success"
    
    def test_serialize_scene_respects_max_depth(self, mock_connection):
        """Test serialization respects max depth."""
        from houdini_mcp.tools import serialize_scene
        
        # Create deep hierarchy
        obj_node = mock_connection.node("/obj")
        level1 = MockHouNode(path="/obj/level1", name="level1", node_type="geo")
        level2 = MockHouNode(path="/obj/level1/level2", name="level2", node_type="null")
        level3 = MockHouNode(path="/obj/level1/level2/level3", name="level3", node_type="null")
        level1._children = [level2]
        level2._children = [level3]
        obj_node._children = [level1]
        
        result = serialize_scene("/obj", False, 1, "localhost", 18811)
        
        assert result["status"] == "success"


class TestSceneDiff:
    """Tests for scene diff functionality."""
    
    def test_get_last_scene_diff_no_diff(self):
        """Test getting scene diff when none available."""
        from houdini_mcp.tools import get_last_scene_diff
        import houdini_mcp.tools as tools_module
        
        # Reset scene state
        tools_module._before_scene = []
        tools_module._after_scene = []
        
        result = get_last_scene_diff()
        
        assert result["status"] == "warning"
        assert "No scene diff available" in result["message"]
    
    def test_get_last_scene_diff_with_changes(self):
        """Test getting scene diff with actual changes."""
        from houdini_mcp.tools import get_last_scene_diff
        import houdini_mcp.tools as tools_module
        
        # Simulate before/after state
        tools_module._before_scene = []
        tools_module._after_scene = [
            {"path": "/obj/new_node", "type": "geo", "name": "new_node", "children": []}
        ]
        
        result = get_last_scene_diff()
        
        assert result["status"] == "success"
        assert result["diff"]["has_changes"] is True
        assert "/obj/new_node" in result["diff"]["added"]


class TestListNodeTypes:
    """Tests for list_node_types function."""
    
    def test_list_node_types_success(self, mock_connection):
        """Test listing node types successfully."""
        from houdini_mcp.tools import list_node_types
        
        result = list_node_types(None, "localhost", 18811)
        
        assert result["status"] == "success"
        assert "node_types" in result
        assert result["count"] > 0
    
    def test_list_node_types_with_category(self, mock_connection):
        """Test listing node types with category filter."""
        from houdini_mcp.tools import list_node_types
        
        result = list_node_types("Object", "localhost", 18811)
        
        assert result["status"] == "success"
        # All returned types should be from Object category
        for node_type in result["node_types"]:
            assert node_type["category"] == "Object"
    
    def test_list_node_types_nonexistent_category(self, mock_connection):
        """Test listing with non-existent category returns empty."""
        from houdini_mcp.tools import list_node_types
        
        result = list_node_types("NonExistentCategory", "localhost", 18811)
        
        assert result["status"] == "success"
        assert result["count"] == 0


class TestInternalHelpers:
    """Tests for internal helper functions."""
    
    def test_node_to_dict(self, mock_connection):
        """Test _node_to_dict helper."""
        from houdini_mcp.tools import _node_to_dict
        
        node = MockHouNode(
            path="/obj/test",
            name="test",
            node_type="geo",
            params={"tx": 1.0}
        )
        
        result = _node_to_dict(node, include_params=True)
        
        assert result["path"] == "/obj/test"
        assert result["name"] == "test"
        assert result["type"] == "geo"
        assert "parameters" in result
    
    def test_get_scene_diff(self):
        """Test _get_scene_diff helper."""
        from houdini_mcp.tools import _get_scene_diff
        
        before = [
            {"path": "/obj/existing", "type": "geo", "name": "existing", "children": []}
        ]
        after = [
            {"path": "/obj/existing", "type": "geo", "name": "existing", "children": []},
            {"path": "/obj/new", "type": "null", "name": "new", "children": []}
        ]
        
        diff = _get_scene_diff(before, after)
        
        assert "/obj/new" in diff["added"]
        assert len(diff["removed"]) == 0
        assert diff["has_changes"] is True
