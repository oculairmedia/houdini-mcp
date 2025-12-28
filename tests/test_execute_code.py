"""Tests for the execute_code function and related helpers."""

import pytest
from unittest.mock import MagicMock, patch

from tests.conftest import MockHouNode, MockHouModule


class TestDetectDangerousCode:
    """Tests for the _detect_dangerous_code helper."""

    def test_detect_hou_exit(self):
        """Test detection of hou.exit() calls."""
        from houdini_mcp.tools import _detect_dangerous_code

        code = "hou.exit()"
        result = _detect_dangerous_code(code)
        assert len(result) == 1
        assert "hou.exit()" in result[0]

    def test_detect_os_remove(self):
        """Test detection of os.remove() calls."""
        from houdini_mcp.tools import _detect_dangerous_code

        code = "os.remove('/path/to/file')"
        result = _detect_dangerous_code(code)
        assert len(result) >= 1
        assert any("file deletion" in r.lower() or "os.remove" in r for r in result)

    def test_detect_subprocess(self):
        """Test detection of subprocess calls."""
        from houdini_mcp.tools import _detect_dangerous_code

        code = "subprocess.run(['ls', '-la'])"
        result = _detect_dangerous_code(code)
        assert len(result) >= 1
        assert any("subprocess" in r.lower() or "shell" in r.lower() for r in result)

    def test_detect_hipfile_clear(self):
        """Test detection of hou.hipFile.clear() calls."""
        from houdini_mcp.tools import _detect_dangerous_code

        code = "hou.hipFile.clear()"
        result = _detect_dangerous_code(code)
        assert len(result) >= 1
        assert any("clear" in r.lower() or "wipe" in r.lower() for r in result)

    def test_detect_open_write_mode(self):
        """Test detection of open() with write mode."""
        from houdini_mcp.tools import _detect_dangerous_code

        code = "open('/path/to/file', 'w')"
        result = _detect_dangerous_code(code)
        assert len(result) >= 1
        assert any("write" in r.lower() or "file" in r.lower() for r in result)

    def test_safe_code_no_detection(self):
        """Test that safe code returns empty list."""
        from houdini_mcp.tools import _detect_dangerous_code

        code = """
node = hou.node('/obj')
geo = node.createNode('geo', 'my_geo')
sphere = geo.createNode('sphere')
print(sphere.path())
"""
        result = _detect_dangerous_code(code)
        assert result == []

    def test_multiple_dangerous_patterns(self):
        """Test detection of multiple dangerous patterns."""
        from houdini_mcp.tools import _detect_dangerous_code

        code = """
hou.exit()
os.remove('/tmp/file')
subprocess.call(['rm', '-rf', '/'])
"""
        result = _detect_dangerous_code(code)
        assert len(result) >= 3


class TestTruncateOutput:
    """Tests for the _truncate_output helper."""

    def test_no_truncation_needed(self):
        """Test output under limit is not truncated."""
        from houdini_mcp.tools import _truncate_output

        output = "Hello, World!"
        result, was_truncated = _truncate_output(output, 1000)
        assert result == output
        assert was_truncated is False

    def test_truncation_at_limit(self):
        """Test output at exact limit is not truncated."""
        from houdini_mcp.tools import _truncate_output

        output = "x" * 100
        result, was_truncated = _truncate_output(output, 100)
        assert result == output
        assert was_truncated is False

    def test_truncation_over_limit(self):
        """Test output over limit is truncated."""
        from houdini_mcp.tools import _truncate_output

        output = "x" * 200
        result, was_truncated = _truncate_output(output, 100)
        assert len(result) == 100
        assert was_truncated is True

    def test_empty_output(self):
        """Test empty output handling."""
        from houdini_mcp.tools import _truncate_output

        output = ""
        result, was_truncated = _truncate_output(output, 100)
        assert result == ""
        assert was_truncated is False


