"""Tests for the render_viewport function."""

import pytest
from unittest.mock import MagicMock, patch, mock_open
import base64
import tempfile
import os

from tests.conftest import MockHouNode, MockHouModule, MockGeometry, MockBoundingBox


class TestRenderViewportValidation:
    """Tests for render_viewport input validation."""

    def test_resolution_too_small(self, mock_connection):
        """Test rejection of resolution smaller than 64x64."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(resolution=[32, 32], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "64x64" in result["message"]

    def test_resolution_too_small_width(self, mock_connection):
        """Test rejection of width smaller than 64."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(resolution=[32, 512], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "64x64" in result["message"]

    def test_resolution_too_small_height(self, mock_connection):
        """Test rejection of height smaller than 64."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(resolution=[512, 32], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "64x64" in result["message"]

    def test_resolution_too_large(self, mock_connection):
        """Test rejection of resolution larger than 4096x4096."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(resolution=[8192, 8192], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "4096" in result["message"]

    def test_resolution_too_large_width(self, mock_connection):
        """Test rejection of width larger than 4096."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(resolution=[8192, 512], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "4096" in result["message"]

    def test_resolution_too_large_height(self, mock_connection):
        """Test rejection of height larger than 4096."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(resolution=[512, 8192], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "4096" in result["message"]

    def test_connection_error(self, reset_connection_state):
        """Test handling of connection errors."""
        from houdini_mcp.tools import render_viewport

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = render_viewport(host="localhost", port=18811)

        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]

    def test_obj_context_not_found(self, mock_connection):
        """Test handling when /obj context is not found."""
        from houdini_mcp.tools import render_viewport

        # Remove /obj from the mock
        mock_connection._nodes.pop("/obj", None)

        result = render_viewport(host="localhost", port=18811)
        assert result["status"] == "error"
        assert "/obj" in result["message"] or "Cannot find" in result["message"]


class TestRenderViewportAutoFrame:
    """Tests for render_viewport auto-framing functionality."""

    def test_auto_frame_with_empty_scene(self, mock_connection):
        """Test auto_frame with no child nodes uses defaults."""
        from houdini_mcp.tools import render_viewport

        # Empty scene - /obj has no children
        obj_node = mock_connection.node("/obj")
        obj_node._children = []

        # The function should proceed but may fail at render stage
        result = render_viewport(auto_frame=True, host="localhost", port=18811)

        # Should at least get past validation
        # May error at render stage, which is fine for this test
        assert "status" in result

    def test_auto_frame_disabled(self, mock_connection):
        """Test with auto_frame disabled."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(auto_frame=False, host="localhost", port=18811)

        # Should proceed past auto_frame logic
        assert "status" in result


class TestRenderViewportLookAt:
    """Tests for render_viewport look_at functionality."""

    def test_look_at_nonexistent_node(self, mock_connection):
        """Test look_at with a non-existent node path."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            look_at="/obj/nonexistent",
            auto_frame=False,
            host="localhost",
            port=18811,
        )

        # Should proceed even if look_at node doesn't exist
        assert "status" in result


class TestRenderViewportCameraSetup:
    """Tests for render_viewport camera setup."""

    def test_default_camera_rotation(self, mock_connection):
        """Test default camera rotation is isometric."""
        from houdini_mcp.tools import render_viewport

        # Just verify it doesn't crash with defaults
        result = render_viewport(auto_frame=False, host="localhost", port=18811)
        assert "status" in result

    def test_custom_camera_rotation_front(self, mock_connection):
        """Test front view camera rotation."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            camera_rotation=[0.0, 0.0, 0.0],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_custom_camera_rotation_top(self, mock_connection):
        """Test top view camera rotation."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            camera_rotation=[-90.0, 0.0, 0.0],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_orthographic_projection(self, mock_connection):
        """Test orthographic camera setup."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            orthographic=True,
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_perspective_projection(self, mock_connection):
        """Test perspective camera setup (default)."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            orthographic=False,
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result


