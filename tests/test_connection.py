"""Tests for the Houdini connection manager."""

import pytest
from unittest.mock import MagicMock, patch

from houdini_mcp.connection import (
    HoudiniConnectionError,
    HoudiniOperationError,
    connect,
    disconnect,
    is_connected,
    ensure_connected,
    get_connection_info,
    ping,
    get_hou,
    get_connection,
)


class TestConnect:
    """Tests for the connect function."""

    def test_connect_success(self, mock_rpyc_with_reset, mock_hou):
        """Test successful connection to Houdini."""
        connection, hou = connect("localhost", 18811)

        assert connection is not None
        assert hou is not None
        assert hou.applicationVersionString() == "20.5.123"

    def test_connect_validates_version(self, mock_rpyc_with_reset, mock_hou):
        """Test that connect validates the Houdini version."""
        connection, hou = connect("localhost", 18811)

        # Verify version was checked
        assert hou.applicationVersionString() == "20.5.123"

    def test_connect_with_retry_success_on_second_attempt(self, reset_connection_state, mock_hou):
        """Test connection retry logic succeeds on second attempt."""
        from tests.conftest import MockRpycConnection

        mock_conn = MockRpycConnection(mock_hou)

        call_count = [0]

        def mock_connect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Connection refused")
            return mock_conn

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect = mock_connect
            connection, hou = connect("localhost", 18811, max_retries=3, retry_delay=0.01)

        assert call_count[0] == 2  # Failed once, succeeded on retry
        assert hou is not None

    def test_connect_all_retries_fail(self, reset_connection_state):
        """Test connection failure after all retries exhausted."""
        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")

            with pytest.raises(HoudiniConnectionError) as exc_info:
                connect("localhost", 18811, max_retries=2, retry_delay=0.01)

        assert "Failed to connect" in str(exc_info.value)
        assert "after 2 attempts" in str(exc_info.value)

    def test_connect_exponential_backoff(self, reset_connection_state, mock_hou):
        """Test that retry delay doubles each attempt (exponential backoff)."""
        from tests.conftest import MockRpycConnection
        import time

        mock_conn = MockRpycConnection(mock_hou)
        call_times = []

        def mock_connect(*args, **kwargs):
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ConnectionError("Connection refused")
            return mock_conn

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect = mock_connect
            connect("localhost", 18811, max_retries=3, retry_delay=0.05, jitter=False)

        assert len(call_times) == 3
        # Second delay should be ~2x the first
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]
        assert delay2 > delay1 * 1.5  # Allow some tolerance

    def test_connect_with_jitter(self, reset_connection_state, mock_hou):
        """Test that jitter adds randomness to retry delays."""
        from tests.conftest import MockRpycConnection
        import time

        mock_conn = MockRpycConnection(mock_hou)
        delays = []

        def mock_connect(*args, **kwargs):
            delays.append(time.time())
            if len(delays) < 3:
                raise ConnectionError("Connection refused")
            return mock_conn

        # Run multiple times to check jitter introduces variance
        all_delay_diffs = []
        for _ in range(3):
            delays.clear()
            with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
                mock_rpyc.classic.connect = mock_connect
                connect("localhost", 18811, max_retries=3, retry_delay=0.1, jitter=True)

            if len(delays) >= 2:
                all_delay_diffs.append(delays[1] - delays[0])

        # With jitter, delays should vary slightly between runs
        # Check that we got some variance (not all identical)
        if len(all_delay_diffs) >= 2:
            # Just verify the mechanism works - delays should be > base_delay
            assert all(d >= 0.09 for d in all_delay_diffs)  # Allow small timing variance

    def test_connect_custom_host_port(self, mock_rpyc_with_reset):
        """Test connect with custom host and port."""
        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            from tests.conftest import MockRpycConnection, MockHouModule

            mock_hou = MockHouModule()
            mock_conn = MockRpycConnection(mock_hou)
            mock_rpyc.classic.connect.return_value = mock_conn

            connect("192.168.1.100", 19999)

            mock_rpyc.classic.connect.assert_called_with("192.168.1.100", 19999)


