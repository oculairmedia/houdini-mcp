"""Pytest configuration and fixtures for Houdini MCP tests."""

import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict, List, Optional, Generator


class MockHouNode:
    """Mock Houdini node object."""
    
    def __init__(
        self,
        path: str = "/obj/geo1",
        name: str = "geo1",
        node_type: str = "geo",
        type_description: str = "Geometry",
        children: Optional[List["MockHouNode"]] = None,
        params: Optional[Dict[str, Any]] = None
    ):
        self._path = path
        self._name = name
        self._node_type = node_type
        self._type_description = type_description
        self._children: List["MockHouNode"] = children if children is not None else []
        self._params: Dict[str, Any] = params if params is not None else {"tx": 0.0, "ty": 0.0, "tz": 0.0}
        self._inputs: List[Any] = []
        self._outputs: List[Any] = []
        self._display_flag = True
        self._render_flag = True
    
    def path(self) -> str:
        return self._path
    
    def name(self) -> str:
        return self._name
    
    def type(self) -> MagicMock:
        mock_type = MagicMock()
        mock_type.name.return_value = self._node_type
        mock_type.description.return_value = self._type_description
        return mock_type
    
    def children(self) -> List["MockHouNode"]:
        return self._children
    
    def inputs(self) -> List[Any]:
        return self._inputs
    
    def outputs(self) -> List[Any]:
        return self._outputs
    
    def parms(self) -> List[MagicMock]:
        mock_parms = []
        for name, value in self._params.items():
            mock_parm = MagicMock()
            mock_parm.name.return_value = name
            mock_parm.eval.return_value = value
            mock_parms.append(mock_parm)
        return mock_parms
    
    def parm(self, name: str) -> Optional[MagicMock]:
        if name in self._params:
            mock_parm = MagicMock()
            mock_parm.name.return_value = name
            mock_parm.eval.return_value = self._params[name]
            mock_parm.set = lambda v, n=name: self._params.update({n: v})
            return mock_parm
        return None
    
    def parmTuple(self, name: str) -> Optional[MagicMock]:
        if name in self._params and isinstance(self._params[name], (list, tuple)):
            mock_parm = MagicMock()
            mock_parm.set = lambda v, n=name: self._params.update({n: v})
            return mock_parm
        return None
    
    def createNode(self, node_type: str, name: Optional[str] = None) -> "MockHouNode":
        new_name = name if name else f"{node_type}1"
        new_path = f"{self._path}/{new_name}"
        new_node = MockHouNode(path=new_path, name=new_name, node_type=node_type)
        self._children.append(new_node)
        return new_node
    
    def destroy(self) -> None:
        pass
    
    def isDisplayFlagSet(self) -> bool:
        return self._display_flag
    
    def isRenderFlagSet(self) -> bool:
        return self._render_flag
    
    def setDisplayFlag(self, value: bool) -> None:
        self._display_flag = value
    
    def setRenderFlag(self, value: bool) -> None:
        self._render_flag = value


class MockHouModule:
    """Mock hou module for testing."""
    
    def __init__(self) -> None:
        self._nodes: Dict[str, MockHouNode] = {}
        self._hip_file = "/path/to/test.hip"
        self._version = "20.5.123"
        self._version_tuple = (20, 5, 123)
        
        # Create default /obj node
        obj_node = MockHouNode(path="/obj", name="obj", node_type="obj")
        self._nodes["/obj"] = obj_node
        
        # Mock hipFile
        self.hipFile = MagicMock()
        self.hipFile.path.return_value = self._hip_file
        self.hipFile.save = MagicMock()
        self.hipFile.load = MagicMock()
        self.hipFile.clear = MagicMock()
    
    def applicationVersionString(self) -> str:
        return self._version
    
    def applicationVersion(self) -> tuple:
        return self._version_tuple
    
    def node(self, path: str) -> Optional[MockHouNode]:
        return self._nodes.get(path)
    
    def nodeTypeCategories(self) -> Dict[str, Any]:
        """Return mock node type categories."""
        mock_category = MagicMock()
        mock_types = {
            "geo": MagicMock(),
            "null": MagicMock(),
            "cam": MagicMock()
        }
        for name, mock_type in mock_types.items():
            mock_type.description.return_value = f"{name.capitalize()} node"
        mock_category.nodeTypes.return_value = mock_types
        return {"Object": mock_category}
    
    def add_node(self, node: MockHouNode) -> None:
        """Helper to add a node to the mock."""
        self._nodes[node.path()] = node


@pytest.fixture
def mock_hou() -> MockHouModule:
    """Create a mock hou module."""
    return MockHouModule()


@pytest.fixture
def mock_connection(mock_hou: MockHouModule) -> Generator[MockHouModule, None, None]:
    """Patch the connection module to use mock hou."""
    with patch('houdini_mcp.connection._hou', mock_hou), \
         patch('houdini_mcp.connection._connection', MagicMock()):
        yield mock_hou


@pytest.fixture
def mock_hrpyc(mock_hou: MockHouModule) -> Generator[MockHouModule, None, None]:
    """Patch hrpyc.import_remote_module to return mock connection and hou."""
    mock_conn = MagicMock()
    mock_hrpyc_module = MagicMock()
    mock_hrpyc_module.import_remote_module = MagicMock(return_value=(mock_conn, mock_hou))
    
    with patch.dict('sys.modules', {'hrpyc': mock_hrpyc_module}):
        yield mock_hou