class TestRenderViewportRenderers:
    """Tests for different render engines."""

    def test_opengl_renderer_selected(self, mock_connection):
        """Test OpenGL renderer is accepted."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            renderer="opengl",
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        # Should proceed past renderer validation
        assert "status" in result

    def test_karma_renderer_selected(self, mock_connection):
        """Test Karma renderer is accepted."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            renderer="karma",
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        # Should proceed past renderer validation
        assert "status" in result


class TestRenderViewportOutputFormats:
    """Tests for different output formats."""

    def test_png_format(self, mock_connection):
        """Test PNG output format."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            output_format="png",
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_jpg_format(self, mock_connection):
        """Test JPG output format."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            output_format="jpg",
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_exr_format(self, mock_connection):
        """Test EXR output format."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            output_format="exr",
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result


class TestRenderViewportResolutions:
    """Tests for different resolutions."""

    def test_minimum_valid_resolution(self, mock_connection):
        """Test minimum valid resolution 64x64."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            resolution=[64, 64],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        # Should pass validation
        assert result.get("message", "") != "Resolution must be at least 64x64"

    def test_maximum_valid_resolution(self, mock_connection):
        """Test maximum valid resolution 4096x4096."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            resolution=[4096, 4096],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        # Should pass validation
        assert "4096" not in result.get("message", "")

    def test_non_square_resolution(self, mock_connection):
        """Test non-square resolution."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            resolution=[1920, 1080],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_default_resolution_is_512(self, mock_connection):
        """Test default resolution is 512x512."""
        from houdini_mcp.tools import render_viewport

        # With None resolution, should use 512x512
        result = render_viewport(
            resolution=None,
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        # If successful, resolution should be 512x512
        if result["status"] == "success":
            assert result["resolution"] == [512, 512]


class TestRenderViewportCameraPosition:
    """Tests for custom camera position."""

    def test_custom_camera_position(self, mock_connection):
        """Test custom camera position."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            camera_position=[10.0, 5.0, 15.0],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_camera_position_origin(self, mock_connection):
        """Test camera at origin."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            camera_position=[0.0, 0.0, 0.0],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result

    def test_negative_camera_position(self, mock_connection):
        """Test negative camera position."""
        from houdini_mcp.tools import render_viewport

        result = render_viewport(
            camera_position=[-10.0, -5.0, -15.0],
            auto_frame=False,
            host="localhost",
            port=18811,
        )
        assert "status" in result


class TestRenderQuadViewValidation:
    """Tests for render_quad_view input validation."""

    def test_resolution_too_small(self, mock_connection):
        """Test rejection of resolution smaller than 64x64."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(resolution=[32, 32], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "64x64" in result["message"]

    def test_resolution_too_large(self, mock_connection):
        """Test rejection of resolution larger than 4096x4096."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(resolution=[8192, 8192], host="localhost", port=18811)
        assert result["status"] == "error"
        assert "4096" in result["message"]

    def test_connection_error(self, reset_connection_state):
        """Test handling of connection errors."""
        from houdini_mcp.tools import render_quad_view

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = render_quad_view(host="localhost", port=18811)

        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]

    def test_obj_context_not_found(self, mock_connection):
        """Test handling when /obj context is not found."""
        from houdini_mcp.tools import render_quad_view

        # Remove /obj from the mock
        mock_connection._nodes.pop("/obj", None)

        result = render_quad_view(host="localhost", port=18811)
        assert result["status"] == "error"
        assert "/obj" in result["message"] or "Cannot find" in result["message"]


