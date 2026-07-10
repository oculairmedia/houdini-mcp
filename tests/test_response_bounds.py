"""Tests for response pagination, truncation, and size limits (HDMCP-52 / houdini-mcp-2t6).

Strict TDD test suite for bounded MCP responses with pagination cursors,
detail/compact modes, and hard size caps with multibyte-safe JSON truncation.
"""

import json


class TestResponsePagination:
    """Test pagination with limit/cursor/offset controls."""

    def test_invalid_inputs_are_clamped_without_repeating_cursor(self):
        from houdini_mcp.tools._common import paginate_list

        result = paginate_list(list(range(5)), limit=0, cursor=-100)
        assert result["items"] == [0]
        assert result["cursor"] == 1
        assert result["has_more"] is True

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


class TestLegacyPaginationCompatibility:
    def test_direct_positional_host_port_calls_still_work(self, mock_connection):
        from houdini_mcp.tools.nodes import find_nodes, list_children, list_node_types

        assert list_node_types(None, 10, None, 0, "localhost", 18811)["status"] == "success"
        assert (
            list_children("/obj", False, 10, 1000, True, "localhost", 18811)["status"] == "success"
        )
        assert find_nodes("/obj", "*", None, 10, 0, "localhost", 18811)["status"] == "success"

    def test_next_offset_alias_is_preserved(self, mock_connection):
        from houdini_mcp.tools.nodes import list_node_types

        result = list_node_types(limit=1, cursor=0, host="localhost", port=18811)
        assert result["has_more"] is True
        assert result["next_offset"] == result["cursor"] == 1

    def test_find_nodes_clamps_zero_limit(self, mock_connection):
        from houdini_mcp.tools.nodes import find_nodes
        from tests.conftest import MockHouNode

        obj = mock_connection.node("/obj")
        child = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo")
        obj._children.append(child)
        result = find_nodes(limit=0, cursor=0, host="localhost", port=18811)
        assert result["returned"] == 1
        assert result["matches"][0]["path"] == "/obj/geo1"


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


# NOTE: TestCompactDetailModes removed - apply_detail_mode was not wired to production
# tools and has been removed from the PR scope. Compact mode is available via tool-specific
# compact=True parameters (e.g., get_node_info, list_children) which is tested elsewhere.


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


