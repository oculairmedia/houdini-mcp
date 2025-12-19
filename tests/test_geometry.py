"""Tests for geometry summary tool (HDMCP-9)."""

import pytest
from unittest.mock import MagicMock, patch

from tests.conftest import MockHouNode, MockGeometry


class TestGetGeoSummary:
    """Tests for the get_geo_summary function."""
    
    def test_get_geo_summary_basic_sphere(self, mock_connection):
        """Test getting geometry summary for a basic sphere."""
        from houdini_mcp.tools import get_geo_summary
        
        # Create a mock sphere geometry
        geo = MockGeometry()
        geo.setBoundingBox((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
        
        # Add some points
        geo.addPoint((0.0, 1.0, 0.0), {"N": [0.0, 1.0, 0.0]})
        geo.addPoint((0.5, 0.866, 0.0), {"N": [0.5, 0.866, 0.0]})
        geo.addPoint((0.866, 0.5, 0.0), {"N": [0.866, 0.5, 0.0]})
        
        # Add some primitives (4 vertices each)
        geo.addPrim(4)
        geo.addPrim(4)
        
        # Add attributes
        geo.addPointAttrib("P", "Float", 3)
        geo.addPointAttrib("N", "Float", 3)
        geo.addPrimAttrib("material", "String", 1)
        
        # Add groups
        geo.addPointGroup("top")
        geo.addPrimGroup("front")
        
        # Create node and attach geometry
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        sphere.setGeometry(geo)
        sphere._cook_state = "Cooked"
        mock_connection.add_node(sphere)
        
        # Get summary
        result = get_geo_summary("/obj/geo1/sphere1", max_sample_points=2,
                                host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["node_path"] == "/obj/geo1/sphere1"
        assert result["cook_state"] == "cooked"
        assert result["point_count"] == 3
        assert result["primitive_count"] == 2
        assert result["vertex_count"] == 8  # 2 prims * 4 vertices
        
        # Check bounding box
        assert result["bounding_box"] is not None
        assert result["bounding_box"]["min"] == [-1.0, -1.0, -1.0]
        assert result["bounding_box"]["max"] == [1.0, 1.0, 1.0]
        assert result["bounding_box"]["size"] == [2.0, 2.0, 2.0]
        assert result["bounding_box"]["center"] == [0.0, 0.0, 0.0]
        
        # Check attributes
        assert "attributes" in result
        assert len(result["attributes"]["point"]) == 2  # P and N
        assert len(result["attributes"]["primitive"]) == 1  # material
        
        # Verify attribute metadata
        p_attrib = next(a for a in result["attributes"]["point"] if a["name"] == "P")
        assert p_attrib["type"] == "float"
        assert p_attrib["size"] == 3
        
        # Check groups
        assert "groups" in result
        assert "top" in result["groups"]["point"]
        assert "front" in result["groups"]["primitive"]
        
        # Check sample points
        assert "sample_points" in result
        assert len(result["sample_points"]) == 2  # Limited to max_sample_points
        assert result["sample_points"][0]["index"] == 0
        assert result["sample_points"][0]["P"] == [0.0, 1.0, 0.0]
    
    def test_get_geo_summary_empty_geometry(self, mock_connection):
        """Test geometry summary for empty geometry."""
        from houdini_mcp.tools import get_geo_summary
        
        # Create empty geometry
        geo = MockGeometry()
        geo.setBoundingBox((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        grid.setGeometry(geo)
        grid._cook_state = "Cooked"
        mock_connection.add_node(grid)
        
        result = get_geo_summary("/obj/geo1/grid1", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["point_count"] == 0
        assert result["primitive_count"] == 0
        assert result["vertex_count"] == 0
        assert len(result["attributes"]["point"]) == 0
        assert len(result["groups"]["point"]) == 0
    
    def test_get_geo_summary_massive_geometry(self, mock_connection):
        """Test geometry summary with massive geometry (>1M points)."""
        from houdini_mcp.tools import get_geo_summary
        
        # Create large geometry
        geo = MockGeometry()
        geo.setBoundingBox((-100.0, -100.0, -100.0), (100.0, 100.0, 100.0))
        
        # Simulate 1.5M points
        for i in range(1500000):
            geo.addPoint((float(i), 0.0, 0.0))
        
        # Add primitives
        for i in range(100000):
            geo.addPrim(3)
        
        large_geo = MockHouNode(path="/obj/geo1/large1", name="large1", node_type="grid")
        large_geo.setGeometry(geo)
        large_geo._cook_state = "Cooked"
        mock_connection.add_node(large_geo)
        
        result = get_geo_summary("/obj/geo1/large1", max_sample_points=100,
                                host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["point_count"] == 1500000
        assert result["primitive_count"] == 100000
        assert result["vertex_count"] == 300000  # 100k prims * 3 vertices
        
        # Should have warning about massive geometry
        assert "warning" in result
        assert ">1M" in result["warning"]
        
        # Sample points should be limited
        assert len(result["sample_points"]) == 100
    
    def test_get_geo_summary_uncooked_geometry(self, mock_connection):
        """Test geometry summary for uncooked/dirty node."""
        from houdini_mcp.tools import get_geo_summary
        
        # Create geometry
        geo = MockGeometry()
        geo.addPoint((0.0, 0.0, 0.0))
        geo.setBoundingBox((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
        
        noise = MockHouNode(path="/obj/geo1/noise1", name="noise1", node_type="noise")
        noise.setGeometry(geo)
        noise._cook_state = "Dirty"  # Start as dirty
        mock_connection.add_node(noise)
        
        result = get_geo_summary("/obj/geo1/noise1", host="localhost", port=18811)
        
        # Should cook and return cooked state
        assert result["status"] == "success"
        assert result["cook_state"] == "cooked"  # After cook
        assert result["point_count"] == 1
    
    def test_get_geo_summary_no_geometry(self, mock_connection):
        """Test error when node has no geometry."""
        from houdini_mcp.tools import get_geo_summary
        
        # Create node without geometry (e.g., Object level node)
        cam = MockHouNode(path="/obj/cam1", name="cam1", node_type="cam")
        cam._geometry = None  # No geometry
        mock_connection.add_node(cam)
        
        result = get_geo_summary("/obj/cam1", host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "has no geometry" in result["message"]
    
    def test_get_geo_summary_node_not_found(self, mock_connection):
        """Test error when node doesn't exist."""
        from houdini_mcp.tools import get_geo_summary
        
        result = get_geo_summary("/obj/geo1/nonexistent", host="localhost", port=18811)
        
        assert result["status"] == "error"
        assert "Node not found" in result["message"]
    
    def test_get_geo_summary_no_attributes(self, mock_connection):
        """Test geometry summary without attributes."""
        from houdini_mcp.tools import get_geo_summary
        
        # Create simple geometry with no custom attributes
        geo = MockGeometry()
        geo.addPoint((1.0, 2.0, 3.0))
        geo.addPrim(3)
        geo.setBoundingBox((0.0, 0.0, 0.0), (5.0, 5.0, 5.0))
        
        box = MockHouNode(path="/obj/geo1/box1", name="box1", node_type="box")
        box.setGeometry(geo)
        box._cook_state = "Cooked"
        mock_connection.add_node(box)
        
        result = get_geo_summary("/obj/geo1/box1", include_attributes=True,
                                host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["point_count"] == 1
        assert "attributes" in result
        assert len(result["attributes"]["point"]) == 0
        assert len(result["attributes"]["primitive"]) == 0
    
    def test_get_geo_summary_skip_attributes_and_groups(self, mock_connection):
        """Test skipping attributes and groups."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.addPoint((0.0, 0.0, 0.0))
        geo.addPrim(4)
        geo.setBoundingBox((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
        geo.addPointAttrib("N", "Float", 3)
        geo.addPointGroup("mygroup")
        
        sphere = MockHouNode(path="/obj/geo1/sphere1", name="sphere1", node_type="sphere")
        sphere.setGeometry(geo)
        sphere._cook_state = "Cooked"
        mock_connection.add_node(sphere)
        
        result = get_geo_summary("/obj/geo1/sphere1", include_attributes=False,
                                include_groups=False, max_sample_points=0,
                                host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert "attributes" not in result
        assert "groups" not in result
        assert "sample_points" not in result
    
    def test_get_geo_summary_various_attribute_types(self, mock_connection):
        """Test geometry with various attribute types."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.addPoint((1.0, 2.0, 3.0))
        geo.setBoundingBox((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
        
        # Add different attribute types
        geo.addPointAttrib("P", "Float", 3)
        geo.addPointAttrib("N", "Float", 3)
        geo.addPointAttrib("Cd", "Float", 3)
        geo.addPointAttrib("id", "Int", 1)
        geo.addPointAttrib("name", "String", 1)
        geo.addPrimAttrib("shop_materialpath", "String", 1)
        geo.addVertexAttrib("uv", "Float", 3)
        geo.addDetailAttrib("frame", "Int", 1)
        
        transform = MockHouNode(path="/obj/geo1/xform1", name="xform1", node_type="transform")
        transform.setGeometry(geo)
        transform._cook_state = "Cooked"
        mock_connection.add_node(transform)
        
        result = get_geo_summary("/obj/geo1/xform1", host="localhost", port=18811)
        
        assert result["status"] == "success"
        
        # Check point attributes
        assert len(result["attributes"]["point"]) == 5
        p_attr = next(a for a in result["attributes"]["point"] if a["name"] == "P")
        assert p_attr["type"] == "float"
        assert p_attr["size"] == 3
        
        id_attr = next(a for a in result["attributes"]["point"] if a["name"] == "id")
        assert id_attr["type"] == "int"
        assert id_attr["size"] == 1
        
        # Check other attribute classes
        assert len(result["attributes"]["primitive"]) == 1
        assert len(result["attributes"]["vertex"]) == 1
        assert len(result["attributes"]["detail"]) == 1
    
    def test_get_geo_summary_sample_points_with_attributes(self, mock_connection):
        """Test sample points include attribute values."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.setBoundingBox((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
        
        # Add points with attributes
        geo.addPoint((0.0, 1.0, 0.0), {"N": [0.0, 1.0, 0.0], "Cd": [1.0, 0.0, 0.0]})
        geo.addPoint((1.0, 0.0, 0.0), {"N": [1.0, 0.0, 0.0], "Cd": [0.0, 1.0, 0.0]})
        geo.addPoint((0.0, 0.0, 1.0), {"N": [0.0, 0.0, 1.0], "Cd": [0.0, 0.0, 1.0]})
        
        geo.addPointAttrib("P", "Float", 3)
        geo.addPointAttrib("N", "Float", 3)
        geo.addPointAttrib("Cd", "Float", 3)
        
        mountain = MockHouNode(path="/obj/geo1/mountain1", name="mountain1", node_type="mountain")
        mountain.setGeometry(geo)
        mountain._cook_state = "Cooked"
        mock_connection.add_node(mountain)
        
        result = get_geo_summary("/obj/geo1/mountain1", max_sample_points=3,
                                host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert len(result["sample_points"]) == 3
        
        # Check first point has all attributes
        pt0 = result["sample_points"][0]
        assert pt0["index"] == 0
        assert pt0["P"] == [0.0, 1.0, 0.0]
        assert pt0["N"] == [0.0, 1.0, 0.0]
        assert pt0["Cd"] == [1.0, 0.0, 0.0]
        
        # Check second point
        pt1 = result["sample_points"][1]
        assert pt1["index"] == 1
        assert pt1["P"] == [1.0, 0.0, 0.0]
        assert pt1["N"] == [1.0, 0.0, 0.0]
    
    def test_get_geo_summary_max_sample_points_validation(self, mock_connection):
        """Test max_sample_points validation (capped at 10000)."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.addPoint((0.0, 0.0, 0.0))
        geo.setBoundingBox((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        grid.setGeometry(geo)
        grid._cook_state = "Cooked"
        mock_connection.add_node(grid)
        
        # Test negative value -> 0
        result = get_geo_summary("/obj/geo1/grid1", max_sample_points=-10,
                                host="localhost", port=18811)
        assert result["status"] == "success"
        assert "sample_points" not in result  # 0 samples
        
        # Test value > 10000 -> capped at 10000
        # (Can't easily verify the cap in mock, but function logs warning)
    
    def test_get_geo_summary_multiple_groups(self, mock_connection):
        """Test geometry with multiple groups."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.addPoint((0.0, 0.0, 0.0))
        geo.addPoint((1.0, 0.0, 0.0))
        geo.addPrim(3)
        geo.addPrim(3)
        geo.setBoundingBox((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        
        # Add multiple groups
        geo.addPointGroup("top")
        geo.addPointGroup("bottom")
        geo.addPointGroup("selection")
        geo.addPrimGroup("front")
        geo.addPrimGroup("back")
        
        merge = MockHouNode(path="/obj/geo1/merge1", name="merge1", node_type="merge")
        merge.setGeometry(geo)
        merge._cook_state = "Cooked"
        mock_connection.add_node(merge)
        
        result = get_geo_summary("/obj/geo1/merge1", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert len(result["groups"]["point"]) == 3
        assert "top" in result["groups"]["point"]
        assert "bottom" in result["groups"]["point"]
        assert "selection" in result["groups"]["point"]
        assert len(result["groups"]["primitive"]) == 2
        assert "front" in result["groups"]["primitive"]
        assert "back" in result["groups"]["primitive"]
    
    def test_get_geo_summary_no_bounding_box(self, mock_connection):
        """Test geometry with no bounding box."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.addPoint((0.0, 0.0, 0.0))
        # Don't set bounding box (remains None)
        
        grid = MockHouNode(path="/obj/geo1/grid1", name="grid1", node_type="grid")
        grid.setGeometry(geo)
        grid._cook_state = "Cooked"
        mock_connection.add_node(grid)
        
        result = get_geo_summary("/obj/geo1/grid1", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["bounding_box"] is None
    
    def test_get_geo_summary_cook_failed(self, mock_connection):
        """Test geometry summary when cook fails."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.addPoint((0.0, 0.0, 0.0))
        
        bad_node = MockHouNode(path="/obj/geo1/bad1", name="bad1", node_type="noise")
        bad_node.setGeometry(geo)
        bad_node._cook_state = "CookFailed"
        bad_node._errors = ["Missing input"]
        mock_connection.add_node(bad_node)
        
        result = get_geo_summary("/obj/geo1/bad1", host="localhost", port=18811)
        
        # Should still return geometry info despite cook error
        assert result["status"] == "success"
        assert result["cook_state"] == "error"
        assert result["point_count"] == 1
    
    def test_get_geo_summary_vertex_count_calculation(self, mock_connection):
        """Test vertex count calculation with varying primitive types."""
        from houdini_mcp.tools import get_geo_summary
        
        geo = MockGeometry()
        geo.addPoint((0.0, 0.0, 0.0))
        geo.setBoundingBox((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        
        # Add primitives with different vertex counts
        geo.addPrim(3)  # Triangle
        geo.addPrim(4)  # Quad
        geo.addPrim(5)  # Pentagon
        geo.addPrim(6)  # Hexagon
        
        poly = MockHouNode(path="/obj/geo1/poly1", name="poly1", node_type="grid")
        poly.setGeometry(geo)
        poly._cook_state = "Cooked"
        mock_connection.add_node(poly)
        
        result = get_geo_summary("/obj/geo1/poly1", host="localhost", port=18811)
        
        assert result["status"] == "success"
        assert result["primitive_count"] == 4
        assert result["vertex_count"] == 18  # 3 + 4 + 5 + 6
