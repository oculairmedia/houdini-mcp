"""Pane screenshot capture tools using Qt/PySide2 via RPyC.

This module provides tools for capturing screenshots of Houdini pane tabs
using Qt's screen grab functionality. Screenshots are returned as base64-encoded
PNG images.

Available pane types (30 total):
    - NetworkEditor: Node network editor (default)
    - SceneViewer: 3D scene viewer
    - Parm: Parameter editor panel
    - CompositorViewer: Compositor/COP viewer
    - ChannelEditor: Animation channel editor
    - ParmSpreadsheet: Parameter spreadsheet
    - Textport: Houdini textport/console
    - PythonShell: Python shell
    - IPRViewer: Interactive render preview
    - MaterialPalette: Material palette
    - AssetBrowser: Asset browser
    - TreeView: Tree view
    - DetailsView: Details view
    - DataTree: Data tree (USD)
    - SceneGraphTree: Scene graph tree (USD/Solaris)
    - RenderGallery: Render gallery
    - ChannelList: Channel list
    - ChannelViewer: Channel viewer
    - TakeList: Take list
    - BundleList: Bundle list
    - HandleList: Handle list
    - LightLinker: Light linker
    - HelpBrowser: Help browser
    - PerformanceMonitor: Performance monitor
    - OutputViewer: Output viewer
    - ShaderViewer: Shader viewer
    - ApexEditor: APEX graph editor
    - ContextViewer: Context viewer
    - EngineSessionSync: Engine session sync
    - PythonPanel: Python panel

Note: Panes on inactive desktops may report -1x-1 geometry and cannot be captured.
"""

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ._common import (
    ensure_connected,
    get_connection,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
    handle_connection_errors,
)

logger = logging.getLogger("houdini_mcp.tools.pane_screenshot")


# All valid pane type names from hou.paneTabType
VALID_PANE_TYPES: List[str] = [
    "ApexEditor",
    "AssetBrowser",
    "BundleList",
    "ChannelEditor",
    "ChannelList",
    "ChannelViewer",
    "CompositorViewer",
    "ContextViewer",
    "DataTree",
    "DetailsView",
    "EngineSessionSync",
    "HandleList",
    "HelpBrowser",
    "IPRViewer",
    "LightLinker",
    "MaterialPalette",
    "NetworkEditor",
    "OutputViewer",
    "Parm",
    "ParmSpreadsheet",
    "PerformanceMonitor",
    "PythonPanel",
    "PythonShell",
    "RenderGallery",
    "SceneGraphTree",
    "SceneViewer",
    "ShaderViewer",
    "TakeList",
    "Textport",
    "TreeView",
]


def _get_qt_modules(hou: Any) -> Tuple[Any, Any, Any]:
    """
    Get PySide2 Qt modules from the RPyC connection.

    Args:
        hou: The hou module netref

    Returns:
        Tuple of (QtWidgets, QtCore, QtGui) module references

    Raises:
        HoudiniConnectionError: If cannot get RPyC connection
    """
    conn = object.__getattribute__(hou, "____conn__")
    if conn is None:
        raise HoudiniConnectionError("Cannot get RPyC connection from hou module")

    QtWidgets = conn.modules["PySide2.QtWidgets"]
    QtCore = conn.modules["PySide2.QtCore"]
    QtGui = conn.modules["PySide2.QtGui"]

    return QtWidgets, QtCore, QtGui


def _get_available_pane_types(hou: Any) -> List[str]:
    """
    Get list of available pane type names from hou.paneTabType enum.

    Args:
        hou: The hou module reference

    Returns:
        List of pane type names (strings)
    """
    try:
        return [t for t in dir(hou.paneTabType) if not t.startswith("_") and t != "thisown"]
    except Exception:
        return VALID_PANE_TYPES


