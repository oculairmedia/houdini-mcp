"""Integration test for get_parameter_schema demonstrating real-world usage."""

import pytest
from unittest.mock import MagicMock, patch


def test_get_parameter_schema_sphere_real_world():
    """
    Integration test demonstrating get_parameter_schema with a sphere node.
    
    This simulates a real-world scenario where an agent wants to understand
    what parameters are available on a sphere node before modifying them.
    """
    from houdini_mcp.tools import get_parameter_schema
    
    # Setup comprehensive mock hou module
    mock_hou = MagicMock()
    
    # Setup parmTemplateType enum (matches real Houdini)
    mock_hou.parmTemplateType.Float = "Float"
    mock_hou.parmTemplateType.Int = "Int"
    mock_hou.parmTemplateType.Menu = "Menu"
    mock_hou.parmTemplateType.Toggle = "Toggle"
    mock_hou.parmTemplateType.Folder = "Folder"
    mock_hou.parmTemplateType.Separator = "Separator"
    
    # Create mock sphere node
    mock_node = MagicMock()
    mock_node.path.return_value = "/obj/geo1/sphere1"
    
    # Define sphere parameter templates (typical sphere node parameters)
    sphere_templates = []
    
    # 1. Radius X (float)
    radx_template = MagicMock()
    radx_template.name.return_value = "radx"
    radx_template.label.return_value = "Radius"
    radx_template.type.return_value = mock_hou.parmTemplateType.Float
    radx_template.numComponents.return_value = 1
    radx_template.defaultValue.return_value = [1.0]
    radx_template.minValue.return_value = 0.0
    radx_template.maxValue.return_value = None
    sphere_templates.append(radx_template)
    
    # 2. Type (menu)
    type_template = MagicMock()
    type_template.name.return_value = "type"
    type_template.label.return_value = "Primitive Type"
    type_template.type.return_value = mock_hou.parmTemplateType.Menu
    type_template.numComponents.return_value = 1
    type_template.defaultValue.return_value = [0]
    type_template.menuLabels.return_value = ["Polygon", "Mesh", "Polygon Mesh", "NURBS"]
    type_template.menuItems.return_value = ["poly", "mesh", "polymesh", "nurbs"]
    sphere_templates.append(type_template)
    
    # 3. Frequency (int)
    freq_template = MagicMock()
    freq_template.name.return_value = "freq"
    freq_template.label.return_value = "Frequency"
    freq_template.type.return_value = mock_hou.parmTemplateType.Int
    freq_template.numComponents.return_value = 1
    freq_template.defaultValue.return_value = [2]
    freq_template.minValue.return_value = 2
    freq_template.maxValue.return_value = 50
    sphere_templates.append(freq_template)
    
    # 4. Translate (vector - 3 components)
    t_template = MagicMock()
    t_template.name.return_value = "t"
    t_template.label.return_value = "Translate"
    t_template.type.return_value = mock_hou.parmTemplateType.Float
    t_template.numComponents.return_value = 3
    t_template.defaultValue.return_value = [0.0, 0.0, 0.0]
    t_template.minValue.return_value = None
    t_template.maxValue.return_value = None
    sphere_templates.append(t_template)
    
    # Setup node to return these templates
    mock_node.parmTemplates.return_value = sphere_templates
    
    # Setup individual parms with current values
    parm_current_values = {
        "radx": 2.5,
        "type": 0,
        "freq": 5,
        "t": [1.0, 2.0, 3.0]
    }
    
    def mock_parm_getter(name):
        """Return mock parm with template and value."""
        if name not in parm_current_values or isinstance(parm_current_values[name], list):
            return None
        
        mock_parm = MagicMock()
        # Find the template for this parm
        template = next((t for t in sphere_templates if t.name() == name), None)
        mock_parm.parmTemplate.return_value = template
        mock_parm.eval.return_value = parm_current_values[name]
        return mock_parm
    
    def mock_parm_tuple_getter(name):
        """Return mock parm tuple for vector parameters."""
        if name not in parm_current_values or not isinstance(parm_current_values[name], list):
            return None
        
        mock_tuple = MagicMock()
        template = next((t for t in sphere_templates if t.name() == name), None)
        mock_tuple.parmTemplate.return_value = template
        mock_tuple.eval.return_value = tuple(parm_current_values[name])
        return mock_tuple
    
    mock_node.parm.side_effect = mock_parm_getter
    mock_node.parmTuple.side_effect = mock_parm_tuple_getter
    
    mock_hou.node.return_value = mock_node
    
    # Execute test
    with patch('houdini_mcp.connection._hou', mock_hou), \
         patch('houdini_mcp.connection._connection', MagicMock()):
        result = get_parameter_schema("/obj/geo1/sphere1")
    
    # Assertions
    assert result["status"] == "success"
    assert result["node_path"] == "/obj/geo1/sphere1"
    assert result["count"] == 4
    assert len(result["parameters"]) == 4
    
    # Verify each parameter
    params_by_name = {p["name"]: p for p in result["parameters"]}
    
    # 1. Check radx (float)
    assert "radx" in params_by_name
    radx = params_by_name["radx"]
    assert radx["label"] == "Radius"
    assert radx["type"] == "float"
    assert radx["default"] == 1.0
    assert radx["current_value"] == 2.5
    assert radx["min"] == 0.0
    assert radx["max"] is None
    assert radx["is_animatable"] is True
    
    # 2. Check type (menu)
    assert "type" in params_by_name
    ptype = params_by_name["type"]
    assert ptype["label"] == "Primitive Type"
    assert ptype["type"] == "menu"
    assert ptype["default"] == 0
    assert ptype["current_value"] == 0
    assert ptype["is_animatable"] is False
    assert len(ptype["menu_items"]) == 4
    assert ptype["menu_items"][0] == {"label": "Polygon", "value": "poly"}
    assert ptype["menu_items"][1] == {"label": "Mesh", "value": "mesh"}
    
    # 3. Check freq (int)
    assert "freq" in params_by_name
    freq = params_by_name["freq"]
    assert freq["label"] == "Frequency"
    assert freq["type"] == "int"
    assert freq["default"] == 2
    assert freq["current_value"] == 5
    assert freq["min"] == 2
    assert freq["max"] == 50
    assert freq["is_animatable"] is True
    
    # 4. Check t (vector)
    assert "t" in params_by_name
    t = params_by_name["t"]
    assert t["label"] == "Translate"
    assert t["type"] == "vector"
    assert t["tuple_size"] == 3
    assert t["default"] == [0.0, 0.0, 0.0]
    assert t["current_value"] == [1.0, 2.0, 3.0]
    assert t["is_animatable"] is True
    
    print("✓ Integration test passed!")
    print(f"✓ Retrieved schema for {result['count']} parameters")
    print(f"✓ Validated float, int, menu, and vector parameter types")


