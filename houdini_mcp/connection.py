"""Houdini connection manager using hrpyc."""

import logging
from typing import Optional, Any, Tuple

logger = logging.getLogger("houdini_mcp.connection")

# Global connection state
_connection: Optional[Any] = None
_hou: Optional[Any] = None


class HoudiniConnectionError(Exception):
    """Raised when unable to connect to Houdini."""
    pass


def connect(host: str = "localhost", port: int = 18811) -> Tuple[Any, Any]:
    """
    Connect to Houdini RPC server using hrpyc.
    
    Args:
        host: Houdini server hostname (default: localhost)
        port: Houdini RPC port (default: 18811)
        
    Returns:
        Tuple of (connection, hou module)
        
    Raises:
        HoudiniConnectionError: If connection fails
    """
    global _connection, _hou
    
    try:
        import hrpyc
        logger.info(f"Connecting to Houdini at {host}:{port}")
        _connection, _hou = hrpyc.import_remote_module(host, port)
        logger.info(f"Connected to Houdini version: {_hou.applicationVersionString()}")
        return _connection, _hou
    except ImportError:
        raise HoudiniConnectionError(
            "hrpyc not available. This module requires hrpyc to be installed. "
            "Install with: pip install hrpyc"
        )
    except Exception as e:
        raise HoudiniConnectionError(
            f"Failed to connect to Houdini at {host}:{port}. "
            f"Make sure Houdini is running with RPC server enabled. Error: {e}"
        )


def get_hou(host: str = "localhost", port: int = 18811) -> Any:
    """
    Get the remote hou module, connecting if necessary.
    
    Args:
        host: Houdini server hostname
        port: Houdini RPC port
        
    Returns:
        The remote hou module
        
    Raises:
        HoudiniConnectionError: If connection fails
    """
    global _hou
    
    if _hou is None:
        connect(host, port)
    
    return _hou


def get_connection() -> Optional[Any]:
    """Get the current connection object."""
    return _connection


def disconnect():
    """Disconnect from Houdini."""
    global _connection, _hou
    
    if _connection is not None:
        try:
            _connection.close()
            logger.info("Disconnected from Houdini")
        except Exception as e:
            logger.warning(f"Error disconnecting: {e}")
        finally:
            _connection = None
            _hou = None


def is_connected() -> bool:
    """Check if connected to Houdini."""
    global _connection, _hou
    
    if _connection is None or _hou is None:
        return False
    
    try:
        # Try a simple operation to verify connection is alive
        _hou.applicationVersion()
        return True
    except Exception:
        # Connection is dead, clean up
        _connection = None
        _hou = None
        return False


def ensure_connected(host: str = "localhost", port: int = 18811) -> Any:
    """
    Ensure we're connected to Houdini, reconnecting if necessary.
    
    Returns:
        The remote hou module
    """
    if not is_connected():
        connect(host, port)
    return _hou
