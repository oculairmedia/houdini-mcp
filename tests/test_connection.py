"""Tests for the Houdini connection manager."""

import pytest
from unittest.mock import MagicMock, patch

from houdini_mcp.connection import (
    HoudiniConnectionError,
    connect,
    disconnect,
    is_connected,
    ensure_connected,
    get_connection_info,
    ping
)


class TestConnect:
    """Tests for the connect function."""
    
    def test_connect_success(self, mock_hrpyc):
        """Test successful connection to Houdini."""
        # Reset global state
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        connection, hou = connect("localhost", 18811)
        
        assert connection is not None
        assert hou is not None
        assert hou.applicationVersionString() == "20.5.123"
    
    def test_connect_with_retry(self, mock_hou):
        """Test connection retry logic."""
        mock_conn = MagicMock()
        mock_hrpyc_module = MagicMock()
        
        # First call fails, second succeeds
        call_count = [0]
        def mock_import(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Connection refused")
            return (mock_conn, mock_hou)
        
        mock_hrpyc_module.import_remote_module = mock_import
        
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        with patch.dict('sys.modules', {'hrpyc': mock_hrpyc_module}):
            connection, hou = connect("localhost", 18811, max_retries=3, retry_delay=0.01)
        
        assert call_count[0] == 2  # Failed once, succeeded on retry
        assert hou is not None
    
    def test_connect_all_retries_fail(self, mock_hou):
        """Test connection failure after all retries exhausted."""
        mock_hrpyc_module = MagicMock()
        mock_hrpyc_module.import_remote_module = MagicMock(
            side_effect=ConnectionError("Connection refused")
        )
        
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        with patch.dict('sys.modules', {'hrpyc': mock_hrpyc_module}):
            with pytest.raises(HoudiniConnectionError) as exc_info:
                connect("localhost", 18811, max_retries=2, retry_delay=0.01)
        
        assert "Failed to connect" in str(exc_info.value)
        assert "after 2 attempts" in str(exc_info.value)
    
    def test_connect_hrpyc_not_installed(self):
        """Test error when hrpyc is not installed."""
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        # Remove hrpyc from sys.modules to simulate it not being installed
        with patch.dict('sys.modules', {'hrpyc': None}):
            with pytest.raises(HoudiniConnectionError) as exc_info:
                connect("localhost", 18811)
        
        assert "hrpyc not available" in str(exc_info.value)


class TestIsConnected:
    """Tests for the is_connected function."""
    
    def test_is_connected_true(self, mock_connection):
        """Test is_connected returns True when connected."""
        result = is_connected()
        assert result is True
    
    def test_is_connected_false_no_connection(self):
        """Test is_connected returns False when no connection."""
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        result = is_connected()
        assert result is False
    
    def test_is_connected_false_dead_connection(self, mock_hou):
        """Test is_connected returns False when connection is dead."""
        import houdini_mcp.connection as conn_module
        
        # Set up a connection that will fail validation
        mock_hou.applicationVersion = MagicMock(side_effect=ConnectionError("Dead"))
        conn_module._connection = MagicMock()
        conn_module._hou = mock_hou
        
        result = is_connected()
        
        assert result is False
        assert conn_module._connection is None
        assert conn_module._hou is None


class TestDisconnect:
    """Tests for the disconnect function."""
    
    def test_disconnect_success(self, mock_connection):
        """Test successful disconnection."""
        import houdini_mcp.connection as conn_module
        
        disconnect()
        
        assert conn_module._connection is None
        assert conn_module._hou is None
    
    def test_disconnect_handles_error(self):
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


class TestEnsureConnected:
    """Tests for the ensure_connected function."""
    
    def test_ensure_connected_already_connected(self, mock_connection):
        """Test ensure_connected returns hou when already connected."""
        hou = ensure_connected("localhost", 18811)
        assert hou is not None
        assert hou.applicationVersionString() == "20.5.123"
    
    def test_ensure_connected_reconnects(self, mock_hrpyc):
        """Test ensure_connected reconnects when disconnected."""
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        hou = ensure_connected("localhost", 18811)
        
        assert hou is not None


class TestGetConnectionInfo:
    """Tests for the get_connection_info function."""
    
    def test_get_connection_info_connected(self, mock_connection):
        """Test get_connection_info when connected."""
        info = get_connection_info("localhost", 18811)
        
        assert info["connected"] is True
        assert info["houdini_version"] == "20.5.123"
        assert info["houdini_build"]["major"] == 20
        assert info["houdini_build"]["minor"] == 5
        assert info["houdini_build"]["build"] == 123
    
    def test_get_connection_info_disconnected(self):
        """Test get_connection_info when disconnected."""
        import houdini_mcp.connection as conn_module
        conn_module._connection = None
        conn_module._hou = None
        
        info = get_connection_info("localhost", 18811)
        
        assert info["connected"] is False
        assert info["host"] == "localhost"
        assert info["port"] == 18811


class TestPing:
    """Tests for the ping function."""
    
    def test_ping_success(self, mock_hou):
        """Test ping returns True when Houdini is reachable."""
        mock_conn = MagicMock()
        mock_hrpyc_module = MagicMock()
        mock_hrpyc_module.import_remote_module = MagicMock(return_value=(mock_conn, mock_hou))
        
        with patch.dict('sys.modules', {'hrpyc': mock_hrpyc_module}):
            result = ping("localhost", 18811)
        
        assert result is True
        mock_conn.close.assert_called_once()
    
    def test_ping_failure(self):
        """Test ping returns False when Houdini is not reachable."""
        mock_hrpyc_module = MagicMock()
        mock_hrpyc_module.import_remote_module = MagicMock(
            side_effect=ConnectionError("Connection refused")
        )
        
        with patch.dict('sys.modules', {'hrpyc': mock_hrpyc_module}):
            result = ping("localhost", 18811)
        
        assert result is False