class TestProductionPathResponseCap:
    """Test that production tools enforce hard caps on final serialized responses."""

    def test_list_children_respects_cap(self, mock_connection):
        """list_children final JSON response never exceeds cap."""
        import json

        from houdini_mcp.tools.nodes import list_children
        from tests.conftest import MockHouNode

        mock_hou = mock_connection

        # Create a large child hierarchy
        large_children = []
        for i in range(200):
            child = MockHouNode(path=f"/obj/geo1/child{i}", name=f"child{i}", node_type="geo")
            large_children.append(child)

        # Create parent with many children
        parent = MockHouNode(
            path="/obj/geo1", name="geo1", node_type="geo", children=large_children
        )
        mock_hou.add_node(parent)

        # Call with small cap
        result = list_children("/obj/geo1", limit=100, host="localhost", port=18811)

        # Serialize and measure final size
        result_json = json.dumps(result, ensure_ascii=False)
        result_bytes = len(result_json.encode("utf-8"))

        # Should respect the DEFAULT_RESPONSE_CAP_BYTES (16KB)
        from houdini_mcp.tools._common import DEFAULT_RESPONSE_CAP_BYTES

        assert result_bytes <= DEFAULT_RESPONSE_CAP_BYTES, (
            f"list_children response {result_bytes} bytes exceeds cap {DEFAULT_RESPONSE_CAP_BYTES}"
        )

    def test_find_nodes_respects_cap(self, mock_connection):
        """find_nodes final JSON response never exceeds cap."""
        import json

        from houdini_mcp.tools.nodes import find_nodes
        from tests.conftest import MockHouNode

        mock_hou = mock_connection

        # Create many nested nodes
        children = []
        for i in range(500):
            child = MockHouNode(path=f"/obj/sphere{i}", name=f"sphere{i}", node_type="sphere")
            children.append(child)

        # Create obj node with many children
        obj = MockHouNode(path="/obj", name="obj", node_type="Object", children=children)
        mock_hou.add_node(obj)

        result = find_nodes("/obj", pattern="*", limit=200, host="localhost", port=18811)

        # Serialize and measure
        result_json = json.dumps(result, ensure_ascii=False)
        result_bytes = len(result_json.encode("utf-8"))

        from houdini_mcp.tools._common import DEFAULT_RESPONSE_CAP_BYTES

        assert result_bytes <= DEFAULT_RESPONSE_CAP_BYTES

    def test_list_node_types_respects_cap(self, mock_connection):
        """list_node_types final JSON response never exceeds cap."""
        import json

        from houdini_mcp.tools.nodes import list_node_types

        # Call with defaults (will populate cache and return results)
        result = list_node_types(host="localhost", port=18811)

        # Serialize and measure
        result_json = json.dumps(result, ensure_ascii=False)
        result_bytes = len(result_json.encode("utf-8"))

        from houdini_mcp.tools._common import DEFAULT_RESPONSE_CAP_BYTES

        assert result_bytes <= DEFAULT_RESPONSE_CAP_BYTES

    def test_get_parameter_schema_respects_cap(self, mock_connection):
        """get_parameter_schema final JSON response never exceeds cap."""
        import json

        from houdini_mcp.tools.parameters import get_parameter_schema
        from tests.conftest import MockHouNode

        mock_hou = mock_connection

        # Create a node with many parameters
        params = {}
        for i in range(300):
            params[f"parm{i}"] = 1.0

        node = MockHouNode(path="/obj/geo1", name="geo1", node_type="geo", params=params)
        mock_hou.add_node(node)

        result = get_parameter_schema("/obj/geo1", max_parms=200, host="localhost", port=18811)

        # Serialize and measure
        result_json = json.dumps(result, ensure_ascii=False)
        result_bytes = len(result_json.encode("utf-8"))

        from houdini_mcp.tools._common import DEFAULT_RESPONSE_CAP_BYTES

        assert result_bytes <= DEFAULT_RESPONSE_CAP_BYTES

    def test_get_geo_summary_respects_cap(self):
        """get_geo_summary final JSON response never exceeds cap.

        Exercises the real production path: get_geo_summary() -> execute_code()
        -> _add_response_metadata() -> apply_response_cap(). Only execute_code's
        Houdini-side execution is mocked (it returns oversized geometry JSON on
        stdout, as the real Houdini-side analysis code would for a dense mesh);
        the response-bounding logic itself is exercised for real.
        """
        from unittest.mock import patch

        from houdini_mcp.tools import get_geo_summary
        from houdini_mcp.tools._common import DEFAULT_RESPONSE_CAP_BYTES

        # Build an oversized geometry summary: many attributes, many groups,
        # and many sample points with several attribute values each. This
        # mirrors what a dense production SOP (many named attributes/groups)
        # would produce before bounding is applied.
        point_attrs = [{"name": f"point_attr_{i}", "type": "float", "size": 3} for i in range(200)]
        prim_attrs = [{"name": f"prim_attr_{i}", "type": "string", "size": 1} for i in range(200)]
        vertex_attrs = [{"name": f"vertex_attr_{i}", "type": "float", "size": 2} for i in range(50)]
        detail_attrs = [{"name": f"detail_attr_{i}", "type": "int", "size": 1} for i in range(50)]

        point_groups = [f"point_group_{i}" for i in range(200)]
        prim_groups = [f"prim_group_{i}" for i in range(200)]

        sample_points = [
            {
                "index": i,
                "P": [float(i), float(i) * 2, float(i) * 3],
                "N": [0.0, 1.0, 0.0],
                "Cd": [1.0, 0.5, 0.25],
                "extra_attr": f"sample_point_payload_{i}" * 5,
            }
            for i in range(16)
        ]

        oversized_geo_data = {
            "status": "success",
            "node_path": "/obj/geo1/dense_mesh1",
            "cook_state": "cooked",
            "point_count": 500000,
            "primitive_count": 250000,
            "vertex_count": 1000000,
            "bounding_box": {
                "min": [-10.0, -10.0, -10.0],
                "max": [10.0, 10.0, 10.0],
                "size": [20.0, 20.0, 20.0],
                "center": [0.0, 0.0, 0.0],
            },
            "attributes": {
                "point": point_attrs,
                "primitive": prim_attrs,
                "vertex": vertex_attrs,
                "detail": detail_attrs,
            },
            "groups": {
                "point": point_groups,
                "primitive": prim_groups,
            },
            "sample_points": sample_points,
        }

        oversized_json = json.dumps(oversized_geo_data)
        # Sanity check the fixture is actually oversized relative to the cap;
        # otherwise this test would not be exercising truncation at all.
        assert len(oversized_json.encode("utf-8")) > DEFAULT_RESPONSE_CAP_BYTES

        with patch("houdini_mcp.tools.code.execute_code") as mock_execute_code:
            mock_execute_code.return_value = {
                "status": "success",
                "stdout": oversized_json,
                "stderr": "",
            }

            result = get_geo_summary(
                "/obj/geo1/dense_mesh1",
                max_sample_points=16,
                host="localhost",
                port=18811,
            )

        # Final serialized response (as returned to the MCP client) must
        # respect the hard cap.
        result_json = json.dumps(result, ensure_ascii=False)
        result_bytes = len(result_json.encode("utf-8"))
        assert result_bytes <= DEFAULT_RESPONSE_CAP_BYTES, (
            f"get_geo_summary response {result_bytes} bytes exceeds cap "
            f"{DEFAULT_RESPONSE_CAP_BYTES}"
        )

        # It must actually have been truncated (proves the cap engaged, not
        # just that the mock happened to be small).
        assert result["_truncated"] is True
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/geo1/dense_mesh1"

        # Truncation retains useful bounded data, not metadata-only.
        preserved_something = any(
            key in result and result[key] for key in ("attributes", "groups", "sample_points")
        )
        assert preserved_something, "Truncated response should retain useful bounded data"


