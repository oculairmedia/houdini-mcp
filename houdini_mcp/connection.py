"""Houdini connection manager using rpyc with retry logic and validation.

Note: We use rpyc.classic directly instead of hrpyc because:
1. hrpyc is bundled with Houdini and not available on PyPI
2. rpyc.classic.connect() provides the same functionality
3. IMPORTANT: rpyc must be version 5.x (6.x has protocol incompatibility)
"""

import logging
import random
import time
import threading
import concurrent.futures
from typing import Optional, Any, Tuple, Dict, Callable, TypeVar, Type
from functools import wraps

import rpyc
from rpyc.utils.classic import DEFAULT_SERVER_PORT

logger = logging.getLogger("houdini_mcp.connection")

# Type variable for generic retry decorator
F = TypeVar("F", bound=Callable[..., Any])

# Global connection state
_connection: Optional[Any] = None
_hou: Optional[Any] = None

# Thread pool for controlled execution with timeouts
_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

# Connection configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # maximum delay cap
DEFAULT_TIMEOUT = 10.0  # seconds
DEFAULT_SYNC_TIMEOUT = 30.0  # timeout for individual RPC calls (seconds) - reduced from 60
DEFAULT_OPERATION_TIMEOUT = 45.0  # max time for any single tool operation

# Retryable exceptions for connection and RPC operations
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
    EOFError,
    BrokenPipeError,
    OSError,
)


class HoudiniConnectionError(Exception):
    """Raised when unable to connect to Houdini."""

    pass


class HoudiniOperationError(Exception):
    """Raised when a Houdini operation fails."""

    pass