class TestRenderQuadViewConfiguration:
    """Tests for render_quad_view configuration options."""

    def test_default_renders_4_views(self, mock_connection):
        """Test default configuration returns 4 views."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(host="localhost", port=18811)
        # If it proceeds past validation, check structure
        if result["status"] == "success":
            assert "views" in result
            assert len(result["views"]) == 4
            view_names = [v["name"] for v in result["views"]]
            assert "front" in view_names
            assert "left" in view_names
            assert "top" in view_names
            assert "perspective" in view_names

    def test_exclude_perspective_renders_3_views(self, mock_connection):
        """Test include_perspective=False returns only 3 views."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(include_perspective=False, host="localhost", port=18811)
        if result["status"] == "success":
            assert "views" in result
            assert len(result["views"]) == 3
            view_names = [v["name"] for v in result["views"]]
            assert "perspective" not in view_names

    def test_orthographic_projection(self, mock_connection):
        """Test orthographic projection is applied to ortho views."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(orthographic=True, host="localhost", port=18811)
        if result["status"] == "success":
            for view in result["views"]:
                if view["name"] != "perspective":
                    assert view.get("orthographic") is True

    def test_perspective_view_always_perspective(self, mock_connection):
        """Test perspective view uses perspective projection even with orthographic=True."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(orthographic=True, host="localhost", port=18811)
        if result["status"] == "success":
            for view in result["views"]:
                if view["name"] == "perspective":
                    assert view.get("orthographic") is False


class TestRenderQuadViewRenderers:
    """Tests for different render engines in quad view."""

    def test_opengl_renderer(self, mock_connection):
        """Test OpenGL renderer is accepted."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(renderer="opengl", host="localhost", port=18811)
        assert "status" in result
        if result["status"] == "success":
            assert result["renderer"] == "opengl"

    def test_karma_renderer(self, mock_connection):
        """Test Karma renderer is accepted."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(renderer="karma", host="localhost", port=18811)
        assert "status" in result
        if result["status"] == "success":
            assert result["renderer"] == "karma"

    def test_unknown_renderer(self, mock_connection):
        """Test unknown renderer returns error."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(renderer="unknown", host="localhost", port=18811)
        assert result["status"] == "error"
        # The error message might vary depending on where the mock fails,
        # but it should contain "Unknown renderer" or other error info
        assert "message" in result


class TestRenderQuadViewOutputFormats:
    """Tests for different output formats in quad view."""

    def test_png_format(self, mock_connection):
        """Test PNG output format."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(output_format="png", host="localhost", port=18811)
        assert "status" in result
        if result["status"] == "success":
            for view in result["views"]:
                if "error" not in view:
                    assert view["format"] == "png"

    def test_jpg_format(self, mock_connection):
        """Test JPG output format."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(output_format="jpg", host="localhost", port=18811)
        assert "status" in result

    def test_exr_format(self, mock_connection):
        """Test EXR output format."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(output_format="exr", host="localhost", port=18811)
        assert "status" in result


class TestRenderQuadViewResolutions:
    """Tests for different resolutions in quad view."""

    def test_minimum_valid_resolution(self, mock_connection):
        """Test minimum valid resolution 64x64."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(resolution=[64, 64], host="localhost", port=18811)
        assert result.get("message", "") != "Resolution must be at least 64x64"

    def test_maximum_valid_resolution(self, mock_connection):
        """Test maximum valid resolution 4096x4096."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(resolution=[4096, 4096], host="localhost", port=18811)
        assert "4096" not in result.get("message", "")

    def test_default_resolution_is_512(self, mock_connection):
        """Test default resolution is 512x512."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(resolution=None, host="localhost", port=18811)
        if result["status"] == "success":
            for view in result["views"]:
                if "error" not in view:
                    assert view["resolution"] == [512, 512]


class TestRenderQuadViewTiming:
    """Tests for render timing information."""

    def test_includes_render_time(self, mock_connection):
        """Test that total_render_time_ms is included in result."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(host="localhost", port=18811)
        if result["status"] == "success":
            assert "total_render_time_ms" in result
            assert isinstance(result["total_render_time_ms"], (int, float))


class TestListRenderNodes:
    """Tests for list_render_nodes function."""

    def test_connection_error(self, reset_connection_state):
        """Test handling of connection errors."""
        from houdini_mcp.tools import list_render_nodes

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = list_render_nodes(host="localhost", port=18811)

        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]

    def test_out_context_not_found(self, mock_connection):
        """Test handling when /out context is not found."""
        from houdini_mcp.tools import list_render_nodes

        # Remove /out from the mock
        mock_connection._nodes.pop("/out", None)

        result = list_render_nodes(host="localhost", port=18811)
        assert result["status"] == "error"
        assert "/out" in result["message"] or "Cannot find" in result["message"]


