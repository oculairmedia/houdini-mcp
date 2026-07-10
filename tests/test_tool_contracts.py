"""Tests that validate tool contracts and documented examples."""

import inspect
import re


class TestExecuteCodeContract:
    """Validate execute_code tool contract."""

    def test_execute_code_docstring_mentions_preinjected_hou(self):
        """Ensure execute_code docstring clearly states hou is pre-injected."""
        from houdini_mcp.tools import execute_code

        docstring = execute_code.__doc__
        assert docstring is not None, "execute_code must have a docstring"

        # Check for key phrases
        docstring_lower = docstring.lower()
        assert "pre-inject" in docstring_lower or "available" in docstring_lower, (
            "Docstring must mention that hou is pre-injected or available"
        )

    def test_execute_code_parameter_types(self):
        """Validate execute_code parameter type hints."""
        from houdini_mcp.tools import execute_code

        sig = inspect.signature(execute_code)

        # Check required parameters
        assert "code" in sig.parameters
        assert sig.parameters["code"].annotation is str

        # Check optional parameters have correct types
        assert sig.parameters["capture_diff"].annotation is bool
        assert sig.parameters["allow_dangerous"].annotation is bool
        assert sig.parameters["allow_heavy_geometry"].annotation is bool

    def test_detect_import_hou_function_exists(self):
        """Verify _detect_import_hou helper exists."""
        from houdini_mcp.tools._common import _detect_import_hou

        assert callable(_detect_import_hou)

    def test_detect_import_hou_catches_basic_import(self):
        """Test _detect_import_hou catches 'import hou'."""
        from houdini_mcp.tools._common import _detect_import_hou

        assert _detect_import_hou("import hou")
        assert _detect_import_hou("import hou\n")
        assert _detect_import_hou("import hou  # comment")
        assert _detect_import_hou("import hou; print('test')")

    def test_detect_import_hou_catches_from_import(self):
        """Test _detect_import_hou catches 'from hou import'."""
        from houdini_mcp.tools._common import _detect_import_hou

        assert _detect_import_hou("from hou import node")
        assert _detect_import_hou("from hou import node, parm")

    def test_detect_import_hou_ignores_safe_code(self):
        """Test _detect_import_hou doesn't flag safe code."""
        from houdini_mcp.tools._common import _detect_import_hou

        assert not _detect_import_hou("hou.node('/obj')")
        assert not _detect_import_hou("# This uses hou")
        assert not _detect_import_hou("x = hou.applicationVersion()")


class TestRenderViewportContract:
    """Validate render_viewport tool contract."""

    def test_render_viewport_parameter_names(self):
        """Ensure render_viewport uses correct parameter names."""
        from houdini_mcp.tools import render_viewport

        sig = inspect.signature(render_viewport)

        # Should have these parameters
        expected_params = {
            "camera_position",
            "camera_rotation",
            "look_at",
            "resolution",
            "renderer",
            "output_format",
            "auto_frame",
            "orthographic",
            "karma_engine",
        }

        actual_params = set(sig.parameters.keys()) - {"host", "port"}
        assert expected_params == actual_params, (
            f"render_viewport parameters mismatch. "
            f"Expected: {expected_params}, Got: {actual_params}"
        )

        # Should NOT have these (common mistakes)
        forbidden_params = {"width", "height", "camera_path"}
        assert not (forbidden_params & actual_params), (
            f"render_viewport should not have parameters: {forbidden_params & actual_params}"
        )

    def test_render_viewport_resolution_is_list(self):
        """Ensure resolution parameter is typed as list."""
        from houdini_mcp.tools import render_viewport

        sig = inspect.signature(render_viewport)
        resolution_param = sig.parameters["resolution"]

        # Should be list[int] | None
        annotation_str = str(resolution_param.annotation)
        assert "list" in annotation_str.lower() or "none" in annotation_str.lower()

    def test_render_viewport_docstring_documents_resolution_format(self):
        """Ensure docstring clearly documents resolution as [width, height]."""
        from houdini_mcp.tools import render_viewport

        docstring = render_viewport.__doc__
        assert docstring is not None

        # Check for list format documentation
        assert "[width, height]" in docstring or "width, height" in docstring, (
            "Docstring must document resolution format"
        )


class TestRenderQuadViewContract:
    """Validate render_quad_view tool contract."""

    def test_render_quad_view_parameter_names(self):
        """Ensure render_quad_view has correct parameters."""
        from houdini_mcp.tools import render_quad_view

        sig = inspect.signature(render_quad_view)

        expected_params = {
            "resolution",
            "renderer",
            "output_format",
            "orthographic",
            "include_perspective",
            "karma_engine",
        }

        actual_params = set(sig.parameters.keys()) - {"host", "port"}
        assert expected_params == actual_params