def retry_with_backoff(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
) -> Callable[[F], F]:
    """
    Decorator that retries a function with exponential backoff and optional jitter.

    This prevents thundering herd problems when multiple clients try to reconnect
    simultaneously, and provides graceful degradation under load.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay cap in seconds (default: 30.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        jitter: If True, add random jitter to prevent thundering herd (default: True)
        retryable_exceptions: Tuple of exception types that trigger retry

    Returns:
        Decorated function that retries on specified exceptions

    Example:
        @retry_with_backoff(max_retries=5, jitter=True)
        def connect_to_houdini():
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            current_delay = base_delay

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt < max_retries - 1:
                        # Calculate delay with exponential backoff
                        delay = min(current_delay, max_delay)

                        # Add jitter to prevent thundering herd
                        if jitter:
                            # Add up to 10% random jitter
                            delay += random.uniform(0, delay * 0.1)

                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries} failed: {e}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        current_delay *= exponential_base
                    else:
                        logger.error(f"All {max_retries} attempts failed. Last error: {e}")

            # Re-raise the last exception after all retries exhausted
            if last_exception:
                raise last_exception
            return None  # Should never reach here

        return wrapper  # type: ignore

    return decorator


def _do_connect(
    host: str,
    port: int,
    sync_timeout: float,
) -> Tuple[Any, Any]:
    """
    Internal function to establish a single connection attempt.

    This is wrapped by connect() with retry logic.
    """
    global _connection, _hou

    logger.info(f"Connecting to Houdini at {host}:{port}")

    # Use rpyc.classic.connect for simple SlaveService connection
    # Note: rpyc.classic.connect() does not accept config parameter
    _connection = rpyc.classic.connect(host, port)

    # Set sync_request_timeout on the connection after establishing it
    # This prevents hangs when Houdini is busy (e.g., cooking heavy geometry)
    if hasattr(_connection, "_config"):
        _connection._config["sync_request_timeout"] = sync_timeout

    _hou = _connection.modules.hou

    # Validate connection by checking Houdini version
    version = _hou.applicationVersionString()
    logger.info(f"Connected to Houdini version: {version}")

    # Additional validation - ensure we can access common nodes
    obj_node = _hou.node("/obj")
    if obj_node is None:
        logger.warning("Connected but /obj node not accessible - unusual state")

    return _connection, _hou


def connect(
    host: str = "localhost",
    port: int = 18811,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    sync_timeout: float = DEFAULT_SYNC_TIMEOUT,
    jitter: bool = True,
) -> Tuple[Any, Any]:
    """
    Connect to Houdini RPC server using rpyc with retry logic.

    Uses exponential backoff with optional jitter to prevent thundering herd
    problems when multiple clients reconnect simultaneously.

    Args:
        host: Houdini server hostname (default: localhost)
        port: Houdini RPC port (default: 18811)
        max_retries: Maximum number of connection attempts (default: 3)
        retry_delay: Initial delay between retries in seconds (default: 1.0)
        sync_timeout: Timeout for synchronous RPC calls in seconds (default: 30)
        jitter: If True, add random jitter to delays (default: True)

    Returns:
        Tuple of (connection, hou module)

    Raises:
        HoudiniConnectionError: If connection fails after all retries
    """
    last_error: Optional[Exception] = None
    current_delay = retry_delay

    for attempt in range(max_retries):
        try:
            return _do_connect(host, port, sync_timeout)

        except RETRYABLE_EXCEPTIONS as e:
            last_error = e
            logger.warning(f"Connection attempt {attempt + 1}/{max_retries} failed: {e}")

            if attempt < max_retries - 1:
                # Calculate delay with cap
                delay = min(current_delay, DEFAULT_MAX_DELAY)

                # Add jitter to prevent thundering herd
                if jitter:
                    delay += random.uniform(0, delay * 0.1)

                logger.info(f"Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
                current_delay *= 2  # Exponential backoff

        except Exception as e:
            # Non-retryable exception - fail immediately
            raise HoudiniConnectionError(
                f"Non-retryable error connecting to Houdini at {host}:{port}: {e}"
            ) from e

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


def is_connected(validate: bool = False) -> bool:
    """
    Check if connected to Houdini.

    By default, only checks if connection objects exist and socket is open.
    This is fast (no RPC call). Set validate=True to perform an RPC call
    to verify Houdini is actually responsive (slower but more thorough).

    Args:
        validate: If True, perform RPC call to verify connection is alive.
                  If False (default), only check socket state for speed.

    Returns:
        True if connected, False otherwise.
    """
    global _connection, _hou

    if _connection is None or _hou is None:
        return False

    try:
        # Fast path: check if connection is closed without RPC
        # Use explicit comparison to True/False to handle MagicMock correctly
        if hasattr(_connection, "closed"):
            closed_val = _connection.closed
            # Handle both bool and MagicMock cases
            if closed_val is True:
                logger.debug("Connection socket is closed")
                _connection = None
                _hou = None
                return False

        # If validation requested, do an RPC call
        if validate:
            _hou.applicationVersion()

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
        "hip_file": None,
    }

    if is_connected():
        try:
            info["connected"] = True
            info["houdini_version"] = _hou.applicationVersionString()
            version_tuple = _hou.applicationVersion()
            info["houdini_build"] = {
                "major": version_tuple[0],
                "minor": version_tuple[1],
                "build": version_tuple[2],
            }
            info["hip_file"] = _hou.hipFile.path() or "untitled.hip"
        except Exception as e:
            logger.warning(f"Error getting connection info: {e}")
            info["error"] = str(e)

    return info


def ping(host: str = "localhost", port: int = 18811, timeout: float = 5.0) -> bool:
    """
    Quick connectivity test without maintaining connection.

    Args:
        host: Houdini server hostname
        port: Houdini RPC port
        timeout: Timeout in seconds for the ping (default: 5.0)

    Returns:
        True if Houdini RPC server is reachable, False otherwise.
    """
    try:
        # Note: rpyc.classic.connect() does not accept config parameter
        # timeout is not enforced at connection level for classic connections
        conn = rpyc.classic.connect(host, port)
        hou = conn.modules.hou
        hou.applicationVersion()  # Validate we can call methods
        conn.close()
        return True
    except Exception as e:
        logger.debug(f"Ping failed: {e}")
        return False


class HoudiniOperationTimeout(Exception):
    """Raised when a Houdini operation times out."""

    pass


class SafeExecutionResult:
    """Result wrapper for safe_execute operations."""

    def __init__(
        self,
        success: bool,
        result: Any = None,
        error: Optional[str] = None,
        error_type: Optional[str] = None,
        timed_out: bool = False,
        connection_lost: bool = False,
    ):
        self.success = success
        self.result = result
        self.error = error
        self.error_type = error_type
        self.timed_out = timed_out
        self.connection_lost = connection_lost

    def to_error_dict(self, operation: str) -> Dict[str, Any]:
        """Convert to standardized error response dict."""
        if self.timed_out:
            message = (
                f"Operation '{operation}' timed out. Houdini may be processing heavy geometry. "
                "Try with less data or simpler operations."
            )
        elif self.connection_lost:
            message = (
                f"Connection to Houdini was lost during '{operation}'. "
                "The connection will be re-established on the next call."
            )
        else:
            message = f"Operation '{operation}' failed: {self.error}"

        return {
            "status": "error",
            "error_type": self.error_type or "operation_error",
            "message": message,
            "operation": operation,
            "timed_out": self.timed_out,
            "connection_lost": self.connection_lost,
            "recoverable": True,
        }


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Get or create the thread pool executor."""
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="houdini_rpc"
        )
    return _executor