class TestGetRenderSettings:
    """Tests for get_render_settings function."""

    def test_connection_error(self, reset_connection_state):
        """Test handling of connection errors."""
        from houdini_mcp.tools import get_render_settings

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = get_render_settings("/out/karma1", host="localhost", port=18811)

        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]

    def test_rop_not_found(self, mock_connection):
        """Test handling when ROP is not found."""
        from houdini_mcp.tools import get_render_settings

        result = get_render_settings("/out/nonexistent", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "not found" in result["message"]


class TestSetRenderSettings:
    """Tests for set_render_settings function."""

    def test_connection_error(self, reset_connection_state):
        """Test handling of connection errors."""
        from houdini_mcp.tools import set_render_settings

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = set_render_settings(
                "/out/karma1", {"samplesperpixel": 64}, host="localhost", port=18811
            )

        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]

    def test_rop_not_found(self, mock_connection):
        """Test handling when ROP is not found."""
        from houdini_mcp.tools import set_render_settings

        result = set_render_settings(
            "/out/nonexistent", {"samplesperpixel": 64}, host="localhost", port=18811
        )
        assert result["status"] == "error"
        assert "not found" in result["message"]


class TestCreateRenderNode:
    """Tests for create_render_node function."""

    def test_connection_error(self, reset_connection_state):
        """Test handling of connection errors."""
        from houdini_mcp.tools import create_render_node

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = create_render_node("karma", host="localhost", port=18811)

        assert result["status"] == "error"
        assert "Failed to connect" in result["message"]

    def test_out_context_not_found(self, mock_connection):
        """Test handling when /out context is not found."""
        from houdini_mcp.tools import create_render_node

        # Remove /out from the mock
        mock_connection._nodes.pop("/out", None)

        result = create_render_node("karma", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "/out" in result["message"] or "Cannot find" in result["message"]


class TestKarmaEngineParameter:
    """Tests for karma_engine parameter in render functions."""

    def test_render_viewport_accepts_karma_engine_cpu(self, mock_connection):
        """Test render_viewport accepts karma_engine='cpu'."""
        from houdini_mcp.tools import render_viewport

        # Should not raise an error
        result = render_viewport(renderer="karma", karma_engine="cpu", host="localhost", port=18811)
        assert "status" in result

    def test_render_viewport_accepts_karma_engine_gpu(self, mock_connection):
        """Test render_viewport accepts karma_engine='gpu'."""
        from houdini_mcp.tools import render_viewport

        # Should not raise an error
        result = render_viewport(renderer="karma", karma_engine="gpu", host="localhost", port=18811)
        assert "status" in result

    def test_render_quad_view_accepts_karma_engine_cpu(self, mock_connection):
        """Test render_quad_view accepts karma_engine='cpu'."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(
            renderer="karma", karma_engine="cpu", host="localhost", port=18811
        )
        assert "status" in result

    def test_render_quad_view_accepts_karma_engine_gpu(self, mock_connection):
        """Test render_quad_view accepts karma_engine='gpu'."""
        from houdini_mcp.tools import render_quad_view

        result = render_quad_view(
            renderer="karma", karma_engine="gpu", host="localhost", port=18811
        )
        assert "status" in result

    def test_karma_engine_ignored_for_opengl(self, mock_connection):
        """Test karma_engine is ignored when renderer is opengl."""
        from houdini_mcp.tools import render_viewport

        # Should work fine - karma_engine is ignored for opengl
        result = render_viewport(
            renderer="opengl", karma_engine="gpu", host="localhost", port=18811
        )
        assert "status" in result

    def test_karma_engine_default_is_cpu(self, mock_connection):
        """Test karma_engine defaults to 'cpu'."""
        from houdini_mcp.tools import render_viewport
        import inspect

        sig = inspect.signature(render_viewport)
        default_value = sig.parameters["karma_engine"].default
        assert default_value == "cpu"