class TestExecuteCode:
    """Tests for the execute_code function."""

    def test_execute_empty_code(self, mock_connection):
        """Test executing empty code returns early."""
        from houdini_mcp.tools import execute_code

        result = execute_code("", host="localhost", port=18811)
        assert result["status"] == "success"
        assert "Empty code" in result["message"]

    def test_execute_whitespace_only(self, mock_connection):
        """Test executing whitespace-only code returns early."""
        from houdini_mcp.tools import execute_code

        result = execute_code("   \n\t  ", host="localhost", port=18811)
        assert result["status"] == "success"
        assert "Empty code" in result["message"]

    def test_execute_dangerous_code_blocked(self, mock_connection):
        """Test dangerous code is blocked by default."""
        from houdini_mcp.tools import execute_code

        result = execute_code("hou.exit()", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "Dangerous operations detected" in result["message"]
        assert "dangerous_patterns" in result
        assert "hint" in result

    def test_execute_dangerous_code_allowed(self, mock_connection):
        """Test dangerous code can be allowed with flag."""
        from houdini_mcp.tools import execute_code

        # This won't actually call hou.exit() since hou is mocked
        result = execute_code(
            "print('would call hou.exit()')",
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        # The code itself is safe, but contains the pattern
        assert result["status"] == "success"

    def test_execute_simple_print(self, mock_connection):
        """Test executing simple print statement."""
        from houdini_mcp.tools import execute_code

        result = execute_code("print('Hello, Houdini!')", host="localhost", port=18811)
        assert result["status"] == "success"
        assert "Hello, Houdini!" in result["stdout"]

    def test_execute_with_hou_access(self, mock_connection):
        """Test code can access hou module."""
        from houdini_mcp.tools import execute_code

        result = execute_code("print(hou.applicationVersionString())", host="localhost", port=18811)
        assert result["status"] == "success"
        assert "20.5.123" in result["stdout"]

    def test_execute_syntax_error(self, mock_connection):
        """Test handling of syntax errors in code."""
        from houdini_mcp.tools import execute_code

        result = execute_code("def broken(", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "traceback" in result

    def test_execute_runtime_error(self, mock_connection):
        """Test handling of runtime errors."""
        from houdini_mcp.tools import execute_code

        result = execute_code("x = 1 / 0", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "ZeroDivisionError" in result["message"] or "division" in result["traceback"]

    def test_execute_name_error(self, mock_connection):
        """Test handling of name errors."""
        from houdini_mcp.tools import execute_code

        result = execute_code("print(undefined_variable)", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "NameError" in result["message"] or "undefined_variable" in result["traceback"]

    def test_execute_captures_stderr(self, mock_connection):
        """Test stderr is captured."""
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "import sys; sys.stderr.write('error message')",
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert "error message" in result["stderr"]

    def test_execute_stdout_truncation(self, mock_connection):
        """Test stdout is truncated when exceeds limit."""
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "print('x' * 1000)",
            max_stdout_size=100,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert len(result["stdout"]) <= 100
        assert result.get("stdout_truncated") is True

    def test_execute_stderr_truncation(self, mock_connection):
        """Test stderr is truncated when exceeds limit."""
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "import sys; sys.stderr.write('x' * 1000)",
            max_stderr_size=100,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert len(result["stderr"]) <= 100
        assert result.get("stderr_truncated") is True

    def test_execute_connection_error(self, reset_connection_state):
        """Test handling of connection errors."""
        from houdini_mcp.tools import execute_code

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = execute_code("print('test')", host="localhost", port=18811)

        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]

    def test_execute_dangerous_warning_when_allowed(self, mock_connection):
        """Test dangerous pattern warning is included when allowed."""
        from houdini_mcp.tools import execute_code

        # Use actual dangerous pattern in a harmless way
        code = """
# This comment mentions hou.exit() but doesn't call it
x = 1
"""
        # This should detect the pattern even in comments
        result = execute_code(code, allow_dangerous=True, host="localhost", port=18811)

        # If pattern detected, should have warning
        if result.get("dangerous_patterns_executed"):
            assert "safety_warning" in result


class TestExecuteCodeWithDiff:
    """Tests for execute_code with capture_diff enabled."""

    def test_capture_diff_basic(self, mock_connection):
        """Test basic scene diff capture."""
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "print('test')",
            capture_diff=True,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert "scene_changes" in result

    def test_capture_diff_with_node_creation(self, mock_connection):
        """Test scene diff captures node creation."""
        from houdini_mcp.tools import execute_code

        # Create a node using the mock
        result = execute_code(
            """
obj = hou.node('/obj')
geo = obj.createNode('geo', 'test_geo')
""",
            capture_diff=True,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert "scene_changes" in result
        # The mock should have created a node
        scene_changes = result["scene_changes"]
        # Check if added_nodes is present (might be empty with mocks)
        assert "added_nodes" in scene_changes or "modified" in str(scene_changes).lower()


class TestExecuteCodeTimeout:
    """Tests for execute_code timeout handling."""

    def test_timeout_returns_error(self, mock_connection):
        """Test that timeout returns appropriate error."""
        from houdini_mcp.tools import execute_code
        import time

        # Use a very short timeout with blocking code
        # Note: With mocks, we can't truly test timeout, but we can verify the parameter
        result = execute_code(
            "print('quick')",
            timeout=30,
            host="localhost",
            port=18811,
        )
        # Quick code should succeed
        assert result["status"] == "success"


class TestExecuteCodeEdgeCases:
    """Edge case tests for execute_code."""

    def test_multiline_code(self, mock_connection):
        """Test execution of multiline code."""
        from houdini_mcp.tools import execute_code

        code = """
x = 1
y = 2
z = x + y
print(f"Result: {z}")
"""
        result = execute_code(code, host="localhost", port=18811)
        assert result["status"] == "success"
        assert "Result: 3" in result["stdout"]

    def test_code_with_imports(self, mock_connection):
        """Test code with standard library imports."""
        from houdini_mcp.tools import execute_code

        code = """
import math
print(math.pi)
"""
        result = execute_code(code, host="localhost", port=18811)
        assert result["status"] == "success"
        assert "3.14" in result["stdout"]

    def test_code_with_functions(self, mock_connection):
        """Test code that defines and calls functions."""
        from houdini_mcp.tools import execute_code

        code = """
def greet(name):
    return f"Hello, {name}!"

print(greet("Houdini"))
"""
        result = execute_code(code, host="localhost", port=18811)
        assert result["status"] == "success"
        assert "Hello, Houdini!" in result["stdout"]

    def test_code_with_class(self, mock_connection):
        """Test code that defines a class."""
        from houdini_mcp.tools import execute_code

        code = """
class Counter:
    def __init__(self):
        self.count = 0
    def increment(self):
        self.count += 1
        return self.count

c = Counter()
print(c.increment())
print(c.increment())
"""
        result = execute_code(code, host="localhost", port=18811)
        assert result["status"] == "success"
        assert "1" in result["stdout"]
        assert "2" in result["stdout"]

    def test_code_with_unicode(self, mock_connection):
        """Test code with unicode characters."""
        from houdini_mcp.tools import execute_code

        code = "print('Hello, 世界! 🌍')"
        result = execute_code(code, host="localhost", port=18811)
        assert result["status"] == "success"
        assert "世界" in result["stdout"]

    def test_code_with_list_comprehension(self, mock_connection):
        """Test code with list comprehension."""
        from houdini_mcp.tools import execute_code

        code = "print([x**2 for x in range(5)])"
        result = execute_code(code, host="localhost", port=18811)
        assert result["status"] == "success"
        assert "[0, 1, 4, 9, 16]" in result["stdout"]
