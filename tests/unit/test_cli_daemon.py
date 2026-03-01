"""Unit tests for src/olav/cli/daemon.py."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json
import os
import sys
from pathlib import Path

# Mock missing modules before importing daemon
mock_router = MagicMock()
sys.modules["olav.core.semantic_router"] = mock_router

from src.olav.cli.daemon import DaemonServer, query_daemon, get_daemon_status, stop_daemon, spawn_daemon

class TestDaemonServer:
    """Tests for DaemonServer class."""
    
    def test_init(self):
        """Test initialization."""
        server = DaemonServer()
        assert server._agent is None
        assert server._query_count == 0

    @pytest.mark.asyncio
    async def test_ensure_agent(self):
        """Test lazy agent initialization."""
        server = DaemonServer()
        with patch("olav.agents.agent.create_olav_agent") as mock_create:
            mock_agent = MagicMock()
            mock_create.return_value = mock_agent
            
            agent = await server._ensure_agent()
            assert agent == mock_agent
            mock_create.assert_called_once()
            
            # Second call should not re-initialize
            await server._ensure_agent()
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_connection_empty_query(self):
        """Test handling connection with empty query."""
        server = DaemonServer()
        mock_reader = AsyncMock()
        mock_reader.readline.return_value = b'{"query": ""}\n'
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        
        await server._handle_connection(mock_reader, mock_writer)
        
        # Check that error response was written
        args, _ = mock_writer.write.call_args
        response = json.loads(args[0].decode())
        assert response["status"] == "error"
        assert response["message"] == "Empty query"

    @pytest.mark.asyncio
    async def test_handle_connection_success(self):
        """Test handling connection successfully."""
        server = DaemonServer()
        mock_reader = AsyncMock()
        mock_reader.readline.return_value = b'{"query": "test"}\n'
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        
        with patch.object(server, "_ensure_agent", new_callable=AsyncMock) as mock_ensure:
            mock_agent = MagicMock()
            mock_agent.invoke = AsyncMock(return_value={"status": "success", "response": "OK"})
            mock_ensure.return_value = mock_agent
            
            # Mock SemanticRouter to miss
            with patch("olav.core.semantic_router.SemanticRouter") as mock_router_class:
                mock_router_inst = mock_router_class.return_value
                mock_router_inst.route_and_execute = AsyncMock(return_value=None)
                
                await server._handle_connection(mock_reader, mock_writer)
        
        args, _ = mock_writer.write.call_args
        response = json.loads(args[0].decode())
        assert response["status"] == "success"
        assert response["response"] == "OK"

    @pytest.mark.asyncio
    async def test_run(self):
        """Test DaemonServer.run."""
        server = DaemonServer()
        with patch("asyncio.start_unix_server", new_callable=AsyncMock) as mock_start, \
             patch("src.olav.cli.daemon._PID_FILE") as mock_pid_file, \
             patch.object(server, "_ensure_agent", new_callable=AsyncMock), \
             patch.object(server, "_write_stats"):
            
            mock_start.return_value.__aenter__.return_value = MagicMock()
            
            # Mock stop_event.wait() to return immediately
            with patch("asyncio.Event.wait", new_callable=AsyncMock):
                with patch("signal.signal"):
                    await server.run()
                    mock_start.assert_called_once()
                    mock_pid_file.write_text.assert_called()

@pytest.mark.asyncio
async def test_query_daemon_no_socket():
    """Test query_daemon when socket doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        result = await query_daemon("test")
        assert result is None

def test_get_daemon_status_not_running():
    """Test get_daemon_status when not running."""
    with patch("src.olav.cli.daemon._PID_FILE") as mock_pid_file:
        mock_pid_file.exists.return_value = False
        status = get_daemon_status()
        assert status["running"] is False

def test_get_daemon_status_running():
    """Test get_daemon_status when running."""
    with patch("src.olav.cli.daemon._PID_FILE") as mock_pid_file, \
         patch("os.kill", return_value=None), \
         patch("src.olav.cli.daemon._STATS_FILE") as mock_stats_file:
        
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "1234"
        
        mock_stats_file.exists.return_value = True
        mock_stats_file.read_text.return_value = '{"query_count": 5}'
        
        status = get_daemon_status()
        assert status["running"] is True
        assert status["pid"] == 1234
        assert status["query_count"] == 5

def test_stop_daemon():
    """Test stop_daemon."""
    with patch("src.olav.cli.daemon._PID_FILE") as mock_pid_file, \
         patch("os.kill") as mock_kill:
        
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "1234"
        
        assert stop_daemon() is True
        mock_kill.assert_called_with(1234, 15) # SIGTERM is 15

def test_spawn_daemon():
    """Test spawn_daemon."""
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.pid = 5678
        pid = spawn_daemon()
        assert pid == 5678
        mock_popen.assert_called_once()