def safe_execute(
    func: Callable[..., Any],
    *args: Any,
    timeout: float = DEFAULT_OPERATION_TIMEOUT,
    operation_name: str = "unknown",
    **kwargs: Any,
) -> SafeExecutionResult:
    """
    Execute a function with timeout protection and connection error handling.

    This wraps any Houdini RPC operation to ensure:
    1. It cannot hang indefinitely (controlled timeout)
    2. Connection errors are caught and reported cleanly
    3. The connection is cleaned up on failure

    Args:
        func: The function to execute
        *args: Arguments to pass to the function
        timeout: Maximum execution time in seconds
        operation_name: Name of the operation for error messages
        **kwargs: Keyword arguments to pass to the function

    Returns:
        SafeExecutionResult with success/failure info
    """
    global _connection, _hou

    executor = _get_executor()

    try:
        future = executor.submit(func, *args, **kwargs)
        result = future.result(timeout=timeout)
        return SafeExecutionResult(success=True, result=result)

    except concurrent.futures.TimeoutError:
        logger.error(f"Operation '{operation_name}' timed out after {timeout}s")
        # Cancel the future if possible (though RPyC calls may not be cancellable)
        future.cancel()
        # Clean up the potentially broken connection
        _safe_disconnect()
        return SafeExecutionResult(
            success=False,
            error=f"Timed out after {timeout} seconds",
            error_type="timeout",
            timed_out=True,
        )

    except (EOFError, BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError) as e:
        logger.error(f"Connection error during '{operation_name}': {type(e).__name__}: {e}")
        _safe_disconnect()
        return SafeExecutionResult(
            success=False,
            error=str(e),
            error_type="connection_error",
            connection_lost=True,
        )

    except Exception as e:
        logger.error(f"Error during '{operation_name}': {type(e).__name__}: {e}")
        # Check if this looks like a connection error
        error_str = str(e).lower()
        if any(
            x in error_str for x in ["connection", "eof", "broken", "reset", "refused", "timeout"]
        ):
            _safe_disconnect()
            return SafeExecutionResult(
                success=False,
                error=str(e),
                error_type="connection_error",
                connection_lost=True,
            )
        return SafeExecutionResult(
            success=False,
            error=str(e),
            error_type=type(e).__name__,
        )


def _safe_disconnect() -> None:
    """Safely disconnect without raising exceptions."""
    global _connection, _hou
    try:
        if _connection is not None:
            _connection.close()
    except Exception as e:
        logger.debug(f"Error during safe disconnect: {e}")
    finally:
        _connection = None
        _hou = None


def execute_with_timeout(
    func: Callable[..., Any],
    *args: Any,
    timeout: float = DEFAULT_OPERATION_TIMEOUT,
    **kwargs: Any,
) -> Any:
    """
    Execute a function with a timeout, raising HoudiniOperationTimeout if exceeded.

    Unlike safe_execute, this raises exceptions rather than returning a result object.
    Use this for internal operations where you want to handle the exception yourself.

    Args:
        func: Function to execute
        *args: Arguments to pass
        timeout: Maximum execution time in seconds
        **kwargs: Keyword arguments to pass

    Returns:
        The function result

    Raises:
        HoudiniOperationTimeout: If the operation times out
        Various exceptions: If the operation fails for other reasons
    """
    executor = _get_executor()

    try:
        future = executor.submit(func, *args, **kwargs)
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise HoudiniOperationTimeout(f"Operation timed out after {timeout} seconds")


def quick_health_check(host: str = "localhost", port: int = 18811, timeout: float = 5.0) -> bool:
    """
    Quick health check with strict timeout - use before heavy operations.

    Uses is_connected(validate=True) to perform an actual RPC call
    and verify Houdini is responsive.

    Args:
        host: Houdini server hostname
        port: Houdini RPC port
        timeout: Maximum time to wait

    Returns:
        True if Houdini is responsive, False otherwise
    """
    # First do fast check without RPC
    if not is_connected(validate=False):
        return False

    def _check():
        try:
            _hou.applicationVersion()
            return True
        except Exception:
            return False

    try:
        result = execute_with_timeout(_check, timeout=timeout)
        return result
    except (HoudiniOperationTimeout, Exception):
        return False