def _fit_pane_contents(pane: Any, pane_type_name: str) -> Optional[str]:
    """
    Fit/frame the contents of a pane to show all items.

    Args:
        pane: The pane tab object
        pane_type_name: Name of the pane type

    Returns:
        None on success, error message string on failure
    """
    try:
        if pane_type_name == "NetworkEditor":
            # NetworkEditor has homeAll() to frame all nodes
            # or homeToSelection() for selected nodes
            if hasattr(pane, "homeAll"):
                pane.homeAll()
            else:
                return "NetworkEditor does not support homeAll()"
        elif pane_type_name == "SceneViewer":
            # SceneViewer can frame geometry
            if hasattr(pane, "homeAll"):
                pane.homeAll()
            elif hasattr(pane, "homeSelected"):
                pane.homeSelected()
        elif pane_type_name == "CompositorViewer":
            if hasattr(pane, "homeAll"):
                pane.homeAll()
        elif pane_type_name == "ChannelEditor":
            if hasattr(pane, "homeAll"):
                pane.homeAll()
        # Other pane types may not support fitting
        return None
    except Exception as e:
        return f"Failed to fit contents: {e}"


def _capture_pane_to_bytes(
    hou: Any,
    pane_type_name: str,
    QtWidgets: Any,
    QtCore: Any,
    fit_contents: bool = False,
) -> Dict[str, Any]:
    """
    Internal function to capture a pane screenshot and return raw bytes.

    Args:
        hou: The hou module reference
        pane_type_name: Name of the pane type to capture
        QtWidgets: PySide2.QtWidgets module reference
        QtCore: PySide2.QtCore module reference
        fit_contents: If True, fit/frame contents before capture (for supported panes)

    Returns:
        Dict with either success data (including raw_bytes) or error info
    """
    # Get pane type enum
    pane_type = getattr(hou.paneTabType, pane_type_name, None)
    if pane_type is None:
        return {
            "status": "error",
            "message": f"Unknown pane type: {pane_type_name}",
            "available_types": _get_available_pane_types(hou),
        }

    # Find pane
    pane = hou.ui.paneTabOfType(pane_type)
    if pane is None:
        return {
            "status": "error",
            "message": f"No pane of type {pane_type_name} found in the current Houdini layout. "
            "Make sure a pane of this type is visible in the UI.",
        }

    # Fit contents if requested
    if fit_contents:
        fit_error = _fit_pane_contents(pane, pane_type_name)
        if fit_error:
            logger.warning(fit_error)

    # Get geometry
    screen_geom = pane.qtScreenGeometry()
    geom_x: int = screen_geom.x()
    geom_y: int = screen_geom.y()
    geom_width: int = screen_geom.width()
    geom_height: int = screen_geom.height()

    # Check for invalid geometry (pane on inactive desktop or minimized)
    if geom_width <= 0 or geom_height <= 0:
        return {
            "status": "error",
            "message": f"Pane {pane_type_name} has invalid geometry ({geom_width}x{geom_height}). "
            "It may be on an inactive desktop or minimized.",
        }

    # Get QApplication and screen
    app = QtWidgets.QApplication.instance()
    if app is None:
        return {
            "status": "error",
            "message": "No QApplication instance found. Houdini UI may not be initialized.",
        }

    screen = app.primaryScreen()
    if screen is None:
        return {"status": "error", "message": "No primary screen found."}

    # Capture screen region
    pixmap = screen.grabWindow(0, geom_x, geom_y, geom_width, geom_height)

    if pixmap.isNull():
        return {
            "status": "error",
            "message": "Screen grab returned null pixmap. The screen region may not be accessible.",
        }

    # Convert to PNG bytes
    image = pixmap.toImage()
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    raw_bytes = bytes(buffer.data().data())

    # Get pane name safely
    try:
        pane_name = str(pane.name())
    except Exception:
        pane_name = "<unknown>"

    return {
        "status": "success",
        "pane_type": pane_type_name,
        "pane_name": pane_name,
        "geometry": {"x": geom_x, "y": geom_y, "width": geom_width, "height": geom_height},
        "raw_bytes": raw_bytes,
    }