class TestDocumentedExamplesValid:
    """Validate that documented examples follow tool contracts."""

    def test_readme_execute_code_example_no_import_hou(self):
        """Ensure README examples don't use 'import hou'."""
        import pathlib

        readme_path = pathlib.Path(__file__).parent.parent / "README.md"
        if not readme_path.exists():
            return  # Skip if README not found

        readme_content = readme_path.read_text()

        # Find all code blocks that might use execute_code
        code_blocks = re.findall(r"```(?:python|bash)?\n(.*?)```", readme_content, re.DOTALL)

        for block in code_blocks:
            if "execute_code" in block or "hou." in block:
                # This block references Houdini - check it doesn't import
                assert "import hou" not in block, (
                    f"README example incorrectly uses 'import hou':\n{block}"
                )

    def test_server_py_execute_code_example_no_import_hou(self):
        """Ensure server.py docstring example doesn't use 'import hou'."""
        import pathlib

        server_path = pathlib.Path(__file__).parent.parent / "houdini_mcp" / "server.py"
        assert server_path.exists()

        content = server_path.read_text()

        # Find execute_code function and its docstring
        if "def execute_code" in content and "Example:" in content:
            # Extract the section between execute_code and the next function
            execute_code_section = content.split("def execute_code")[1]
            if "Example:" in execute_code_section:
                example_section = execute_code_section.split("Example:")[1].split("def ")[0]
                assert "import hou" not in example_section, (
                    "server.py execute_code example incorrectly uses 'import hou'"
                )

    def test_examples_directory_no_import_hou(self):
        """Ensure example Python files don't use 'import hou'."""
        import pathlib

        examples_dir = pathlib.Path(__file__).parent.parent / "examples"
        if not examples_dir.exists():
            return

        for py_file in examples_dir.rglob("*.py"):
            content = py_file.read_text()
            assert "import hou" not in content, (
                f"Example file {py_file.name} incorrectly uses 'import hou'"
            )


class TestToolSchemaExportability:
    """Validate that tool signatures can be exported as JSON schemas."""

    def test_execute_code_parameters_json_serializable(self):
        """Ensure execute_code parameters can be described in JSON schema."""
        from houdini_mcp.tools import execute_code

        sig = inspect.signature(execute_code)

        # All parameters should have serializable types
        for param_name, param in sig.parameters.items():
            annotation = param.annotation
            if annotation == inspect.Parameter.empty:
                continue

            # Should be basic types or None
            annotation_str = str(annotation)
            # Just verify it's a reasonable type hint
            assert any(
                t in annotation_str for t in ["str", "int", "bool", "float", "list", "dict", "None"]
            ), f"Parameter {param_name} has non-serializable type: {annotation}"

    def test_render_viewport_parameters_json_serializable(self):
        """Ensure render_viewport parameters can be described in JSON schema."""
        from houdini_mcp.tools import render_viewport

        sig = inspect.signature(render_viewport)

        for param_name, param in sig.parameters.items():
            annotation = param.annotation
            if annotation == inspect.Parameter.empty:
                continue

            annotation_str = str(annotation)
            assert any(
                t in annotation_str for t in ["str", "int", "bool", "float", "list", "dict", "None"]
            ), f"Parameter {param_name} has non-serializable type: {annotation}"


class TestMinimalValidExamplesInDocs:
    """Validate that minimal valid examples exist for key tools."""

    def test_tool_contracts_doc_exists(self):
        """Ensure tool-contracts.md documentation exists."""
        import pathlib

        doc_path = pathlib.Path(__file__).parent.parent / "docs" / "tool-contracts.md"
        assert doc_path.exists(), "docs/tool-contracts.md must exist"

        content = doc_path.read_text()
        assert "execute_code" in content
        assert "render_viewport" in content
        assert "pre-inject" in content.lower() or "pre-injected" in content.lower()

    def test_tool_contracts_doc_has_examples(self):
        """Ensure tool-contracts.md has minimal valid examples."""
        import pathlib

        doc_path = pathlib.Path(__file__).parent.parent / "docs" / "tool-contracts.md"
        if not doc_path.exists():
            return

        content = doc_path.read_text()

        # Should have code examples
        assert "```python" in content
        # Should document the import hou issue
        assert "import hou" in content
        # Should have correct examples
        assert "render_viewport()" in content or "execute_code(" in content
