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
        params: Optional[Dict[str, Any]] = None,
    ):
        self._path = path
        self._name = name
        self._node_type = node_type
        self._type_description = type_description
        self._children: List["MockHouNode"] = children if children is not None else []
        self._params: Dict[str, Any] = (
            params if params is not None else {"tx": 0.0, "ty": 0.0, "tz": 0.0}
        )
        self._inputs: List[Any] = []
        self._outputs: List[Any] = []
        self._display_flag = True
        self._render_flag = True
        self._bypass = False
        self._destroyed = False
        # Cook state tracking
        self._cook_state = "Cooked"  # Cooked, CookFailed, Dirty, Uncooked
        self._errors: List[str] = []
        self._warnings: List[str] = []
        self._last_cook_time: Optional[float] = None
        # Geometry
        self._geometry: Optional["MockGeometry"] = None
        # Parent node (set during createNode)
        self._parent: Optional["MockHouNode"] = None
        # Network position
        self._position: tuple = (0.0, 0.0)
        # Node color
        self._color: Optional["MockColor"] = None
        # Network boxes
        self._network_boxes: List["MockNetworkBox"] = []
        self._network_box_counter = 0

    def path(self) -> str:
        return self._path

    def name(self) -> str:
        return self._name

    def type(self) -> MagicMock:
        mock_type = MagicMock()
        mock_type.name.return_value = self._node_type
        mock_type.description.return_value = self._type_description

        # Add category mock
        mock_category = MagicMock()
        # Determine category from node type
        # SOPs: grid, sphere, box, noise, mountain, merge, etc.
        # Objects: geo, cam, light, null (at /obj level)
        if self._node_type in [
            "grid",
            "sphere",
            "box",
            "noise",
            "mountain",
            "merge",
            "transform",
            "subnet",
        ]:
            mock_category.name.return_value = "Sop"
        elif self._node_type in ["geo", "cam", "light", "null"]:
            mock_category.name.return_value = "Object"
        elif self._node_type in ["dopnet", "pyrosolver"]:
            mock_category.name.return_value = "Dop"
        else:
            mock_category.name.return_value = "Sop"  # Default to Sop

        mock_type.category.return_value = mock_category
        return mock_type

    def children(self) -> List["MockHouNode"]:
        return self._children

    def inputs(self) -> List[Any]:
        return self._inputs

    def outputs(self) -> List[Any]:
        return self._outputs

    def inputConnectors(self) -> List[tuple]:
        """Return list of (input_index, output_index) tuples for each input."""
        connectors = []
        for idx, inp in enumerate(self._inputs):
            if inp is not None:
                # Default to output index 0
                connectors.append((idx, 0))
            else:
                connectors.append((idx, -1))
        return connectors

    def parms(self) -> List[MagicMock]:
        mock_parms = []
        for name in self._params.keys():
            parm = self.parm(name)
            if parm is not None:
                mock_parms.append(parm)
        return mock_parms

    def parm(self, name: str) -> Optional[MagicMock]:
        if name not in self._params:
            return None

        # Return stable mock objects so tests can patch attributes.
        if not hasattr(self, "_parm_objects"):
            self._parm_objects = {}

        if name in self._parm_objects:
            # Keep current value in sync.
            self._parm_objects[name].eval.return_value = self._params[name]
            return self._parm_objects[name]

        mock_parm = MagicMock()
        mock_parm.name.return_value = name
        mock_parm.eval.return_value = self._params[name]

        def _setter(v: Any, n: str = name) -> None:
            self._params.update({n: v})
            mock_parm.eval.return_value = v

        mock_parm.set = _setter
        self._parm_objects[name] = mock_parm
        return mock_parm

    def parmTuple(self, name: str) -> Optional[MagicMock]:
        if name not in self._params or not isinstance(self._params[name], (list, tuple)):
            return None

        if not hasattr(self, "_parm_tuple_objects"):
            self._parm_tuple_objects = {}

        if name in self._parm_tuple_objects:
            self._parm_tuple_objects[name].eval.return_value = tuple(self._params[name])
            return self._parm_tuple_objects[name]

        mock_parm = MagicMock()
        mock_parm.eval.return_value = tuple(self._params[name])

        def _setter(v: Any, n: str = name) -> None:
            self._params.update({n: v})
            mock_parm.eval.return_value = tuple(v) if isinstance(v, (list, tuple)) else v

        mock_parm.set = _setter
        self._parm_tuple_objects[name] = mock_parm
        return mock_parm

    def createNode(self, node_type: str, name: Optional[str] = None) -> "MockHouNode":
        new_name = name if name else f"{node_type}1"
        new_path = f"{self._path}/{new_name}"

        # Create node with type-specific default parameters
        params: Dict[str, Any] = {"tx": 0.0, "ty": 0.0, "tz": 0.0}

        # Add type-specific parameters
        if node_type == "material":
            params.update(
                {
                    "shop_materialpath1": "",
                    "group1": "",
                }
            )
        elif node_type == "principledshader":
            params.update(
                {
                    "basecolor": [1.0, 1.0, 1.0],
                    "rough": 0.3,
                    "metallic": 0.0,
                }
            )

        new_node = MockHouNode(path=new_path, name=new_name, node_type=node_type, params=params)
        new_node._parent = self  # Set parent reference
        self._children.append(new_node)
        return new_node

    def destroy(self) -> None:
        self._destroyed = True

    def isDisplayFlagSet(self) -> bool:
        return self._display_flag

    def isRenderFlagSet(self) -> bool:
        return self._render_flag

    def setDisplayFlag(self, value: bool) -> None:
        self._display_flag = value

    def setRenderFlag(self, value: bool) -> None:
        self._render_flag = value

    def setBypass(self, value: bool) -> None:
        self._bypass = value

    def isBypassed(self) -> bool:
        return self._bypass

    def setInput(
        self, input_index: int, source_node: Optional["MockHouNode"], output_index: int = 0
    ) -> None:
        """Set input connection."""
        # Extend inputs list if needed
        while len(self._inputs) <= input_index:
            self._inputs.append(None)

        # Remove old connection if exists
        old_source = self._inputs[input_index]
        if old_source is not None and self in old_source._outputs:
            old_source._outputs.remove(self)

        # Set new connection
        self._inputs[input_index] = source_node

        # Update source node's outputs
        if source_node is not None:
            if self not in source_node._outputs:
                source_node._outputs.append(self)

    def cookState(self) -> MagicMock:
        """Return cook state enum."""
        mock_state = MagicMock()
        mock_state.name.return_value = self._cook_state
        return mock_state

    def errors(self) -> List[str]:
        """Return list of error messages."""
        return self._errors.copy()

    def warnings(self) -> List[str]:
        """Return list of warning messages."""
        return self._warnings.copy()

    def cook(self, force: bool = False) -> None:
        """Simulate cooking the node."""
        import time

        self._last_cook_time = time.time()
        # If there are errors, state becomes CookFailed
        if self._errors:
            self._cook_state = "CookFailed"
        else:
            self._cook_state = "Cooked"

    def isCook(self) -> bool:
        """Check if node is currently cooking."""
        return False  # For mock, assume never actively cooking

    def geometry(self) -> Optional["MockGeometry"]:
        """Return geometry object if this is a SOP node."""
        return self._geometry

    def setGeometry(self, geo: "MockGeometry") -> None:
        """Helper to set geometry on this node."""
        self._geometry = geo

    def allSubChildren(self) -> List["MockHouNode"]:
        """Return all descendant nodes recursively."""
        all_descendants: List["MockHouNode"] = []

        def collect(node: "MockHouNode") -> None:
            for child in node._children:
                all_descendants.append(child)
                collect(child)

        collect(self)
        return all_descendants

    def parent(self) -> Optional["MockHouNode"]:
        """Return the parent node."""
        return self._parent

    def displayNode(self) -> Optional["MockHouNode"]:
        """Return the display node (node with display flag set, or last child)."""
        # Find child with display flag set
        for child in self._children:
            if child._display_flag:
                return child
        # Fallback to last child if any
        if self._children:
            return self._children[-1]
        return None

    def layoutChildren(
        self, horizontal_spacing: float = 2.0, vertical_spacing: float = 1.0, *args, **kwargs
    ) -> None:
        """Layout child nodes. No-op for mock."""
        pass

    def setPosition(self, position: "MockVector2") -> None:
        """Set the node's position in the network editor."""
        self._position = (position[0], position[1])

    def position(self) -> tuple:
        """Get the node's position in the network editor."""
        return self._position

    def setColor(self, color: "MockColor") -> None:
        """Set the node's display color."""
        self._color = color

    def color(self) -> Optional["MockColor"]:
        """Get the node's display color."""
        return self._color

    def createNetworkBox(self, name: Optional[str] = None) -> "MockNetworkBox":
        """Create a network box in this node's network."""
        self._network_box_counter += 1
        box_name = name if name else f"netbox{self._network_box_counter}"
        netbox = MockNetworkBox(box_name)
        self._network_boxes.append(netbox)
        return netbox

    def setFirstInput(self, node: Optional["MockHouNode"]) -> None:
        """Set the first input connection (convenience method)."""
        self.setInput(0, node)


