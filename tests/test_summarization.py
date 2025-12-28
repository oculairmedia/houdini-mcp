"""Tests for AI summarization module."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from houdini_mcp.tools import summarization


class TestEstimateTokens:
    """Tests for token estimation."""

    def test_estimate_tokens_string(self):
        """Test token estimation for strings."""
        text = "a" * 100  # 100 characters
        assert summarization.estimate_tokens(text) == 25  # 100/4

    def test_estimate_tokens_dict(self):
        """Test token estimation for dict."""
        data = {"key": "value" * 10}
        result = summarization.estimate_tokens(data)
        assert result > 0

    def test_estimate_tokens_list(self):
        """Test token estimation for list."""
        data = [{"x": i} for i in range(100)]
        result = summarization.estimate_tokens(data)
        assert result > 100  # Should be more than 100 tokens for 100 items


class TestShouldSummarize:
    """Tests for summarization decision logic."""

    def test_should_summarize_force_true(self):
        """Test force summarization."""
        assert summarization.should_summarize({}, force=True) is True

    def test_should_summarize_small_data(self):
        """Test small data doesn't get summarized."""
        small_data = {"count": 10}
        assert summarization.should_summarize(small_data) is False

    def test_should_summarize_large_data(self):
        """Test large data triggers summarization."""
        # Create data larger than threshold (default 5000 tokens = ~20000 chars)
        large_data = {"data": "x" * 30000}
        assert summarization.should_summarize(large_data) is True

    @patch.object(summarization, "SUMMARIZATION_ENABLED", False)
    def test_should_summarize_disabled(self):
        """Test summarization disabled."""
        large_data = {"data": "x" * 30000}
        assert summarization.should_summarize(large_data) is False


class TestGetSummarizationStatus:
    """Tests for summarization status."""

    def test_get_summarization_status_returns_config(self):
        """Test status returns all config keys."""
        status = summarization.get_summarization_status()

        assert "enabled" in status
        assert "model" in status
        assert "proxy_url" in status
        assert "auto_threshold_tokens" in status
        assert "target_summary_tokens" in status


class TestCallClaude:
    """Tests for Claude API calls."""

    @pytest.mark.asyncio
    @patch.object(summarization, "SUMMARIZATION_ENABLED", False)
    async def test_call_claude_disabled(self):
        """Test Claude call when disabled returns None."""
        result = await summarization._call_claude("test prompt")
        assert result is None

    @pytest.mark.asyncio
    async def test_call_claude_success(self):
        """Test successful Claude API call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"text": "Test summary"}]}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await summarization._call_claude("test prompt")
            assert result == "Test summary"

    @pytest.mark.asyncio
    async def test_call_claude_api_error(self):
        """Test Claude API error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error"

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await summarization._call_claude("test prompt")
            assert result is None

    @pytest.mark.asyncio
    async def test_call_claude_timeout(self):
        """Test Claude API timeout handling."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await summarization._call_claude("test prompt")
            assert result is None


class TestSummarizeGeometry:
    """Tests for geometry summarization."""

    @pytest.mark.asyncio
    async def test_summarize_geometry_adds_summary(self):
        """Test geometry summarization adds ai_summary field."""
        geo_data = {
            "point_count": 1000,
            "primitive_count": 500,
            "bounding_box": {"min": [0, 0, 0], "max": [1, 1, 1]},
        }

        with patch.object(summarization, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = "This is a cube with 1000 points."

            result = await summarization.summarize_geometry(geo_data)

            assert "ai_summary" in result
            assert result["ai_summary"] == "This is a cube with 1000 points."
            assert result["_summarized"] is True

    @pytest.mark.asyncio
    async def test_summarize_geometry_no_summary_on_error(self):
        """Test geometry data unchanged if Claude fails."""
        geo_data = {
            "point_count": 1000,
        }

        with patch.object(summarization, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = None

            result = await summarization.summarize_geometry(geo_data)

            assert "ai_summary" not in result
            assert "_summarized" not in result


class TestSummarizeErrors:
    """Tests for error summarization."""

    @pytest.mark.asyncio
    async def test_summarize_errors_adds_summary(self):
        """Test error summarization adds ai_summary field."""
        error_data = {
            "error_nodes": [
                {"path": "/obj/geo1/bad_node", "errors": ["Missing input"]},
            ],
            "error_count": 1,
        }

        with patch.object(summarization, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = "1 error found: missing input on bad_node."

            result = await summarization.summarize_errors(error_data)

            assert "ai_summary" in result
            assert result["_summarized"] is True


class TestSummarizeScene:
    """Tests for scene summarization."""

    @pytest.mark.asyncio
    async def test_summarize_scene_adds_summary(self):
        """Test scene summarization adds ai_summary field."""
        scene_data = {
            "children": [
                {"name": "geo1", "type": "geo"},
                {"name": "geo2", "type": "geo"},
            ],
        }

        with patch.object(summarization, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = "Simple scene with 2 geometry nodes."

            result = await summarization.summarize_scene(scene_data)

            assert "ai_summary" in result
            assert result["_summarized"] is True


class TestSummarizeRenderSettings:
    """Tests for render settings summarization."""

    @pytest.mark.asyncio
    async def test_summarize_render_settings_adds_summary(self):
        """Test render settings summarization adds ai_summary field."""
        render_data = {
            "rop_type": "karma",
            "settings": {
                "samples": 64,
                "resolution": [1920, 1080],
            },
        }

        with patch.object(summarization, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = "Karma render at 1080p with 64 samples."

            result = await summarization.summarize_render_settings(render_data)

            assert "ai_summary" in result
            assert result["_summarized"] is True
