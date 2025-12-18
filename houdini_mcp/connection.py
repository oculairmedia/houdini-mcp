"""Houdini connection manager using hrpyc with retry logic and validation."""

import logging
import time
from typing import Optional, Any, Tuple, Dict

logger = logging.getLogger("houdini_mcp.connection")

# Global connection state
_connection: Optional[Any] = None
_hou: Optional[Any] = None

# Connection configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds
DEFAULT_TIMEOUT = 10.0  # seconds


class HoudiniConnectionError(Exception):
    """Raised when unable to connect to Houdini."""
    pass


class HoudiniOperationError(Exception):
    """Raised when a Houdini operation fails."""
    pass


def connect(
    host: str = "localhost",
    port: int = 18811,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY
) -> Tuple[Any, Any]:
    """
    Connect to Houdini RPC server using hrpyc with retry logic.
    
    Args:
        host: Houdini server hostname (default: localhost)
        port: Houdini RPC port (default: 18811)
        max_retries: Maximum number of connection attempts
        retry_delay: Initial delay between retries (doubles each attempt)
        
    Returns:
        Tuple of (connection, hou module)
        
    Raises:
        HoudiniConnectionError: If connection fails after all retries
    """
    global _connection, _hou
    
    try:
        import hrpyc  # type: ignore
    except ImportError:
        raise HoudiniConnectionError(
            "hrpyc not available. This module requires hrpyc to be installed. "
            "Install with: pip install hrpyc"
        )
    
    last_error: Optional[Exception] = None
    current_delay = retry_delay
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Connecting to Houdini at {host}:{port} (attempt {attempt + 1}/{max_retries})")
            _connection, _hou = hrpyc.import_remote_module(host, port)
            
            # Validate connection by checking Houdini version
            hou_module: Any = _hou
            version = hou_module.applicationVersionString()
            logger.info(f"Connected to Houdini version: {version}")
            
            # Additional validation - ensure we can access common nodes
            obj_node = hou_module.node("/obj")
            if obj_node is None:
                logger.warning("Connected but /obj node not accessible - unusual state")
            
            return _connection, _hou
            
        except Exception as e:
            last_error = e
            logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {current_delay:.1f} seconds...")
                time.sleep(current_delay)
                current_delay *= 2  # Exponential backoff
    
    raise HoudiniConnectionError(
        f"Failed to connect to Houdini at {host}:{port} after {max_retries} attempts. "
        f"Make sure Houdini is running with RPC server enabled "
        f"(run 'import hrpyc; hrpyc.start_server()' in Houdini's Python shell). "
        f"Last error: {last_error}"
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


def disconnect() -> None:
    """Disconnect from Houdini gracefully."""
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
    """
    Check if connected to Houdini with validation.
    
    Performs a lightweight operation to verify the connection is alive.
    """
    global _connection, _hou
    
    if _connection is None or _hou is None:
        return False
    
    try:
        # Try a simple operation to verify connection is alive
        hou_module: Any = _hou
        hou_module.applicationVersion()
        return True
    except Exception as e:
        logger.debug(f"Connection check failed: {e}")
        # Connection is dead, clean up
        _connection = None
        _hou = None
        return False


def ensure_connected(host: str = "localhost", port: int = 18811) -> Any:
    """
    Ensure we're connected to Houdini, reconnecting if necessary.
    
    This is the preferred method for tools to get the hou module,
    as it handles connection recovery automatically.
    
    Returns:
        The remote hou module
        
    Raises:
        HoudiniConnectionError: If unable to establish connection
    """
    if not is_connected():
        logger.info("Connection lost or not established, reconnecting...")
        connect(host, port)
    return _hou


def get_connection_info(host: str = "localhost", port: int = 18811) -> Dict[str, Any]:
    """
    Get detailed information about the current connection state.
    
    Returns:
        Dict with connection status, host, port, and Houdini info if connected.
    """
    info: Dict[str, Any] = {
        "host": host,
        "port": port,
        "connected": False,
        "houdini_version": None,
        "houdini_build": None,
        "hip_file": None
    }
    
    if is_connected():
        try:
            hou_module: Any = _hou
            info["connected"] = True
            info["houdini_version"] = hou_module.applicationVersionString()
            version_tuple = hou_module.applicationVersion()
            info["houdini_build"] = {
                "major": version_tuple[0],
                "minor": version_tuple[1],
                "build": version_tuple[2]
            }
            info["hip_file"] = hou_module.hipFile.path() or "untitled.hip"
        except Exception as e:
            logger.warning(f"Error getting connection info: {e}")
            info["error"] = str(e)
    
    return info


def ping(host: str = "localhost", port: int = 18811) -> bool:
    """
    Quick connectivity test without maintaining connection.
    
    Returns:
        True if Houdini RPC server is reachable, False otherwise.
    """
    try:
        import hrpyc  # type: ignore
        conn, hou = hrpyc.import_remote_module(host, port)
        hou.applicationVersion()  # Validate we can call methods
        conn.close()
        return True
    except Exception as e:
        logger.debug(f"Ping failed: {e}")
        return False