class MockRpycConnection:
    """Mock rpyc connection object."""

    def __init__(self, hou_module: "MockHouModule"):
        self.modules = MagicMock()
        self.modules.hou = hou_module
        self._closed = False

    def close(self) -> None:
        self._closed = True


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

        # Mock cookState enum
        self.cookState = MagicMock()
        self.cookState.Cooked = MagicMock()
        self.cookState.Cooked.name.return_value = "Cooked"
        self.cookState.CookFailed = MagicMock()
        self.cookState.CookFailed.name.return_value = "CookFailed"
        self.cookState.Dirty = MagicMock()
        self.cookState.Dirty.name.return_value = "Dirty"
        self.cookState.Uncooked = MagicMock()
        self.cookState.Uncooked.name.return_value = "Uncooked"

        # Houdini types
        self.Color = MockColor
        self.Vector2 = MockVector2

    def applicationVersionString(self) -> str:
        return self._version

    def applicationVersion(self) -> tuple:
        return self._version_tuple

    def node(self, path: str) -> Optional[MockHouNode]:
        return self._nodes.get(path)

    def nodeTypeCategories(self) -> Dict[str, Any]:
        """Return mock node type categories with sufficient types for testing limits."""
        # Object-level node types
        object_types = {
            "geo": MagicMock(),
            "null": MagicMock(),
            "cam": MagicMock(),
            "light": MagicMock(),
            "dopnet": MagicMock(),
            "ropnet": MagicMock(),
            "chopnet": MagicMock(),
            "subnet": MagicMock(),
            "instance": MagicMock(),
            "fetch": MagicMock(),
        }
        for name, mock_type in object_types.items():
            mock_type.description.return_value = f"{name.capitalize()} node"

        object_category = MagicMock()
        object_category.nodeTypes.return_value = object_types

        # SOP-level node types (many more to test limits)
        sop_type_names = [
            "sphere",
            "box",
            "grid",
            "tube",
            "torus",
            "circle",
            "line",
            "curve",
            "noise",
            "mountain",
            "attribnoise",
            "cloudnoise",
            "heightfield_noise",
            "transform",
            "xform",
            "blast",
            "delete",
            "dissolve",
            "fuse",
            "clean",
            "merge",
            "switch",
            "copy",
            "scatter",
            "copytopoints",
            "foreach",
            "vex",
            "wrangle",
            "attribwrangle",
            "pointwrangle",
            "volumewrangle",
            "vdb",
            "vdbfromparticles",
            "vdbsmooth",
            "vdbreshape",
            "vdbcombine",
            "file",
            "alembic",
            "filecache",
            "cache",
            "stash",
            "group",
            "groupcreate",
            "groupcombine",
            "groupexpression",
            "subdivide",
            "polyextrude",
            "polybevel",
            "polyreduce",
            "polyfill",
            "null",
            "output",
            "object_merge",
            "timeshift",
            "trail",
            # Add more to exceed 100 total
            *[f"custom_sop_{i}" for i in range(60)],
        ]

        sop_types = {}
        for name in sop_type_names:
            mock_type = MagicMock()
            mock_type.description.return_value = f"{name.replace('_', ' ').title()} SOP"
            sop_types[name] = mock_type

        sop_category = MagicMock()
        sop_category.nodeTypes.return_value = sop_types

        return {"Object": object_category, "Sop": sop_category}

    def add_node(self, node: MockHouNode) -> None:
        """Helper to add a node to the mock."""
        self._nodes[node.path()] = node

    def remove_node(self, path: str) -> None:
        """Helper to remove a node from the mock."""
        if path in self._nodes:
            del self._nodes[path]