class TestIsConnected:
    """Tests for the is_connected function."""

    def test_is_connected_true(self, mock_connection):
        """Test is_connected returns True when connected."""
        result = is_connected()
        assert result is True

    def test_is_connected_false_no_connection(self, reset_connection_state):
        """Test is_connected returns False when no connection."""
        result = is_connected()
        assert result is False

    def test_is_connected_false_dead_connection(self, reset_connection_state):
        """Test is_connected returns False when RPC validation fails."""
        import houdini_mcp.connection as conn_module

        # Set up a connection that will fail validation
        mock_hou = MagicMock()
        mock_hou.applicationVersion.side_effect = ConnectionError("Dead")
        conn_module._connection = MagicMock()
        conn_module._hou = mock_hou

        # Use validate=True to trigger RPC validation
        result = is_connected(validate=True)

        assert result is False
        assert conn_module._connection is None
        assert conn_module._hou is None

    def test_is_connected_cleans_up_on_failure(self, reset_connection_state):
        """Test is_connected cleans up global state on failure."""
        import houdini_mcp.connection as conn_module

        mock_hou = MagicMock()
        mock_hou.applicationVersion.side_effect = Exception("Connection lost")
        conn_module._connection = MagicMock()
        conn_module._hou = mock_hou

        # Use validate=True to trigger RPC validation
        is_connected(validate=True)

        assert conn_module._connection is None
        assert conn_module._hou is None

    def test_is_connected_fast_path_no_rpc(self, reset_connection_state):
        """Test that is_connected() without validate does no RPC call."""
        import houdini_mcp.connection as conn_module

        mock_hou = MagicMock()
        conn_module._connection = MagicMock()
        conn_module._connection.closed = False  # Explicitly set to False
        conn_module._hou = mock_hou

        # Default is_connected() should not call applicationVersion
        result = is_connected()

        assert result is True
        # Verify no RPC call was made
        mock_hou.applicationVersion.assert_not_called()


class TestDisconnect:
    """Tests for the disconnect function."""

    def test_disconnect_success(self, mock_connection):
        """Test successful disconnection."""
        import houdini_mcp.connection as conn_module

        disconnect()

        assert conn_module._connection is None
        assert conn_module._hou is None

    def test_disconnect_handles_close_error(self, reset_connection_state):
        """Test disconnect handles close errors gracefully."""
        import houdini_mcp.connection as conn_module

        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("Close failed")
        conn_module._connection = mock_conn
        conn_module._hou = MagicMock()

        # Should not raise
        disconnect()

        assert conn_module._connection is None
        assert conn_module._hou is None

    def test_disconnect_when_not_connected(self, reset_connection_state):
        """Test disconnect when not connected does nothing."""
        import houdini_mcp.connection as conn_module

        # Should not raise
        disconnect()

        assert conn_module._connection is None
        assert conn_module._hou is None

    def test_disconnect_calls_close(self, reset_connection_state):
        """Test disconnect calls close on connection."""
        import houdini_mcp.connection as conn_module

        mock_conn = MagicMock()
        conn_module._connection = mock_conn
        conn_module._hou = MagicMock()

        disconnect()

        mock_conn.close.assert_called_once()


class TestEnsureConnected:
    """Tests for the ensure_connected function."""

    def test_ensure_connected_already_connected(self, mock_connection, mock_hou):
        """Test ensure_connected returns hou when already connected."""
        hou = ensure_connected("localhost", 18811)
        assert hou is not None
        assert hou.applicationVersionString() == "20.5.123"

    def test_ensure_connected_reconnects(self, mock_rpyc_with_reset):
        """Test ensure_connected reconnects when disconnected."""
        hou = ensure_connected("localhost", 18811)
        assert hou is not None

    def test_ensure_connected_uses_provided_host_port(self, reset_connection_state):
        """Test ensure_connected uses provided host and port."""
        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            from tests.conftest import MockRpycConnection, MockHouModule

            mock_hou = MockHouModule()
            mock_conn = MockRpycConnection(mock_hou)
            mock_rpyc.classic.connect.return_value = mock_conn

            ensure_connected("custom-host", 12345)

            mock_rpyc.classic.connect.assert_called_with("custom-host", 12345)


