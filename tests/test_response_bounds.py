"""Tests for response pagination, truncation, and size limits (HDMCP-52 / houdini-mcp-2t6).

Strict TDD test suite for bounded MCP responses with pagination cursors,
detail/compact modes, and hard size caps with multibyte-safe JSON truncation.
"""

import json


class TestResponsePagination:
    """Test pagination with limit/cursor/offset controls."""

    def test_paginate_empty_list(self):
        """Paginating an empty list returns empty result with no cursor."""
        from houdini_mcp.tools._common import paginate_list

        result = paginate_list([], limit=10)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["returned"] == 0
        assert result["has_more"] is False
        assert "cursor" not in result

    def test_paginate_single_item(self):
        """Paginating a single item returns it with no cursor."""
        from houdini_mcp.tools._common import paginate_list

        result = paginate_list([{"id": 1}], limit=10)
        assert result["items"] == [{"id": 1}]
        assert result["total"] == 1
        assert result["returned"] == 1
        assert result["has_more"] is False
        assert "cursor" not in result

    def test_paginate_under_limit(self):
        """Items under limit return all items with no cursor."""
        from houdini_mcp.tools._common import paginate_list

        items = [{"id": i} for i in range(5)]
        result = paginate_list(items, limit=10)
        assert result["items"] == items
        assert result["total"] == 5
        assert result["returned"] == 5
        assert result["has_more"] is False

    def test_paginate_at_limit(self):
        """Exactly at limit returns all items with no cursor."""
        from houdini_mcp.tools._common import paginate_list

        items = [{"id": i} for i in range(10)]
        result = paginate_list(items, limit=10)
        assert result["items"] == items
        assert result["total"] == 10
        assert result["returned"] == 10
        assert result["has_more"] is False

    def test_paginate_over_limit(self):
        """Items over limit return limited items with cursor."""
        from houdini_mcp.tools._common import paginate_list

        items = [{"id": i} for i in range(25)]
        result = paginate_list(items, limit=10)
        assert len(result["items"]) == 10
        assert result["items"] == items[:10]
        assert result["total"] == 25
        assert result["returned"] == 10
        assert result["has_more"] is True
        assert result["cursor"] == 10

    def test_paginate_with_cursor(self):
        """Using cursor returns next page."""
        from houdini_mcp.tools._common import paginate_list

        items = [{"id": i} for i in range(25)]
        result = paginate_list(items, limit=10, cursor=10)
        assert len(result["items"]) == 10
        assert result["items"] == items[10:20]
        assert result["total"] == 25
        assert result["returned"] == 10
        assert result["has_more"] is True
        assert result["cursor"] == 20

    def test_paginate_last_page(self):
        """Last page returns remaining items with no cursor."""
        from houdini_mcp.tools._common import paginate_list

        items = [{"id": i} for i in range(25)]
        result = paginate_list(items, limit=10, cursor=20)
        assert len(result["items"]) == 5
        assert result["items"] == items[20:25]
        assert result["total"] == 25
        assert result["returned"] == 5
        assert result["has_more"] is False
        assert "cursor" not in result

    def test_paginate_cursor_beyond_end(self):
        """Cursor beyond end returns empty page."""
        from houdini_mcp.tools._common import paginate_list

        items = [{"id": i} for i in range(25)]
        result = paginate_list(items, limit=10, cursor=30)
        assert result["items"] == []
        assert result["total"] == 25
        assert result["returned"] == 0
        assert result["has_more"] is False