@pytest.fixture
def mock_hou() -> MockHouModule:
    """Create a mock hou module."""
    return MockHouModule()


@pytest.fixture
def mock_connection(mock_hou: MockHouModule) -> Generator[MockHouModule, None, None]:
    """Patch the connection module to use mock hou."""
    mock_conn = MockRpycConnection(mock_hou)
    with (
        patch("houdini_mcp.connection._hou", mock_hou),
        patch("houdini_mcp.connection._connection", mock_conn),
    ):
        yield mock_hou


@pytest.fixture
def mock_rpyc(mock_hou: MockHouModule) -> Generator[MockHouModule, None, None]:
    """Patch rpyc.classic.connect to return mock connection."""
    mock_conn = MockRpycConnection(mock_hou)

    with patch("houdini_mcp.connection.rpyc") as mock_rpyc_module:
        mock_rpyc_module.classic.connect.return_value = mock_conn
        yield mock_hou


@pytest.fixture
def reset_connection_state() -> Generator[None, None, None]:
    """Reset global connection state before and after test."""
    import houdini_mcp.connection as conn_module

    # Reset before
    conn_module._connection = None
    conn_module._hou = None
    yield
    # Reset after
    conn_module._connection = None
    conn_module._hou = None


@pytest.fixture
def mock_rpyc_with_reset(
    mock_hou: MockHouModule, reset_connection_state: None
) -> Generator[MockHouModule, None, None]:
    """Patch rpyc and reset connection state."""
    mock_conn = MockRpycConnection(mock_hou)

    with patch("houdini_mcp.connection.rpyc") as mock_rpyc_module:
        mock_rpyc_module.classic.connect.return_value = mock_conn
        yield mock_hou