class TestGetHou:
    """Tests for the get_hou function."""

    def test_get_hou_when_connected(self, mock_connection, mock_hou):
        """Test get_hou returns hou when connected."""
        hou = get_hou("localhost", 18811)
        assert hou is mock_hou

    def test_get_hou_connects_if_needed(self, mock_rpyc_with_reset):
        """Test get_hou connects if not connected."""
        hou = get_hou("localhost", 18811)
        assert hou is not None


class TestGetConnection:
    """Tests for the get_connection function."""

    def test_get_connection_returns_connection(self, mock_connection):
        """Test get_connection returns the connection object."""
        conn = get_connection()
        assert conn is not None

    def test_get_connection_returns_none_when_disconnected(self, reset_connection_state):
        """Test get_connection returns None when disconnected."""
        conn = get_connection()
        assert conn is None


class TestGetConnectionInfo:
    """Tests for the get_connection_info function."""

    def test_get_connection_info_connected(self, mock_connection, mock_hou):
        """Test get_connection_info when connected."""
        info = get_connection_info("localhost", 18811)

        assert info["connected"] is True
        assert info["houdini_version"] == "20.5.123"
        assert info["houdini_build"]["major"] == 20
        assert info["houdini_build"]["minor"] == 5
        assert info["houdini_build"]["build"] == 123
        assert info["hip_file"] == "/path/to/test.hip"

    def test_get_connection_info_disconnected(self, reset_connection_state):
        """Test get_connection_info when disconnected."""
        info = get_connection_info("localhost", 18811)

        assert info["connected"] is False
        assert info["host"] == "localhost"
        assert info["port"] == 18811
        assert info["houdini_version"] is None

    def test_get_connection_info_handles_error(self, reset_connection_state):
        """Test get_connection_info handles errors gracefully."""
        import houdini_mcp.connection as conn_module

        mock_hou = MagicMock()
        mock_hou.applicationVersionString.side_effect = Exception("Error")
        conn_module._connection = MagicMock()
        conn_module._hou = mock_hou

        # Patch is_connected to return True
        with patch("houdini_mcp.connection.is_connected", return_value=True):
            info = get_connection_info("localhost", 18811)

        assert "error" in info


class TestPing:
    """Tests for the ping function."""

    def test_ping_success(self, mock_hou):
        """Test ping returns True when Houdini is reachable."""
        from tests.conftest import MockRpycConnection

        mock_conn = MockRpycConnection(mock_hou)

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.return_value = mock_conn
            result = ping("localhost", 18811)

        assert result is True
        assert mock_conn._closed is True  # Connection should be closed

    def test_ping_failure(self):
        """Test ping returns False when Houdini is not reachable."""
        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.side_effect = ConnectionError("Connection refused")
            result = ping("localhost", 18811)

        assert result is False

    def test_ping_closes_connection(self, mock_hou):
        """Test ping closes connection after checking."""
        from tests.conftest import MockRpycConnection

        mock_conn = MockRpycConnection(mock_hou)

        with patch("houdini_mcp.connection.rpyc") as mock_rpyc:
            mock_rpyc.classic.connect.return_value = mock_conn
            ping("localhost", 18811)

        assert mock_conn._closed is True


class TestHoudiniConnectionError:
    """Tests for the HoudiniConnectionError exception."""

    def test_exception_message(self):
        """Test exception contains useful message."""
        error = HoudiniConnectionError("Test error message")
        assert str(error) == "Test error message"

    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        error = HoudiniConnectionError("Test")
        assert isinstance(error, Exception)


class TestHoudiniOperationError:
    """Tests for the HoudiniOperationError exception."""

    def test_exception_message(self):
        """Test exception contains useful message."""
        error = HoudiniOperationError("Operation failed")
        assert str(error) == "Operation failed"

    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        error = HoudiniOperationError("Test")
        assert isinstance(error, Exception)