class TestResponseTruncation:
    """Test JSON-safe response truncation with metadata."""

    def test_truncate_under_cap(self):
        """Response under cap is not truncated."""
        from houdini_mcp.tools._common import apply_response_cap

        data = {"status": "success", "items": [1, 2, 3]}
        result = apply_response_cap(data, max_bytes=1000)
        assert result["status"] == "success"
        assert result["items"] == [1, 2, 3]
        assert "_truncated" not in result

    def test_truncate_at_cap(self):
        """Response at cap boundary is not truncated."""
        from houdini_mcp.tools._common import apply_response_cap

        data = {"status": "success", "value": "x" * 100}
        json_str = json.dumps(data)
        cap = len(json_str)
        result = apply_response_cap(data, max_bytes=cap)
        assert "_truncated" not in result

    def test_truncate_over_cap(self):
        """Response over cap is truncated with metadata."""
        from houdini_mcp.tools._common import apply_response_cap

        data = {"status": "success", "items": list(range(1000))}
        result = apply_response_cap(data, max_bytes=500)

        # Should have truncation metadata
        assert result["_truncated"] is True
        assert "original_size_bytes" in result
        assert result["original_size_bytes"] > 500
        assert "truncated_size_bytes" in result
        assert result["truncated_size_bytes"] <= 500

        # Result must be valid JSON
        result_json = json.dumps(result)
        assert len(result_json) <= 500

        # Must parse back
        reparsed = json.loads(result_json)
        assert reparsed["_truncated"] is True

    def test_truncate_nested_fields(self):
        """Truncation works with deeply nested fields."""
        from houdini_mcp.tools._common import apply_response_cap

        data = {
            "status": "success",
            "nested": {"deep": {"items": list(range(1000))}},
        }
        result = apply_response_cap(data, max_bytes=300)
        assert result["_truncated"] is True
        json_str = json.dumps(result)
        assert len(json_str) <= 300

    def test_truncate_multibyte_strings(self):
        """Truncation is multibyte-safe (UTF-8)."""
        from houdini_mcp.tools._common import apply_response_cap

        # Unicode characters (emoji, CJK) use multiple bytes
        data = {"status": "success", "text": "Hello 世界 🌍" * 100}
        result = apply_response_cap(data, max_bytes=200)

        # Result must be valid JSON (no broken multibyte sequences)
        result_json = json.dumps(result, ensure_ascii=False)
        assert len(result_json.encode("utf-8")) <= 200

        # Must parse back without Unicode errors
        reparsed = json.loads(result_json)
        assert reparsed["_truncated"] is True

    def test_truncate_preserves_status(self):
        """Truncation always preserves status field."""
        from houdini_mcp.tools._common import apply_response_cap

        data = {"status": "error", "message": "x" * 1000, "items": list(range(1000))}
        result = apply_response_cap(data, max_bytes=200)
        assert result["status"] == "error"
        assert "_truncated" in result

    def test_truncate_malformed_json_recovery(self):
        """If truncation would create invalid JSON, it's fixed."""
        from houdini_mcp.tools._common import apply_response_cap

        data = {"items": ["a" * 500, "b" * 500, "c" * 500]}
        result = apply_response_cap(data, max_bytes=300)

        # Must be valid JSON
        result_json = json.dumps(result)
        reparsed = json.loads(result_json)
        assert reparsed["_truncated"] is True


class TestCompactDetailModes:
    """Test compact vs detail response modes."""

    def test_compact_mode_reduces_fields(self):
        """Compact mode excludes heavy fields."""
        from houdini_mcp.tools._common import apply_detail_mode

        full_data = {
            "path": "/obj/geo1",
            "type": "geo",
            "parameters": {"tx": 1.0, "ty": 2.0, "tz": 3.0},
            "children": [{"path": "/obj/geo1/sphere1"}],
            "metadata": "heavy field" * 100,
        }

        compact = apply_detail_mode(full_data, mode="compact")
        assert compact["path"] == "/obj/geo1"
        assert compact["type"] == "geo"
        assert "parameters" not in compact or compact.get("child_count") is not None
        assert "metadata" not in compact

    def test_detail_mode_includes_all_fields(self):
        """Detail mode includes all fields."""
        from houdini_mcp.tools._common import apply_detail_mode

        full_data = {
            "path": "/obj/geo1",
            "type": "geo",
            "parameters": {"tx": 1.0},
            "children": [],
        }

        detail = apply_detail_mode(full_data, mode="detail")
        assert detail == full_data

    def test_standard_mode_is_default(self):
        """Standard mode is a balanced default."""
        from houdini_mcp.tools._common import apply_detail_mode

        full_data = {"path": "/obj/geo1", "type": "geo", "parameters": {"tx": 1.0}}

        standard = apply_detail_mode(full_data, mode="standard")
        assert standard == full_data