class TestSemanticTruncation:
    def test_truncated_page_cursor_advances_by_preserved_count(self):
        from houdini_mcp.tools._common import apply_response_cap

        result = apply_response_cap(
            {
                "status": "success",
                "children": [{"name": f"n{i}", "detail": "x" * 300} for i in range(20)],
                "returned": 20,
                "count": 20,
                "total": 20,
                "has_more": False,
            },
            max_bytes=1400,
        )
        preserved = len(result["children"])
        assert 0 < preserved < 20
        assert result["returned"] == result["count"] == preserved
        assert result["has_more"] is True
        assert result["cursor"] == result["next_offset"] == preserved

    def test_nested_geometry_categories_keep_bounded_prefixes(self):
        from houdini_mcp.tools._common import apply_response_cap

        result = apply_response_cap(
            {
                "status": "success",
                "attributes": {
                    "point": [{"name": f"p{i}", "detail": "x" * 100} for i in range(100)],
                    "primitive": [{"name": f"pr{i}", "detail": "x" * 100} for i in range(100)],
                },
            },
            max_bytes=1800,
        )
        assert result["attributes"]
        assert result["attributes_category_counts"]["point"]["original"] == 100
        assert _json_size(result) <= 1800

    def test_diagnostic_lists_are_preserved(self):
        from houdini_mcp.tools._common import apply_response_cap

        result = apply_response_cap(
            {
                "status": "success",
                "error_nodes": [{"path": f"/obj/n{i}", "error": "x" * 200} for i in range(100)],
            },
            max_bytes=1500,
        )
        assert result["error_nodes"]
        assert result["error_nodes_truncated"] is True

    def test_capped_page_preserves_next_offset(self):
        from houdini_mcp.tools._common import apply_response_cap

        result = apply_response_cap(
            {
                "status": "success",
                "children": [{"name": f"n{i}", "detail": "x" * 300} for i in range(20)],
                "returned": 20,
                "count": 20,
                "total": 100,
                "has_more": True,
                "cursor": 20,
                "next_offset": 20,
            },
            max_bytes=1400,
        )
        assert result["next_offset"] == result["cursor"] == len(result["children"])


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


class TestFinalSerializedSizeAccounting:
    """The cap applies to the final object, including metadata added by finalization."""

    def test_metadata_added_after_initial_measurement_cannot_cross_cap(self):
        """A near-cap response is re-capped after size metadata is inserted."""
        from houdini_mcp.tools._common import _add_response_metadata

        cap = 200
        # This payload is 172 bytes before metadata, but the size metadata pushes
        # it to 201 bytes unless finalization performs a second cap pass.
        payload = {"status": "success", "items": ["x" * 136]}
        assert len(json.dumps(payload).encode("utf-8")) < cap

        result = _add_response_metadata(payload, max_bytes=cap)

        assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= cap

    def test_truncated_size_bytes_equals_final_serialized_size(self):
        """Self-referential byte-count metadata converges to the final JSON size."""
        from houdini_mcp.tools._common import apply_response_cap

        result = apply_response_cap(
            {
                "status": "success",
                "items": [{"name": f"item-{i}", "data": "世界🌍" * 40} for i in range(100)],
            },
            max_bytes=1200,
        )
        final_size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))

        assert result["_truncated"] is True
        assert result["truncated_size_bytes"] == final_size
        assert final_size <= 1200