class MockColor:
    """Mock hou.Color object."""

    def __init__(self, rgb: tuple = (0.0, 0.0, 0.0)):
        if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
            self._rgb = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
        else:
            self._rgb = (0.0, 0.0, 0.0)

    def rgb(self) -> tuple:
        return self._rgb

    def __repr__(self) -> str:
        return f"<MockColor {self._rgb}>"


class MockVector2:
    """Mock hou.Vector2 object."""

    def __init__(self, x: float = 0.0, y: float = 0.0):
        self._x = float(x)
        self._y = float(y)

    def __getitem__(self, index: int) -> float:
        if index == 0:
            return self._x
        elif index == 1:
            return self._y
        raise IndexError(f"Index {index} out of range for Vector2")

    def __repr__(self) -> str:
        return f"<MockVector2 ({self._x}, {self._y})>"


class MockNetworkBox:
    """Mock hou.NetworkBox object."""

    def __init__(self, name: str = "netbox1"):
        self._name = name
        self._label = ""
        self._color: Optional[MockColor] = None
        self._nodes: List["MockHouNode"] = []

    def name(self) -> str:
        return self._name

    def setComment(self, label: str) -> None:
        self._label = label

    def setColor(self, color: MockColor) -> None:
        self._color = color

    def addNode(self, node: "MockHouNode") -> None:
        if node not in self._nodes:
            self._nodes.append(node)

    def fitAroundContents(self) -> None:
        """Resize to fit contained nodes."""
        pass  # No-op for mock


class MockGeoPoint:
    """Mock geometry point."""

    def __init__(self, index: int, position: tuple, attribs: Optional[Dict[str, Any]] = None):
        self._index = index
        self._position = list(position)
        self._attribs = attribs if attribs is not None else {}

    def number(self) -> int:
        return self._index

    def position(self) -> tuple:
        return tuple(self._position)

    def attribValue(self, name: str) -> Any:
        """Get attribute value for this point."""
        if name == "P":
            return self._position
        return self._attribs.get(name)


class MockGeoPrim:
    """Mock geometry primitive."""

    def __init__(self, index: int, num_vertices: int = 4, attribs: Optional[Dict[str, Any]] = None):
        self._index = index
        self._num_vertices = num_vertices
        self._attribs = attribs if attribs is not None else {}

    def number(self) -> int:
        return self._index

    def numVertices(self) -> int:
        return self._num_vertices

    def attribValue(self, name: str) -> Any:
        return self._attribs.get(name)


class MockGeoAttrib:
    """Mock geometry attribute."""

    def __init__(self, name: str, data_type: str, size: int):
        self._name = name
        self._data_type = data_type
        self._size = size

    def name(self) -> str:
        return self._name

    def dataType(self) -> Any:
        """Return data type enum."""
        mock_data_type = MagicMock()
        mock_data_type.name.return_value = self._data_type
        return mock_data_type

    def size(self) -> int:
        return self._size


