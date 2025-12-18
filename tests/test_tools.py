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
    
    def test_get_scene_info_connection_error(self):
        """Test get_scene_info handles connection errors."""
        from houdini_mcp.tools import get_scene_info
        
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        # Mock hrpyc to fail
        mock_hrpyc = MagicMock()
        mock_hrpyc.import_remote_module = MagicMock(
            side_effect=ConnectionError("Connection refused")
        )
        
        with patch.dict('sys.modules', {'hrpyc': mock_hrpyc}):
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