@handle_connection_errors("capture_pane_screenshot")
def capture_pane_screenshot(
    pane_type_name: str = "NetworkEditor",
    save_path: Optional[str] = None,
    fit_contents: bool = False,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Capture a screenshot of a Houdini pane tab using Qt screen grab.

    This function captures the screen region occupied by a specific pane tab
    in the Houdini interface. It uses PySide2/Qt's screen grab functionality
    accessed remotely via RPyC.

    Args:
        pane_type_name: Name of the pane type to capture. Common values:
            - "NetworkEditor": Node network editor (default)
            - "SceneViewer": 3D scene viewer
            - "Parm": Parameter editor panel
            - "CompositorViewer": Compositor/COP viewer
            - "IPRViewer": Interactive render preview
            - "ChannelEditor": Animation channel editor
            - "ParmSpreadsheet": Parameter spreadsheet
            - "Textport": Houdini textport/console
            - "PythonShell": Python shell
        save_path: Optional path to save PNG file. If provided, saves to disk
            instead of returning base64. Parent directories are created if needed.
        fit_contents: If True, fit/frame all contents before capture (default: False).
            Supported for: NetworkEditor (frames all nodes), SceneViewer (frames geometry),
            CompositorViewer, ChannelEditor. When False, captures the current view
            (useful for showing what you're actively working on).
        host: Houdini RPC server hostname (default: "localhost")
        port: Houdini RPC server port (default: 18811)

    Returns:
        Dict containing:
        - status: "success" or "error"
        - pane_type: The pane type that was captured
        - pane_name: The name of the specific pane instance
        - geometry: Dict with x, y, width, height of the captured region
        - image_format: Image format ("png")
        - image_size_bytes: Size of the image data in bytes
        - image_base64: Base64-encoded PNG image data (if save_path not provided)
        - file_path: Absolute path to saved file (if save_path provided)

        On error:
        - status: "error"
        - message: Error description
        - available_types: List of available pane types (if pane type not found)

    Example:
        # Capture the network editor as-is (current view)
        result = capture_pane_screenshot("NetworkEditor")

        # Capture with all nodes framed
        result = capture_pane_screenshot("NetworkEditor", fit_contents=True)

        # Capture and save directly to disk
        result = capture_pane_screenshot("SceneViewer", save_path="/tmp/scene.png")
        if result["status"] == "success":
            print(f"Saved to: {result['file_path']}")
    """
    hou = ensure_connected(host, port)

    # Get Qt modules from RPyC connection
    try:
        QtWidgets, QtCore, _ = _get_qt_modules(hou)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to access PySide2 modules: {e}. "
            "Ensure Houdini has PySide2 available.",
        }

    # Capture pane to bytes
    result = _capture_pane_to_bytes(hou, pane_type_name, QtWidgets, QtCore, fit_contents)

    if result["status"] != "success":
        return result

    # Extract raw bytes and add format info
    raw_bytes: bytes = result.pop("raw_bytes")
    result["image_format"] = "png"
    result["image_size_bytes"] = len(raw_bytes)

    # Either save to disk or return as base64
    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw_bytes)
        result["file_path"] = str(path.absolute())
    else:
        result["image_base64"] = base64.b64encode(raw_bytes).decode("utf-8")

    return result


@handle_connection_errors("list_visible_panes")
def list_visible_panes(
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    List all visible pane tabs in the current Houdini layout.

    This is useful for discovering what panes are available for screenshots.
    Panes on inactive desktops will have is_visible=False and cannot be captured.

    Args:
        host: Houdini RPC server hostname (default: "localhost")
        port: Houdini RPC server port (default: 18811)

    Returns:
        Dict containing:
        - status: "success" or "error"
        - current_desktop: Name of the current active desktop
        - panes: List of dicts with pane info:
            - name: Pane tab name
            - type: Pane type name
            - desktop: Desktop name containing this pane
            - is_current_desktop: Whether pane is on the active desktop
            - is_visible: Whether pane has valid geometry (can be captured)
            - geometry: Dict with width/height (None if not visible)
            - capturable: True if pane can be captured (visible and on current desktop)
        - capturable_count: Number of panes that can be captured
        - total_count: Total number of panes found
        - available_types: List of all valid pane type names
    """
    hou = ensure_connected(host, port)

    panes_info: List[Dict[str, Any]] = []
    current_desktop_name: Optional[str] = None

    # Get current desktop name
    try:
        current_desktop = hou.ui.curDesktop()
        current_desktop_name = current_desktop.name() if current_desktop else None
    except Exception:
        pass

    # Iterate through all desktops and panes
    try:
        for desktop in hou.ui.desktops():
            desktop_name = desktop.name()
            is_current = (desktop_name == current_desktop_name) if current_desktop_name else False

            for pane_tab in desktop.paneTabs():
                try:
                    pane_type = pane_tab.type()
                    pane_type_name = (
                        pane_type.name() if hasattr(pane_type, "name") else str(pane_type)
                    )

                    # Get geometry
                    geom = pane_tab.qtScreenGeometry()
                    geom_width = geom.width()
                    geom_height = geom.height()

                    # Check if visible (geometry > 0, not -1x-1)
                    is_visible = geom_width > 0 and geom_height > 0

                    panes_info.append(
                        {
                            "name": str(pane_tab.name()),
                            "type": pane_type_name,
                            "desktop": desktop_name,
                            "is_current_desktop": is_current,
                            "is_visible": is_visible,
                            "geometry": {"width": geom_width, "height": geom_height}
                            if is_visible
                            else None,
                            "capturable": is_visible and is_current,
                        }
                    )
                except Exception as e:
                    logger.debug(f"Failed to get pane info: {e}")
    except Exception as e:
        return {"status": "error", "message": f"Failed to enumerate panes: {e}"}

    # Sort: capturable first, then by type name
    panes_info.sort(key=lambda p: (not p["capturable"], p["type"]))

    return {
        "status": "success",
        "current_desktop": current_desktop_name,
        "panes": panes_info,
        "capturable_count": sum(1 for p in panes_info if p["capturable"]),
        "total_count": len(panes_info),
        "available_types": VALID_PANE_TYPES,
    }


@handle_connection_errors("capture_multiple_panes")
def capture_multiple_panes(
    pane_types: List[str],
    save_dir: Optional[str] = None,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Capture screenshots of multiple pane types in one call.

    This is more efficient than calling capture_pane_screenshot multiple times
    as it reuses the Qt module references and connection.

    Args:
        pane_types: List of pane type names to capture (e.g., ["NetworkEditor", "SceneViewer"])
        save_dir: Optional directory to save PNG files. If provided, saves files
            as "{pane_type}.png" in this directory. Parent directories are created if needed.
            If not provided, returns base64-encoded images.
        host: Houdini RPC server hostname (default: "localhost")
        port: Houdini RPC server port (default: 18811)

    Returns:
        Dict containing:
        - status: "success" if at least one capture succeeded, "error" if all failed
        - success_count: Number of successful captures
        - total_requested: Total number of pane types requested
        - results: Dict mapping pane type names to their capture results
            Each result is a dict with the same format as capture_pane_screenshot

    Example:
        # Capture multiple panes and get base64
        result = capture_multiple_panes(["NetworkEditor", "SceneViewer", "Parm"])
        for pane_type, data in result["results"].items():
            if data["status"] == "success":
                print(f"{pane_type}: {data['image_size_bytes']} bytes")

        # Capture and save to directory
        result = capture_multiple_panes(
            ["NetworkEditor", "SceneViewer"],
            save_dir="/tmp/houdini_captures"
        )
        # Creates /tmp/houdini_captures/NetworkEditor.png, etc.
    """
    hou = ensure_connected(host, port)

    # Get Qt modules from RPyC connection
    try:
        QtWidgets, QtCore, _ = _get_qt_modules(hou)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to access PySide2 modules: {e}. "
            "Ensure Houdini has PySide2 available.",
        }

    results: Dict[str, Dict[str, Any]] = {}
    success_count = 0

    for pane_type_name in pane_types:
        result = _capture_pane_to_bytes(hou, pane_type_name, QtWidgets, QtCore)

        if result["status"] == "success":
            raw_bytes: bytes = result.pop("raw_bytes")
            result["image_format"] = "png"
            result["image_size_bytes"] = len(raw_bytes)

            if save_dir:
                path = Path(save_dir) / f"{pane_type_name}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw_bytes)
                result["file_path"] = str(path.absolute())
            else:
                result["image_base64"] = base64.b64encode(raw_bytes).decode("utf-8")

            success_count += 1

        results[pane_type_name] = result

    return {
        "status": "success" if success_count > 0 else "error",
        "success_count": success_count,
        "total_requested": len(pane_types),
        "results": results,
    }
