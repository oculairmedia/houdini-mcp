"""Connection adapter for local (in-process) Houdini access.

This module provides a unified interface for accessing Houdini,
whether running in-process (stdio mode) or via RPyC (remote mode).
"""

import logging
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger("houdini_mcp_plugin.connection")

# Global connection instance
_connection: Optional["HoudiniConnectionProtocol"] = None


@runtime_checkable
class HoudiniConnectionProtocol(Protocol):
    """Protocol defining the interface for Houdini connections."""

    @property
    def hou(self) -> Any:
        """Access to the hou module."""
        ...

    def is_connected(self) -> bool:
        """Check if connected to Houdini."""
        ...

    def get_remote_modules(self) -> tuple[Any, Any, Any]:
        """Get remote os, tempfile, and base64 modules for file operations."""
        ...


class LocalHoudiniConnection:
    """Direct in-process connection to Houdini.

    Used when the MCP server runs inside Houdini's Python environment.
    Provides direct access to the hou module without network overhead.
    """

    def __init__(self):
        """Initialize local connection."""
        self._hou: Optional[Any] = None

    @property
    def hou(self) -> Any:
        """Get the hou module.

        Lazy-loads the hou module on first access.
        """
        if self._hou is None:
            try:
                import hou

                self._hou = hou
                logger.info("Connected to Houdini in-process")
            except ImportError as e:
                logger.error("Failed to import hou module - not running inside Houdini?")
                raise RuntimeError(
                    "Cannot import hou module. "
                    "This plugin must run inside Houdini's Python environment."
                ) from e
        return self._hou

    def is_connected(self) -> bool:
        """Check if connected to Houdini.

        For local connections, we're connected if we can import hou.
        """
        try:
            _ = self.hou
            return True
        except RuntimeError:
            return False

    def get_remote_modules(self) -> tuple[Any, Any, Any]:
        """Get modules for file operations.

        For local connections, these are just the standard library modules
        since we're running on the same machine as Houdini.
        """
        import os
        import tempfile
        import base64

        return os, tempfile, base64

    def get_info(self) -> dict[str, Any]:
        """Get connection information."""
        if not self.is_connected():
            return {
                "connected": False,
                "mode": "local",
            }

        return {
            "connected": True,
            "mode": "local",
            "houdini_version": self.hou.applicationVersionString(),
            "hip_file": self.hou.hipFile.path(),
        }


def get_connection() -> HoudiniConnectionProtocol:
    """Get the current Houdini connection.

    Returns the global connection instance, creating it if necessary.
    In stdio mode, this returns a LocalHoudiniConnection.
    """
    global _connection
    if _connection is None:
        _connection = LocalHoudiniConnection()
    return _connection


def set_connection(conn: HoudiniConnectionProtocol) -> None:
    """Set the global connection instance.

    This allows switching between local and remote connections.
    """
    global _connection
    _connection = conn


def reset_connection() -> None:
    """Reset the global connection.

    Clears the connection so the next get_connection() call
    will create a fresh connection.
    """
    global _connection
    _connection = None