def test_get_parameter_schema_specific_parameter():
    """Test getting schema for a specific parameter only."""
    from houdini_mcp.tools import get_parameter_schema
    
    mock_hou = MagicMock()
    mock_hou.parmTemplateType.Float = "Float"
    
    mock_node = MagicMock()
    mock_node.path.return_value = "/obj/geo1/sphere1"
    
    # Create template for radx
    radx_template = MagicMock()
    radx_template.name.return_value = "radx"
    radx_template.label.return_value = "Radius X"
    radx_template.type.return_value = mock_hou.parmTemplateType.Float
    radx_template.numComponents.return_value = 1
    radx_template.defaultValue.return_value = [1.0]
    radx_template.minValue.return_value = 0.0
    radx_template.maxValue.return_value = None
    
    # Mock parm to return our template
    mock_parm = MagicMock()
    mock_parm.parmTemplate.return_value = radx_template
    mock_parm.eval.return_value = 3.0
    
    mock_node.parm.return_value = mock_parm
    mock_hou.node.return_value = mock_node
    
    with patch('houdini_mcp.connection._hou', mock_hou), \
         patch('houdini_mcp.connection._connection', MagicMock()):
        result = get_parameter_schema("/obj/geo1/sphere1", parm_name="radx")
    
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["parameters"][0]["name"] == "radx"
    assert result["parameters"][0]["current_value"] == 3.0
    
    print("✓ Specific parameter test passed!")


if __name__ == "__main__":
    test_get_parameter_schema_sphere_real_world()
    test_get_parameter_schema_specific_parameter()
    print("\n✅ All integration tests passed!")