class TestPropertyBasedBounds:
    """Property tests that no response exceeds configured cap."""

    def test_no_response_exceeds_cap_property(self):
        """Property: apply_response_cap never returns JSON larger than cap."""
        from houdini_mcp.tools._common import apply_response_cap

        for size in [100, 500, 1000, 5000, 16000]:
            # Generate various data structures
            data_samples = [
                {"items": list(range(10000))},
                {"text": "a" * 50000},
                {"nested": {"deep": {"value": list(range(1000))}}},
                {"status": "success", "data": {"x": "y" * 10000}},
            ]

            for data in data_samples:
                result = apply_response_cap(data, max_bytes=size)
                result_json = json.dumps(result)
                result_bytes = len(result_json.encode("utf-8"))

                # Property: result is always within cap
                assert result_bytes <= size, (
                    f"Response {result_bytes} bytes exceeds cap {size} bytes"
                )

                # Property: result is always valid JSON
                reparsed = json.loads(result_json)
                assert isinstance(reparsed, dict)

    def test_truncated_responses_always_valid_json(self):
        """Property: truncated responses are always valid, parseable JSON."""
        from houdini_mcp.tools._common import apply_response_cap

        test_cases = [
            {"items": list(range(10000))},
            {"text": "🌍" * 5000},  # Multibyte
            {"nested": {"a": {"b": {"c": list(range(1000))}}}},
        ]

        for data in test_cases:
            for cap in [100, 200, 500, 1000, 16000]:
                result = apply_response_cap(data, max_bytes=cap)
                result_json = json.dumps(result, ensure_ascii=False)

                # Must parse without errors
                reparsed = json.loads(result_json)
                assert isinstance(reparsed, dict)


class TestPerformanceAndSize:
    """Performance and size tests for response bounds."""

    def test_large_list_pagination_performance(self):
        """Pagination on large lists is fast."""
        import time

        from houdini_mcp.tools._common import paginate_list

        large_list = [{"id": i, "data": "x" * 100} for i in range(10000)]

        start = time.time()
        result = paginate_list(large_list, limit=20)
        elapsed = time.time() - start

        assert elapsed < 0.1  # Should be near instant
        assert len(result["items"]) == 20
        assert result["total"] == 10000

    def test_truncation_performance(self):
        """Truncation on large responses is reasonably fast."""
        import time

        from houdini_mcp.tools._common import apply_response_cap

        large_data = {"items": list(range(100000)), "text": "a" * 100000}

        start = time.time()
        result = apply_response_cap(large_data, max_bytes=16000)
        elapsed = time.time() - start

        assert elapsed < 1.0  # Should complete within 1 second
        assert result["_truncated"] is True

    def test_multibyte_string_truncation_correctness(self):
        """Multibyte truncation doesn't break character boundaries."""
        from houdini_mcp.tools._common import apply_response_cap

        # Mix of ASCII and multibyte
        data = {"text": "Hello世界🌍" * 1000}

        result = apply_response_cap(data, max_bytes=500)
        result_json = json.dumps(result, ensure_ascii=False)

        # Must be valid UTF-8
        result_json.encode("utf-8")  # Would raise if broken

        # Must parse
        reparsed = json.loads(result_json)
        assert reparsed["_truncated"] is True


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing tools."""

    def test_pagination_optional_in_existing_tools(self):
        """Pagination is opt-in; existing calls still work."""
        # This will be tested when we update actual tools
        # Placeholder for now
        pass

    def test_cap_disabled_by_default_initially(self):
        """Hard cap is opt-in during initial rollout."""
        # During migration, cap should be optional
        pass