class MockGeoGroup:
    """Mock geometry group."""

    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


class MockBoundingBox:
    """Mock hou.BoundingBox."""

    def __init__(self, min_vec: tuple, max_vec: tuple):
        self._min = list(min_vec)
        self._max = list(max_vec)

    def minvec(self) -> tuple:
        return tuple(self._min)

    def maxvec(self) -> tuple:
        return tuple(self._max)

    def sizevec(self) -> tuple:
        return tuple(self._max[i] - self._min[i] for i in range(3))

    def center(self) -> tuple:
        return tuple((self._max[i] + self._min[i]) / 2.0 for i in range(3))


class MockGeometry:
    """Mock hou.Geometry object."""

    def __init__(self):
        self._points: List[MockGeoPoint] = []
        self._prims: List[MockGeoPrim] = []
        self._point_attribs: List[MockGeoAttrib] = []
        self._prim_attribs: List[MockGeoAttrib] = []
        self._vertex_attribs: List[MockGeoAttrib] = []
        self._detail_attribs: List[MockGeoAttrib] = []
        self._point_groups: List[MockGeoGroup] = []
        self._prim_groups: List[MockGeoGroup] = []
        self._bbox: Optional[MockBoundingBox] = None

    def points(self) -> List[MockGeoPoint]:
        """Return list of points."""
        return self._points

    def iterPoints(self):
        """Iterate over points."""
        return iter(self._points)

    def prims(self) -> List[MockGeoPrim]:
        """Return list of primitives."""
        return self._prims

    def iterPrims(self):
        """Iterate over primitives."""
        return iter(self._prims)

    def pointAttribs(self) -> List[MockGeoAttrib]:
        return self._point_attribs

    def primAttribs(self) -> List[MockGeoAttrib]:
        return self._prim_attribs

    def vertexAttribs(self) -> List[MockGeoAttrib]:
        return self._vertex_attribs

    def globalAttribs(self) -> List[MockGeoAttrib]:
        return self._detail_attribs

    def pointGroups(self) -> List[MockGeoGroup]:
        return self._point_groups

    def primGroups(self) -> List[MockGeoGroup]:
        return self._prim_groups

    def boundingBox(self) -> Optional[MockBoundingBox]:
        return self._bbox

    def addPoint(self, position: tuple, attribs: Optional[Dict[str, Any]] = None) -> MockGeoPoint:
        """Helper to add a point."""
        pt = MockGeoPoint(len(self._points), position, attribs)
        self._points.append(pt)
        return pt

    def addPrim(
        self, num_vertices: int = 4, attribs: Optional[Dict[str, Any]] = None
    ) -> MockGeoPrim:
        """Helper to add a primitive."""
        prim = MockGeoPrim(len(self._prims), num_vertices, attribs)
        self._prims.append(prim)
        return prim

    def addPointAttrib(self, name: str, data_type: str, size: int) -> MockGeoAttrib:
        """Helper to add point attribute."""
        attrib = MockGeoAttrib(name, data_type, size)
        self._point_attribs.append(attrib)
        return attrib

    def addPrimAttrib(self, name: str, data_type: str, size: int) -> MockGeoAttrib:
        """Helper to add primitive attribute."""
        attrib = MockGeoAttrib(name, data_type, size)
        self._prim_attribs.append(attrib)
        return attrib

    def addVertexAttrib(self, name: str, data_type: str, size: int) -> MockGeoAttrib:
        """Helper to add vertex attribute."""
        attrib = MockGeoAttrib(name, data_type, size)
        self._vertex_attribs.append(attrib)
        return attrib

    def addDetailAttrib(self, name: str, data_type: str, size: int) -> MockGeoAttrib:
        """Helper to add detail attribute."""
        attrib = MockGeoAttrib(name, data_type, size)
        self._detail_attribs.append(attrib)
        return attrib

    def addPointGroup(self, name: str) -> MockGeoGroup:
        """Helper to add point group."""
        group = MockGeoGroup(name)
        self._point_groups.append(group)
        return group

    def addPrimGroup(self, name: str) -> MockGeoGroup:
        """Helper to add primitive group."""
        group = MockGeoGroup(name)
        self._prim_groups.append(group)
        return group

    def setBoundingBox(self, min_vec: tuple, max_vec: tuple) -> None:
        """Helper to set bounding box."""
        self._bbox = MockBoundingBox(min_vec, max_vec)
