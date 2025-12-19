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
        
        result = create_node("geo", "/obj", "my_geo", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/my_geo"
        assert result["node_type"] == "geo"
        assert result["node_name"] == "my_geo"
    
    def test_create_node_auto_name(self, mock_connection):
        """Test creating a node with auto-generated name."""
        from houdini_mcp.tools import create_node
        
        result = create_node("sphere", "/obj", None, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "sphere" in result["node_path"]
    
    def test_create_node_parent_not_found(self, mock_connection):
        """Test creating a node with non-existent parent."""
        from houdini_mcp.tools import create_node
        
        result = create_node("geo", "/obj/nonexistent", None, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Parent node not found" in result["message"]
    
    def test_create_node_different_types(self, mock_connection):
        """Test creating different node types."""
        from houdini_mcp.tools import create_node
        
        for node_type in ["geo", "cam", "null", "light"]:
            result = create_node(node_type, "/obj", f"test_{node_type}", host="localhost", port=18811)
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


class TestExecuteCodeSafetyRails:
    """Tests for execute_code safety rails (HDMCP-11)."""
    
    # --- Dangerous Pattern Detection Tests ---
    
    def test_detects_hou_exit(self, mock_connection):
        """Test detection of hou.exit() pattern."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("hou.exit()", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert "Dangerous operations detected" in result["message"]
        assert "dangerous_patterns" in result
        assert any("hou.exit()" in p for p in result["dangerous_patterns"])
        assert "hint" in result
        assert "allow_dangerous" in result["hint"]
    
    def test_detects_os_remove(self, mock_connection):
        """Test detection of os.remove() pattern."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("import os; os.remove('/tmp/file')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert "dangerous_patterns" in result
        assert any("os.remove()" in p for p in result["dangerous_patterns"])
    
    def test_detects_os_unlink(self, mock_connection):
        """Test detection of os.unlink() pattern."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("import os; os.unlink('/tmp/file')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert any("os.unlink()" in p for p in result["dangerous_patterns"])
    
    def test_detects_shutil_rmtree(self, mock_connection):
        """Test detection of shutil.rmtree() pattern."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("import shutil; shutil.rmtree('/tmp/dir')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert any("shutil.rmtree()" in p for p in result["dangerous_patterns"])
    
    def test_detects_subprocess(self, mock_connection):
        """Test detection of subprocess pattern."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("import subprocess; subprocess.run(['ls'])", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert any("subprocess" in p for p in result["dangerous_patterns"])
    
    def test_detects_os_system(self, mock_connection):
        """Test detection of os.system() pattern."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("import os; os.system('ls')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert any("os.system()" in p for p in result["dangerous_patterns"])
    
    def test_detects_open_write_mode(self, mock_connection):
        """Test detection of open() with write mode."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("f = open('/tmp/file', 'w')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert any("open()" in p for p in result["dangerous_patterns"])
    
    def test_detects_open_append_mode(self, mock_connection):
        """Test detection of open() with append mode."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("f = open('/tmp/file', 'a')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert any("open()" in p for p in result["dangerous_patterns"])
    
    def test_detects_hipfile_clear(self, mock_connection):
        """Test detection of hou.hipFile.clear() pattern."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("hou.hipFile.clear()", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert any("hou.hipFile.clear()" in p for p in result["dangerous_patterns"])
    
    def test_detects_multiple_dangerous_patterns(self, mock_connection):
        """Test detection of multiple dangerous patterns in one code block."""
        from houdini_mcp.tools import execute_code
        
        code = """
import os
import subprocess
os.remove('/tmp/file')
subprocess.run(['ls'])
        """
        result = execute_code(code, "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "error"
        assert len(result["dangerous_patterns"]) >= 2
    
    def test_allows_safe_code(self, mock_connection):
        """Test that safe code passes detection."""
        from houdini_mcp.tools import execute_code
        
        safe_code = """
node = hou.node('/obj')
print('Hello')
x = 1 + 2
        """
        result = execute_code(safe_code, "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
    
    def test_allow_dangerous_flag(self, mock_connection):
        """Test that allow_dangerous=True allows dangerous code to execute."""
        from houdini_mcp.tools import execute_code
        
        # Use a pattern that would be detected but won't actually cause harm in mock
        result = execute_code(
            "x = 'hou.exit()'  # Just a string, not actual call", 
            "localhost", 18811, 
            capture_diff=False,
            allow_dangerous=True
        )
        
        # Should succeed since code is actually safe (just contains pattern in string)
        assert result["status"] == "success"
    
    def test_allow_dangerous_includes_warnings(self, mock_connection):
        """Test that allow_dangerous=True includes safety warnings in response."""
        from houdini_mcp.tools import execute_code
        
        # This code contains a pattern but we allow it
        result = execute_code(
            "print('Would call hou.exit() but just printing')", 
            "localhost", 18811, 
            capture_diff=False,
            allow_dangerous=True
        )
        
        # Code actually runs (pattern is in string), but warnings should be present
        assert result["status"] == "success"
        assert "dangerous_patterns_executed" in result
        assert "safety_warning" in result
    
    # --- Output Size Cap Tests ---
    
    def test_stdout_truncation(self, mock_connection):
        """Test that large stdout is truncated."""
        from houdini_mcp.tools import execute_code
        
        # Generate output larger than 100 bytes (using small size for test)
        code = "print('x' * 200)"
        result = execute_code(code, "localhost", 18811, capture_diff=False, max_stdout_size=100)
        
        assert result["status"] == "success"
        assert len(result["stdout"]) <= 100
        assert result["stdout_truncated"] is True
        assert "stdout_warning" in result
    
    def test_stderr_truncation(self, mock_connection):
        """Test that large stderr is truncated."""
        from houdini_mcp.tools import execute_code
        
        code = "import sys; sys.stderr.write('y' * 200)"
        result = execute_code(code, "localhost", 18811, capture_diff=False, max_stderr_size=100)
        
        assert result["status"] == "success"
        assert len(result["stderr"]) <= 100
        assert result["stderr_truncated"] is True
        assert "stderr_warning" in result
    
    def test_no_truncation_within_limits(self, mock_connection):
        """Test that output within limits is not truncated."""
        from houdini_mcp.tools import execute_code
        
        code = "print('hello')"
        result = execute_code(code, "localhost", 18811, capture_diff=False, max_stdout_size=100000)
        
        assert result["status"] == "success"
        assert "stdout_truncated" not in result
        assert "stderr_truncated" not in result
    
    def test_default_size_limits(self, mock_connection):
        """Test that default size limits are applied."""
        from houdini_mcp.tools import execute_code
        
        # Just verify the function works with defaults
        result = execute_code("print('test')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
    
    # --- Scene Diff Size Limit Tests ---
    
    def test_diff_truncation(self, mock_connection):
        """Test that scene diff is truncated when exceeding max_diff_nodes."""
        from houdini_mcp.tools import execute_code
        from tests.conftest import MockHouNode
        
        # Start with empty /obj
        obj_node = mock_connection.node("/obj")
        obj_node._children = []
        
        # The code will "create" nodes by modifying the mock during execution
        # We'll add nodes after the "before" snapshot is taken
        code_that_adds_nodes = '''
# This code simulates adding many nodes
# In real Houdini, this would create actual nodes
# In our mock, we'll inject nodes via the test
pass
'''
        
        # Instead, let's directly test the truncation logic in the result building
        # by patching _serialize_scene_state to return different before/after states
        from unittest.mock import patch
        
        # Mock the before state (empty) and after state (many nodes)
        before_state = []
        after_state = [
            {"path": f"/obj/node{i}", "type": "geo", "name": f"node{i}", "children": []}
            for i in range(10)
        ]
        
        call_count = [0]
        def mock_serialize(hou):
            call_count[0] += 1
            if call_count[0] == 1:
                return before_state  # Before execution
            else:
                return after_state   # After execution
        
        with patch('houdini_mcp.tools._serialize_scene_state', side_effect=mock_serialize):
            result = execute_code("pass", "localhost", 18811, capture_diff=True, max_diff_nodes=5)
        
        assert result["status"] == "success"
        assert "scene_changes" in result
        assert len(result["scene_changes"]["added_nodes"]) == 5  # Truncated to max_diff_nodes
        assert result["diff_truncated"] is True
        assert "diff_warning" in result
    
    def test_no_diff_truncation_within_limits(self, mock_connection):
        """Test that scene diff is not truncated when within limits."""
        from houdini_mcp.tools import execute_code
        import houdini_mcp.tools as tools_module
        
        # Small diff that shouldn't trigger truncation
        tools_module._before_scene = []
        tools_module._after_scene = [
            {"path": "/obj/node1", "type": "geo", "name": "node1", "children": []}
        ]
        
        result = execute_code("x = 1", "localhost", 18811, capture_diff=True, max_diff_nodes=1000)
        
        assert result["status"] == "success"
        assert "diff_truncated" not in result
    
    # --- Timeout Tests ---
    
    def test_timeout_parameter_accepted(self, mock_connection):
        """Test that timeout parameter is accepted."""
        from houdini_mcp.tools import execute_code
        
        # Quick code that should complete before timeout
        result = execute_code("x = 1", "localhost", 18811, capture_diff=False, timeout=10)
        
        assert result["status"] == "success"
    
    def test_timeout_error_message(self, mock_connection):
        """Test timeout error message format (using mock to simulate)."""
        from houdini_mcp.tools import execute_code
        import time
        from unittest.mock import patch
        
        # We can't easily test actual timeout with mock, but we can verify
        # the code structure handles it. For a real timeout test, we'd need
        # an integration test with actual Houdini.
        
        # Just verify normal code completes within reasonable timeout
        result = execute_code("print('fast')", "localhost", 18811, capture_diff=False, timeout=30)
        assert result["status"] == "success"
    
    # --- Empty Code Edge Case ---
    
    def test_empty_code_string(self, mock_connection):
        """Test handling of empty code string."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
        assert result["stdout"] == ""
        assert result["stderr"] == ""
        assert "Empty code" in result.get("message", "")
    
    def test_whitespace_only_code(self, mock_connection):
        """Test handling of whitespace-only code."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("   \n\t  ", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
        assert "Empty code" in result.get("message", "")
    
    # --- Unicode Support ---
    
    def test_unicode_in_stdout(self, mock_connection):
        """Test that unicode in stdout is handled correctly."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("print('Hello 世界 🌍')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
        assert "世界" in result["stdout"]
        assert "🌍" in result["stdout"]
    
    def test_unicode_in_stderr(self, mock_connection):
        """Test that unicode in stderr is handled correctly."""
        from houdini_mcp.tools import execute_code
        
        result = execute_code("import sys; sys.stderr.write('错误 ⚠️')", "localhost", 18811, capture_diff=False)
        
        assert result["status"] == "success"
        assert "错误" in result["stderr"]
    
    # --- Backward Compatibility ---
    
    def test_backward_compatible_signature(self, mock_connection):
        """Test that existing calls without new params still work."""
        from houdini_mcp.tools import execute_code
        
        # Old-style call with just positional args
        result = execute_code("x = 1", "localhost", 18811)
        assert result["status"] == "success"
        
        # Old-style with capture_diff
        result = execute_code("x = 1", "localhost", 18811, True)
        assert result["status"] == "success"
        assert "scene_changes" in result
        
        result = execute_code("x = 1", "localhost", 18811, False)
        assert result["status"] == "success"
        assert "scene_changes" not in result


class TestDangerousPatternDetection:
    """Unit tests for the _detect_dangerous_code helper function."""
    
    def test_detect_function_exists(self):
        """Test that _detect_dangerous_code function exists."""
        from houdini_mcp.tools import _detect_dangerous_code
        assert callable(_detect_dangerous_code)
    
    def test_detect_empty_code(self):
        """Test detection on empty code."""
        from houdini_mcp.tools import _detect_dangerous_code
        
        result = _detect_dangerous_code("")
        assert result == []
    
    def test_detect_safe_code(self):
        """Test detection on safe code."""
        from houdini_mcp.tools import _detect_dangerous_code
        
        result = _detect_dangerous_code("print('hello world')")
        assert result == []
    
    def test_detect_single_pattern(self):
        """Test detection of single dangerous pattern."""
        from houdini_mcp.tools import _detect_dangerous_code
        
        result = _detect_dangerous_code("hou.exit()")
        assert len(result) == 1
        assert "hou.exit()" in result[0]
    
    def test_detect_multiple_patterns(self):
        """Test detection of multiple dangerous patterns."""
        from houdini_mcp.tools import _detect_dangerous_code
        
        code = """
import os
import subprocess
os.remove('/file')
subprocess.call(['cmd'])
        """
        result = _detect_dangerous_code(code)
        assert len(result) >= 2
    
    def test_pattern_in_comment_still_detected(self):
        """Test that patterns in comments are still detected (conservative approach)."""
        from houdini_mcp.tools import _detect_dangerous_code
        
        # We intentionally detect patterns even in comments for safety
        result = _detect_dangerous_code("# hou.exit()")
        assert len(result) == 1
    
    def test_pattern_in_string_still_detected(self):
        """Test that patterns in strings are still detected (conservative approach)."""
        from houdini_mcp.tools import _detect_dangerous_code
        
        # We intentionally detect patterns even in strings for safety
        result = _detect_dangerous_code("x = 'hou.exit()'")
        assert len(result) == 1


class TestTruncateOutput:
    """Unit tests for the _truncate_output helper function."""
    
    def test_truncate_function_exists(self):
        """Test that _truncate_output function exists."""
        from houdini_mcp.tools import _truncate_output
        assert callable(_truncate_output)
    
    def test_no_truncation_needed(self):
        """Test when output is within limits."""
        from houdini_mcp.tools import _truncate_output
        
        output, truncated = _truncate_output("hello", 100)
        assert output == "hello"
        assert truncated is False
    
    def test_truncation_at_limit(self):
        """Test truncation exactly at limit."""
        from houdini_mcp.tools import _truncate_output
        
        output, truncated = _truncate_output("12345", 5)
        assert output == "12345"
        assert truncated is False
    
    def test_truncation_over_limit(self):
        """Test truncation when over limit."""
        from houdini_mcp.tools import _truncate_output
        
        output, truncated = _truncate_output("1234567890", 5)
        assert output == "12345"
        assert truncated is True
    
    def test_truncation_empty_string(self):
        """Test truncation with empty string."""
        from houdini_mcp.tools import _truncate_output
        
        output, truncated = _truncate_output("", 100)
        assert output == ""
        assert truncated is False
    
    def test_truncation_unicode(self):
        """Test truncation with unicode characters."""
        from houdini_mcp.tools import _truncate_output
        
        # Unicode characters may have different byte sizes
        output, truncated = _truncate_output("世界你好", 2)
        assert len(output) == 2
        assert truncated is True


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
        
        result = set_parameter("/obj/geo1", "tx", 5.0, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/geo1"
        assert result["param_name"] == "tx"
        assert result["value"] == 5.0
    
    def test_set_parameter_node_not_found(self, mock_connection):
        """Test setting parameter on non-existent node."""
        from houdini_mcp.tools import set_parameter
        
        result = set_parameter("/obj/nonexistent", "tx", 5.0, host="localhost", port=18811)
        
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
        
        result = set_parameter("/obj/geo1", "nonexistent", 5.0, host="localhost", port=18811)
        
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
        
        result = set_parameter("/obj/geo1", "t", [1.0, 2.0, 3.0], host="localhost", port=18811)
        
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
        
        result = get_node_info("/obj/geo1", True, 50, True, host="localhost", port=18811)
        
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
        
        result = get_node_info("/obj/geo1", False, 50, True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "parameters" not in result
    
    def test_get_node_info_not_found(self, mock_connection):
        """Test getting info for non-existent node."""
        from houdini_mcp.tools import get_node_info
        
        result = get_node_info("/obj/nonexistent", True, 50, True, host="localhost", port=18811)
        
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
        
        result = get_node_info("/obj/geo1", False, 50, True, host="localhost", port=18811)
        
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
        
        result = get_node_info("/obj/geo1", True, 10, True, host="localhost", port=18811)
        
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
        
        result = delete_node("/obj/geo1", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["deleted_path"] == "/obj/geo1"
    
    def test_delete_node_not_found(self, mock_connection):
        """Test deleting non-existent node."""
        from houdini_mcp.tools import delete_node
        
        result = delete_node("/obj/nonexistent", host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_delete_node_returns_name(self, mock_connection):
        """Test delete returns node name in message."""
        from houdini_mcp.tools import delete_node
        
        geo1 = MockHouNode(path="/obj/my_special_geo", name="my_special_geo", node_type="geo")
        mock_connection.add_node(geo1)
        
        result = delete_node("/obj/my_special_geo", host="localhost", port=18811)
        
        assert "my_special_geo" in result["message"]


class TestSceneOperations:
    """Tests for scene file operations."""
    
    def test_save_scene_success(self, mock_connection):
        """Test saving scene successfully."""
        from houdini_mcp.tools import save_scene
        
        result = save_scene(None, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "Scene saved" in result["message"]
        mock_connection.hipFile.save.assert_called_once()
    
    def test_save_scene_with_path(self, mock_connection):
        """Test saving scene to specific path."""
        from houdini_mcp.tools import save_scene
        
        result = save_scene("/path/to/new.hip", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["file_path"] == "/path/to/new.hip"
    
    def test_load_scene_success(self, mock_connection):
        """Test loading scene successfully."""
        from houdini_mcp.tools import load_scene
        
        result = load_scene("/path/to/scene.hip", host="localhost", port=18811)
        
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
        
        result = save_scene(None, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Disk full" in result["message"]
    
    def test_load_scene_error_handling(self, mock_connection):
        """Test load_scene handles errors."""
        from houdini_mcp.tools import load_scene
        
        mock_connection.hipFile.load.side_effect = Exception("File not found")
        
        result = load_scene("/nonexistent.hip", host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "File not found" in result["message"]


class TestSerializeScene:
    """Tests for scene serialization."""
    
    def test_serialize_scene_success(self, mock_connection):
        """Test serializing scene successfully."""
        from houdini_mcp.tools import serialize_scene
        
        result = serialize_scene("/obj", False, 10, host="localhost", port=18811)
        
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
        
        result = serialize_scene("/obj", False, 10, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert len(result["structure"]["children"]) == 1
    
    def test_serialize_scene_not_found(self, mock_connection):
        """Test serializing from non-existent root."""
        from houdini_mcp.tools import serialize_scene
        
        result = serialize_scene("/nonexistent", False, 10, host="localhost", port=18811)
        
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
        
        result = serialize_scene("/obj", True, 10, host="localhost", port=18811)
        
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
        
        result = serialize_scene("/obj", False, 1, host="localhost", port=18811)
        
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
        
        result = list_node_types(None, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "node_types" in result
        assert result["count"] > 0
    
    def test_list_node_types_with_category(self, mock_connection):
        """Test listing node types with category filter."""
        from houdini_mcp.tools import list_node_types
        
        result = list_node_types("Object", host="localhost", port=18811)
        
        assert result["status"] == "success"
        # All returned types should be from Object category
        for node_type in result["node_types"]:
            assert node_type["category"] == "Object"
    
    def test_list_node_types_nonexistent_category(self, mock_connection):
        """Test listing with non-existent category returns empty."""
        from houdini_mcp.tools import list_node_types
        
        result = list_node_types("NonExistentCategory", host="localhost", port=18811)
        
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


class TestListChildren:
    """Tests for list_children function (HDMCP-5)."""
    
    def test_list_children_basic(self, mock_connection):
        """Test listing children with basic info."""
        from houdini_mcp.tools import list_children
        
        # Create a parent with children
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        
        # Set up connection: noise input 0 -> grid output 0
        noise._inputs = [grid]
        grid._outputs = [noise]
        
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            children=[grid, noise]
        )
        mock_connection.add_node(geo1)
        
        result = list_children("/obj/geo1", False, 10, 1000, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/geo1"
        assert result["count"] == 2
        assert len(result["children"]) == 2
        
        # Check grid node (no inputs)
        grid_info = next(c for c in result["children"] if c["name"] == "grid1")
        assert grid_info["path"] == "/obj/geo1/grid1"
        assert grid_info["type"] == "grid"
        assert grid_info["inputs"] == []
        assert grid_info["outputs"] == ["/obj/geo1/noise1"]
        
        # Check noise node (has input from grid)
        noise_info = next(c for c in result["children"] if c["name"] == "noise1")
        assert noise_info["path"] == "/obj/geo1/noise1"
        assert noise_info["type"] == "noise"
        assert len(noise_info["inputs"]) == 1
        assert noise_info["inputs"][0]["index"] == 0
        assert noise_info["inputs"][0]["source_node"] == "/obj/geo1/grid1"
        assert noise_info["inputs"][0]["output_index"] == 0
        assert noise_info["outputs"] == []
    
    def test_list_children_recursive(self, mock_connection):
        """Test recursive traversal of children."""
        from houdini_mcp.tools import list_children
        
        # Create nested hierarchy: geo1 -> subnet1 -> sphere1
        sphere = MockHouNode(path="/obj/geo1/subnet1/sphere1", name="sphere1", node_type="sphere")
        subnet = MockHouNode(
            path="/obj/geo1/subnet1",
            name="subnet1",
            node_type="subnet",
            children=[sphere]
        )
        geo1 = MockHouNode(
            path="/obj/geo1",
            name="geo1",
            node_type="geo",
            children=[subnet]
        )
        mock_connection.add_node(geo1)
        
        result = list_children("/obj/geo1", recursive=True, max_depth=10, max_nodes=1000, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 2  # subnet and sphere
        
        paths = [c["path"] for c in result["children"]]
        assert "/obj/geo1/subnet1" in paths
        assert "/obj/geo1/subnet1/sphere1" in paths
    
    def test_list_children_max_depth(self, mock_connection):
        """Test max_depth limit is respected."""
        from houdini_mcp.tools import list_children
        
        # Create deep hierarchy
        level3 = MockHouNode(path="/obj/geo1/l1/l2/l3", name="l3", node_type="null")
        level2 = MockHouNode(path="/obj/geo1/l1/l2", name="l2", node_type="null", children=[level3])
        level1 = MockHouNode(path="/obj/geo1/l1", name="l1", node_type="null", children=[level2])
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo", children=[level1])
        mock_connection.add_node(geo1)
        
        result = list_children("/obj/geo1", recursive=True, max_depth=1, max_nodes=1000, host="localhost", port=18811)
        
        assert result["status"] == "success"
        # Should only get level1 and level2 (depth 1)
        assert result["count"] <= 2
    
    def test_list_children_max_nodes(self, mock_connection):
        """Test max_nodes limit is respected."""
        from houdini_mcp.tools import list_children
        
        # Create many children
        children = [MockHouNode(path=f"/obj/geo1/node{i}", name=f"node{i}", node_type="null") for i in range(20)]
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo", children=children)
        mock_connection.add_node(geo1)
        
        result = list_children("/obj/geo1", recursive=False, max_depth=10, max_nodes=10, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 10
        assert "warning" in result
    
    def test_list_children_node_not_found(self, mock_connection):
        """Test error when node not found."""
        from houdini_mcp.tools import list_children
        
        result = list_children("/obj/nonexistent", False, 10, 1000, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_list_children_empty(self, mock_connection):
        """Test listing children of node with no children."""
        from houdini_mcp.tools import list_children
        
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo", children=[])
        mock_connection.add_node(geo1)
        
        result = list_children("/obj/geo1", False, 10, 1000, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["children"] == []


class TestFindNodes:
    """Tests for find_nodes function (HDMCP-5)."""
    
    def test_find_nodes_wildcard_pattern(self, mock_connection):
        """Test finding nodes with wildcard pattern."""
        from houdini_mcp.tools import find_nodes
        
        # Create nodes with various names
        obj_node = mock_connection.node("/obj")
        noise1 = MockHouNode(path="/obj/noise1", name="noise1", node_type="noise")
        noise2 = MockHouNode(path="/obj/noise2", name="noise2", node_type="noise")
        grid1 = MockHouNode(path="/obj/grid1", name="grid1", node_type="grid")
        obj_node._children = [noise1, noise2, grid1]
        
        result = find_nodes("/obj", "noise*", None, 100, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["pattern"] == "noise*"
        
        names = [m["name"] for m in result["matches"]]
        assert "noise1" in names
        assert "noise2" in names
        assert "grid1" not in names
    
    def test_find_nodes_substring_match(self, mock_connection):
        """Test finding nodes with substring matching (no wildcards)."""
        from houdini_mcp.tools import find_nodes
        
        obj_node = mock_connection.node("/obj")
        my_noise = MockHouNode(path="/obj/my_noise_node", name="my_noise_node", node_type="noise")
        other = MockHouNode(path="/obj/other", name="other", node_type="null")
        obj_node._children = [my_noise, other]
        
        result = find_nodes("/obj", "noise", None, 100, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["matches"][0]["name"] == "my_noise_node"
    
    def test_find_nodes_type_filter(self, mock_connection):
        """Test finding nodes with type filter."""
        from houdini_mcp.tools import find_nodes
        
        obj_node = mock_connection.node("/obj")
        sphere1 = MockHouNode(path="/obj/sphere1", name="sphere1", node_type="sphere")
        sphere2 = MockHouNode(path="/obj/sphere2", name="sphere2", node_type="sphere")
        box1 = MockHouNode(path="/obj/box1", name="box1", node_type="box")
        obj_node._children = [sphere1, sphere2, box1]
        
        result = find_nodes("/obj", "*", "sphere", 100, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["node_type_filter"] == "sphere"
        
        for match in result["matches"]:
            assert match["type"] == "sphere"
    
    def test_find_nodes_recursive(self, mock_connection):
        """Test finding nodes recursively in hierarchy."""
        from houdini_mcp.tools import find_nodes
        
        # Create nested structure
        deep_noise = MockHouNode(path="/obj/geo1/subnet1/noise1", name="noise1", node_type="noise")
        subnet = MockHouNode(path="/obj/geo1/subnet1", name="subnet1", node_type="subnet", children=[deep_noise])
        geo1 = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo", children=[subnet])
        obj_node = mock_connection.node("/obj")
        obj_node._children = [geo1]
        
        result = find_nodes("/obj", "noise*", None, 100, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["matches"][0]["path"] == "/obj/geo1/subnet1/noise1"
    
    def test_find_nodes_max_results(self, mock_connection):
        """Test max_results limit."""
        from houdini_mcp.tools import find_nodes
        
        obj_node = mock_connection.node("/obj")
        many_nodes = [MockHouNode(path=f"/obj/node{i}", name=f"node{i}", node_type="null") for i in range(20)]
        obj_node._children = many_nodes
        
        result = find_nodes("/obj", "*", None, 10, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 10
        assert "warning" in result
    
    def test_find_nodes_root_not_found(self, mock_connection):
        """Test error when root not found."""
        from houdini_mcp.tools import find_nodes
        
        result = find_nodes("/obj/nonexistent", "*", None, 100, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Root node not found" in result["message"]
    
    def test_find_nodes_no_matches(self, mock_connection):
        """Test when no nodes match pattern."""
        from houdini_mcp.tools import find_nodes
        
        obj_node = mock_connection.node("/obj")
        grid = MockHouNode(path="/obj/grid1", name="grid1", node_type="grid")
        obj_node._children = [grid]
        
        result = find_nodes("/obj", "noise*", None, 100, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["matches"] == []


class TestGetNodeInfoExtended:
    """Tests for get_node_info with input_details (HDMCP-5)."""
    
    def test_get_node_info_with_input_details(self, mock_connection):
        """Test get_node_info includes detailed input connections."""
        from houdini_mcp.tools import get_node_info
        
        # Create connected nodes
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        
        # Connect: noise input 0 -> grid output 0
        noise._inputs = [grid]
        grid._outputs = [noise]
        
        mock_connection.add_node(grid)
        mock_connection.add_node(noise)
        
        result = get_node_info("/obj/geo1/noise1", include_params=False, max_params=50, 
                              include_input_details=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["path"] == "/obj/geo1/noise1"
        assert "input_connections" in result
        assert len(result["input_connections"]) == 1
        
        conn = result["input_connections"][0]
        assert conn["input_index"] == 0
        assert conn["source_node"] == "/obj/geo1/grid1"
        assert conn["source_output_index"] == 0
    
    def test_get_node_info_without_input_details(self, mock_connection):
        """Test get_node_info without input details."""
        from houdini_mcp.tools import get_node_info
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        mock_connection.add_node(grid)
        
        result = get_node_info("/obj/geo1/grid1", include_params=False, max_params=50,
                              include_input_details=False, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "input_connections" not in result
        assert "inputs" in result  # Basic inputs still included
    
    def test_get_node_info_multiple_inputs(self, mock_connection):
        """Test node with multiple input connections."""
        from houdini_mcp.tools import get_node_info
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        
        # Connect: merge has two inputs
        merge._inputs = [grid, sphere]
        grid._outputs = [merge]
        sphere._outputs = [merge]
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(merge)
        
        result = get_node_info("/obj/geo1/merge1", include_params=False, max_params=50,
                              include_input_details=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert len(result["input_connections"]) == 2
        
        # Check both connections
        sources = [conn["source_node"] for conn in result["input_connections"]]
        assert "/obj/geo1/grid1" in sources
        assert "/obj/geo1/sphere1" in sources
    
    def test_get_node_info_no_inputs(self, mock_connection):
        """Test node with no inputs."""
        from houdini_mcp.tools import get_node_info
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        grid._inputs = []
        mock_connection.add_node(grid)
        
        result = get_node_info("/obj/geo1/grid1", include_params=False, max_params=50,
                              include_input_details=True, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "input_connections" in result
        assert len(result["input_connections"]) == 0


class TestConnectNodes:
    """Tests for connect_nodes function (HDMCP-6)."""
    
    def test_connect_nodes_success(self, mock_connection):
        """Test connecting two nodes successfully."""
        from houdini_mcp.tools import connect_nodes
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(noise)
        
        result = connect_nodes("/obj/geo1/grid1", "/obj/geo1/noise1", 0, 0, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["source_node"] == "/obj/geo1/grid1"
        assert result["destination_node"] == "/obj/geo1/noise1"
        assert result["source_output_index"] == 0
        assert result["destination_input_index"] == 0
        
        # Verify connection was made
        assert noise._inputs[0] == grid
        assert noise in grid._outputs
    
    def test_connect_nodes_incompatible_types(self, mock_connection):
        """Test connecting incompatible node types returns error."""
        from houdini_mcp.tools import connect_nodes
        
        # SOP node
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        # DOP node
        dopnet = MockHouNode(path="/obj/dopnet1", name="dopnet1", node_type="dopnet")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(dopnet)
        
        result = connect_nodes("/obj/geo1/grid1", "/obj/dopnet1", 0, 0, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Incompatible node types" in result["message"]
        assert "Sop" in result["message"]
        assert "Dop" in result["message"]
    
    def test_connect_nodes_source_not_found(self, mock_connection):
        """Test error when source node not found."""
        from houdini_mcp.tools import connect_nodes
        
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        mock_connection.add_node(noise)
        
        result = connect_nodes("/obj/geo1/nonexistent", "/obj/geo1/noise1", 0, 0, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Source node not found" in result["message"]
    
    def test_connect_nodes_destination_not_found(self, mock_connection):
        """Test error when destination node not found."""
        from houdini_mcp.tools import connect_nodes
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        mock_connection.add_node(grid)
        
        result = connect_nodes("/obj/geo1/grid1", "/obj/geo1/nonexistent", 0, 0, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Destination node not found" in result["message"]
    
    def test_connect_nodes_replaces_existing(self, mock_connection):
        """Test connecting auto-disconnects existing connection."""
        from houdini_mcp.tools import connect_nodes
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(noise)
        
        # First connection: grid -> noise
        noise.setInput(0, grid)
        assert noise._inputs[0] == grid
        
        # Second connection: sphere -> noise (should replace)
        result = connect_nodes("/obj/geo1/sphere1", "/obj/geo1/noise1", 0, 0, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert noise._inputs[0] == sphere
        assert noise in sphere._outputs
        assert noise not in grid._outputs
    
    def test_connect_nodes_multiple_inputs(self, mock_connection):
        """Test connecting to different input indices."""
        from houdini_mcp.tools import connect_nodes
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(merge)
        
        # Connect grid to input 0
        result1 = connect_nodes("/obj/geo1/grid1", "/obj/geo1/merge1", 0, 0, host="localhost", port=18811)
        assert result1["status"] == "success"
        
        # Connect sphere to input 1
        result2 = connect_nodes("/obj/geo1/sphere1", "/obj/geo1/merge1", 1, 0, host="localhost", port=18811)
        assert result2["status"] == "success"
        
        assert merge._inputs[0] == grid
        assert merge._inputs[1] == sphere


class TestDisconnectNodeInput:
    """Tests for disconnect_node_input function (HDMCP-6)."""
    
    def test_disconnect_node_input_success(self, mock_connection):
        """Test disconnecting an input successfully."""
        from houdini_mcp.tools import disconnect_node_input
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(noise)
        
        # Connect first
        noise.setInput(0, grid)
        assert noise._inputs[0] == grid
        
        # Disconnect
        result = disconnect_node_input("/obj/geo1/noise1", 0, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["was_connected"] is True
        assert result["previous_source"] == "/obj/geo1/grid1"
        assert noise._inputs[0] is None
    
    def test_disconnect_node_input_already_disconnected(self, mock_connection):
        """Test disconnecting an already disconnected input."""
        from houdini_mcp.tools import disconnect_node_input
        
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        noise._inputs = [None]
        mock_connection.add_node(noise)
        
        result = disconnect_node_input("/obj/geo1/noise1", 0, host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["was_connected"] is False
        assert "already disconnected" in result["message"]
    
    def test_disconnect_node_input_node_not_found(self, mock_connection):
        """Test error when node not found."""
        from houdini_mcp.tools import disconnect_node_input
        
        result = disconnect_node_input("/obj/geo1/nonexistent", 0, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_disconnect_node_input_invalid_index(self, mock_connection):
        """Test error when input index out of range."""
        from houdini_mcp.tools import disconnect_node_input
        
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        noise._inputs = [None]
        mock_connection.add_node(noise)
        
        result = disconnect_node_input("/obj/geo1/noise1", 5, host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "out of range" in result["message"]


class TestSetNodeFlags:
    """Tests for set_node_flags function (HDMCP-6)."""
    
    def test_set_node_flags_display_and_render(self, mock_connection):
        """Test setting display and render flags."""
        from houdini_mcp.tools import set_node_flags
        
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        mock_connection.add_node(sphere)
        
        result = set_node_flags("/obj/geo1/sphere1", display=True, render=True, bypass=None, 
                               host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["flags_set"]["display"] is True
        assert result["flags_set"]["render"] is True
        assert "bypass" not in result["flags_set"]
        assert sphere._display_flag is True
        assert sphere._render_flag is True
    
    def test_set_node_flags_bypass_only(self, mock_connection):
        """Test setting bypass flag only."""
        from houdini_mcp.tools import set_node_flags
        
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        mock_connection.add_node(noise)
        
        result = set_node_flags("/obj/geo1/noise1", display=None, render=None, bypass=True,
                               host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["flags_set"]["bypass"] is True
        assert "display" not in result["flags_set"]
        assert "render" not in result["flags_set"]
        assert noise._bypass is True
    
    def test_set_node_flags_all_none(self, mock_connection):
        """Test setting no flags (all None)."""
        from houdini_mcp.tools import set_node_flags
        
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        mock_connection.add_node(sphere)
        
        result = set_node_flags("/obj/geo1/sphere1", display=None, render=None, bypass=None,
                               host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert len(result["flags_set"]) == 0
        assert "No flags were set" in result["message"]
    
    def test_set_node_flags_node_not_found(self, mock_connection):
        """Test error when node not found."""
        from houdini_mcp.tools import set_node_flags
        
        result = set_node_flags("/obj/geo1/nonexistent", display=True, render=None, bypass=None,
                               host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_set_node_flags_mixed_values(self, mock_connection):
        """Test setting mixed flag values."""
        from houdini_mcp.tools import set_node_flags
        
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        sphere._display_flag = True
        sphere._render_flag = True
        mock_connection.add_node(sphere)
        
        # Turn off display, keep render on
        result = set_node_flags("/obj/geo1/sphere1", display=False, render=None, bypass=None,
                               host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["flags_set"]["display"] is False
        assert sphere._display_flag is False
        assert sphere._render_flag is True  # Unchanged


class TestReorderInputs:
    """Tests for reorder_inputs function (HDMCP-6)."""
    
    def test_reorder_inputs_swap_first_two(self, mock_connection):
        """Test swapping first two inputs on a merge node."""
        from houdini_mcp.tools import reorder_inputs
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        box = MockHouNode(path="/obj/geo1/box1", name="box1", node_type="box")
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(box)
        mock_connection.add_node(merge)
        
        # Connect: grid->0, sphere->1, box->2
        merge.setInput(0, grid)
        merge.setInput(1, sphere)
        merge.setInput(2, box)
        
        # Swap first two: [1, 0, 2]
        result = reorder_inputs("/obj/geo1/merge1", [1, 0, 2], host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["reconnection_count"] == 3
        
        # Check new order: sphere->0, grid->1, box->2
        assert merge._inputs[0] == sphere
        assert merge._inputs[1] == grid
        assert merge._inputs[2] == box
    
    def test_reorder_inputs_reverse_three(self, mock_connection):
        """Test reversing three inputs."""
        from houdini_mcp.tools import reorder_inputs
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        box = MockHouNode(path="/obj/geo1/box1", name="box1", node_type="box")
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(box)
        mock_connection.add_node(merge)
        
        merge.setInput(0, grid)
        merge.setInput(1, sphere)
        merge.setInput(2, box)
        
        # Reverse: [2, 1, 0]
        result = reorder_inputs("/obj/geo1/merge1", [2, 1, 0], host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert merge._inputs[0] == box
        assert merge._inputs[1] == sphere
        assert merge._inputs[2] == grid
    
    def test_reorder_inputs_node_not_found(self, mock_connection):
        """Test error when node not found."""
        from houdini_mcp.tools import reorder_inputs
        
        result = reorder_inputs("/obj/geo1/nonexistent", [1, 0], host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_reorder_inputs_invalid_order_length(self, mock_connection):
        """Test error when new_order length exceeds inputs."""
        from houdini_mcp.tools import reorder_inputs
        
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        merge._inputs = [None, None]  # Only 2 inputs
        mock_connection.add_node(merge)
        
        result = reorder_inputs("/obj/geo1/merge1", [0, 1, 2, 3, 4], host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "exceeds number of inputs" in result["message"]
    
    def test_reorder_inputs_invalid_indices(self, mock_connection):
        """Test error when indices are out of range."""
        from houdini_mcp.tools import reorder_inputs
        
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        merge._inputs = [None, None, None]
        mock_connection.add_node(merge)
        
        result = reorder_inputs("/obj/geo1/merge1", [0, 5, 2], host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Invalid indices" in result["message"]
    
    def test_reorder_inputs_with_gaps(self, mock_connection):
        """Test reordering with some None inputs."""
        from houdini_mcp.tools import reorder_inputs
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        
        mock_connection.add_node(grid)
        mock_connection.add_node(sphere)
        mock_connection.add_node(merge)
        
        # Connect with gap: grid->0, None->1, sphere->2
        merge.setInput(0, grid)
        merge.setInput(2, sphere)
        
        # Swap: [2, 1, 0]
        result = reorder_inputs("/obj/geo1/merge1", [2, 1, 0], host="localhost", port=18811)
        
        assert result["status"] == "success"
        # sphere->0, None->1, grid->2
        assert merge._inputs[0] == sphere
        assert merge._inputs[1] is None
        assert merge._inputs[2] == grid