class TestMultibyteResponseBoundaries:
    """Test multibyte-safe truncation at response boundaries."""

    def test_multibyte_string_in_capped_response(self):
        """Multibyte UTF-8 strings don't break at response cap boundary."""
        import json

        from houdini_mcp.tools._common import apply_response_cap

        # Create response with multibyte characters
        data = {
            "status": "success",
            "items": [{"name": f"Node世界🌍{i}", "data": "测试数据" * 100} for i in range(100)],
        }

        result = apply_response_cap(data, max_bytes=2000)

        # Must serialize without errors
        result_json = json.dumps(result, ensure_ascii=False)
        result_bytes = result_json.encode("utf-8")

        # Must be under cap
        assert len(result_bytes) <= 2000

        # Must parse back (no broken multibyte sequences)
        reparsed = json.loads(result_json)
        assert reparsed["_truncated"] is True

    def test_mixed_ascii_multibyte_truncation(self):
        """Mixed ASCII and multibyte content truncates correctly."""
        import json

        from houdini_mcp.tools._common import apply_response_cap

        data = {
            "status": "success",
            "english": "Hello World" * 50,
            "chinese": "你好世界" * 50,
            "japanese": "こんにちは世界" * 50,
            "emoji": "🌍🌎🌏" * 50,
            "mixed": "Hello世界🌍" * 50,
        }

        for cap in [500, 1000, 2000]:
            result = apply_response_cap(data, max_bytes=cap)
            result_json = json.dumps(result, ensure_ascii=False)
            result_bytes = result_json.encode("utf-8")

            # Must be under cap
            assert len(result_bytes) <= cap

            # Must be valid UTF-8
            result_bytes.decode("utf-8")  # Would raise if broken

            # Must parse
            reparsed = json.loads(result_json)
            assert "_truncated" in reparsed or len(result_bytes) < cap

    def test_emoji_at_boundary(self):
        """Emoji (4-byte UTF-8) at truncation boundary doesn't break."""
        import json

        from houdini_mcp.tools._common import apply_response_cap

        # Emoji use 4 bytes in UTF-8
        data = {
            "status": "success",
            "text": "🌍" * 1000,  # 4000 bytes
        }

        result = apply_response_cap(data, max_bytes=500)
        result_json = json.dumps(result, ensure_ascii=False)

        # Must be valid UTF-8
        result_bytes = result_json.encode("utf-8")
        result_bytes.decode("utf-8")  # Would raise if broken

        # Must parse
        reparsed = json.loads(result_json)
        assert reparsed["_truncated"] is True


class TestOversizedResponseRetainsUsefulData:
    """Test that oversized responses retain useful bounded prefix, not just metadata."""

    def test_large_list_preserves_items(self):
        """Oversized list response preserves as many items as possible."""

        from houdini_mcp.tools._common import apply_response_cap

        data = {
            "status": "success",
            "items": [{"id": i, "name": f"item_{i}", "data": "x" * 50} for i in range(1000)],
            "total": 1000,
        }

        result = apply_response_cap(data, max_bytes=5000)

        # Should have truncated
        assert result["_truncated"] is True

        # Should preserve some items (not metadata-only)
        assert "items" in result
        assert len(result["items"]) > 0, "Should preserve useful data, not just metadata"

        # Should have metadata about truncation
        assert "items_truncated" in result
        assert "items_original_count" in result
        assert result["items_original_count"] == 1000

        # Should preserve status and counts
        assert result["status"] == "success"
        assert result["total"] == 1000

    def test_truncation_preserves_essential_fields(self):
        """Truncation always preserves essential metadata fields."""
        from houdini_mcp.tools._common import apply_response_cap

        data = {
            "status": "success",
            "node_path": "/obj/geo1",
            "total": 5000,
            "returned": 100,
            "has_more": True,
            "cursor": 100,
            "items": [{"large": "x" * 1000} for _ in range(100)],
        }

        result = apply_response_cap(data, max_bytes=2000)

        # Essential fields should be preserved
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/geo1"
        assert result["total"] == 5000
        preserved = len(result["items"])
        assert result["returned"] == result["count"] == preserved
        assert result["has_more"] is True
        assert result["cursor"] == result["next_offset"] == preserved

    def test_minimal_response_not_metadata_only(self):
        """Even minimal fallback response includes useful info."""
        from houdini_mcp.tools._common import apply_response_cap

        # Create extremely large response that won't fit even truncated
        data = {
            "status": "success",
            "node_path": "/obj/geo1",
            "items": [{"nested": {"deep": {"data": "x" * 10000}}} for _ in range(100)],
        }

        result = apply_response_cap(data, max_bytes=300)

        # Should have minimal info
        assert result["_truncated"] is True
        assert result["status"] == "success"
        assert "message" in result or "node_path" in result
