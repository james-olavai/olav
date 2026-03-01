"""Unit tests for src/olav/cli/admin.py."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from olav.cli.admin import admin_handler


@pytest.mark.asyncio
async def test_admin_handler_invalid_format():
    """Test admin_handler with invalid command format."""
    result = await admin_handler("invalid command")
    assert result["status"] == "error"
    assert "Invalid command format" in result["message"]


@pytest.mark.asyncio
async def test_admin_handler_unknown_command():
    """Test admin_handler with unknown command (routes to agent)."""
    with patch("olav.agents.agent.create_olav_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.invoke = AsyncMock(return_value={"status": "success", "response": "Agent response"})
        mock_create.return_value = mock_agent

        result = await admin_handler("/admin unknown_cmd")
        assert result["status"] == "success"
        assert result["response"] == "Agent response"
        mock_agent.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_fast_status():
    """Test /admin status command."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.glob", return_value=[]),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 1024 * 1024

        result = await admin_handler("/admin status")
        assert result["status"] == "success"
        assert "data" in result
        assert "databases" in result["data"]


@pytest.mark.asyncio
async def test_fast_db_info():
    """Test /admin db-info command."""
    with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.glob") as mock_glob:
        mock_file = MagicMock(spec=Path)
        mock_file.is_file.return_value = True
        mock_file.suffix = ".duckdb"
        mock_file.name = "main.duckdb"
        mock_file.stat.return_value.st_size = 1024 * 1024
        mock_file.stat.return_value.st_mtime = 1600000000
        mock_glob.return_value = [mock_file]

        result = await admin_handler("/admin db-info")
        assert result["status"] == "success"
        assert "main.duckdb" in result["databases"]


@pytest.mark.asyncio
async def test_fast_skill_list():
    """Test /admin skill-list command."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.iterdir") as mock_iterdir,
    ):
        mock_skill_dir = MagicMock(spec=Path)
        mock_skill_dir.is_dir.return_value = True
        mock_skill_dir.name = "test-skill"

        mock_skill_md = MagicMock(spec=Path)
        mock_skill_md.exists.return_value = True
        mock_skill_md.stat.return_value.st_size = 100

        mock_skill_dir.__truediv__.return_value = mock_skill_md
        mock_iterdir.return_value = [mock_skill_dir]

        result = await admin_handler("/admin skill-list")
        assert result["status"] == "success"
        assert len(result["agents"]) == 1
        assert result["agents"][0]["name"] == "test-skill"


@pytest.mark.asyncio
async def test_kb_status():
    """Test /admin kb-status command."""
    with (
        patch("importlib.util.spec_from_file_location"),
        patch("importlib.util.module_from_spec") as mock_mod_from_spec,
    ):
        mock_mod = MagicMock()
        mock_mod.get_kb_status.return_value = {"status": "ready", "total_chunks": 10}
        mock_mod_from_spec.return_value = mock_mod

        result = await admin_handler("/admin kb-status")
        assert result["status"] == "success"
        assert "ready" in result["message"]
        assert result["statistics"]["total_chunks"] == 10


@pytest.mark.asyncio
async def test_kb_index():
    """Test /admin kb-index command."""
    with (
        patch("importlib.util.spec_from_file_location"),
        patch("importlib.util.module_from_spec") as mock_mod_from_spec,
    ):
        mock_mod = MagicMock()
        mock_mod.index_knowledge_files.return_value = "Indexed 5 chunks from 2 files."
        mock_mod_from_spec.return_value = mock_mod

        result = await admin_handler("/admin kb-index")
        assert result["status"] == "success"
        assert "Indexed 5 chunks" in result["message"]


@pytest.mark.asyncio
async def test_kb_search_no_args():
    """Test /admin kb-search with no args."""
    result = await admin_handler("/admin kb-search")
    assert result["status"] == "error"
    assert "Usage:" in result["message"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_kb_search_success():
    """Test /admin kb-search success."""
    with (
        patch("olav.core.knowledge.get_knowledge_base") as mock_get_kb,
        patch("olav.core.memory.get_store") as mock_get_store,
    ):
        mock_store = MagicMock()
        mock_store.table_exists.return_value = True
        mock_get_store.return_value = mock_store

        mock_kb = MagicMock()
        mock_kb.search.return_value = [
            {
                "text": "test content",
                "metadata": '{"source_file": "test.md"}',
                "rrf_score": 0.95,
            }
        ]
        mock_get_kb.return_value = mock_kb

        result = await admin_handler("/admin kb-search 'test query'")
        assert result["status"] == "success"
        assert "test.md" in result["message"]
        assert result["results"] == 1

@pytest.mark.asyncio
async def test_admin_handler_fast_command_error():
    """Test admin_handler with fast command error."""
    with patch("olav.cli.admin._fast_status", side_effect=Exception("Fast error")):
        result = await admin_handler("/admin status")
        assert result["status"] == "error"
        assert "Fast error" in result["message"]

@pytest.mark.asyncio
async def test_admin_handler_agent_error():
    """Test admin_handler with agent error."""
    with patch("olav.agents.agent.create_olav_agent", side_effect=Exception("Agent error")):
        result = await admin_handler("/admin unknown_cmd")
        assert result["status"] == "error"
        assert "Agent error" in result["message"]

@pytest.mark.asyncio
async def test_fast_backup_with_files():
    """Test /admin backup command with files."""
    with patch("pathlib.Path.mkdir"), \
         patch("tarfile.open") as mock_tar_open, \
         patch("pathlib.Path.glob") as mock_glob, \
         patch("pathlib.Path.stat") as mock_stat:
        
        mock_file = MagicMock(spec=Path)
        mock_file.is_file.return_value = True
        mock_file.relative_to.return_value = Path("databases/main.duckdb")
        mock_glob.side_effect = [[mock_file], []] # .duckdb*, .db
        mock_stat.return_value.st_size = 1024 * 1024
        
        mock_tar = MagicMock()
        mock_tar_open.return_value.__enter__.return_value = mock_tar
        
        result = await admin_handler("/admin backup")
        assert result["status"] == "success"
        mock_tar.add.assert_called()

@pytest.mark.asyncio
async def test_fast_restore_errors():
    """Test /admin restore command errors."""
    # No args
    result = await admin_handler("/admin restore")
    assert result["status"] == "error"
    assert "Backup file path required" in result["message"]
    
    # File not found
    with patch("pathlib.Path.exists", return_value=False):
        result = await admin_handler("/admin restore nonexistent.tar.gz")
        assert result["status"] == "error"
        assert "Backup file not found" in result["message"]

@pytest.mark.asyncio
async def test_kb_search_db_not_found():
    """Test /admin kb-search when KB not indexed."""
    with (
        patch("olav.core.memory.get_store") as mock_get_store,
    ):
        mock_store = MagicMock()
        mock_store.table_exists.return_value = False
        mock_get_store.return_value = mock_store

        result = await admin_handler("/admin kb-search 'query'")
        assert result["status"] == "error"
        assert "Knowledge base not indexed" in result["message"]

@pytest.mark.asyncio
async def test_kb_index_value_error():
    """Test /admin kb-index with ValueError."""
    with patch("importlib.util.spec_from_file_location"), \
         patch("importlib.util.module_from_spec") as mock_mod_from_spec:
        mock_mod = MagicMock()
        mock_mod.index_knowledge_files.side_effect = ValueError("api_key not configured")
        mock_mod_from_spec.return_value = mock_mod
        
        result = await admin_handler("/admin kb-index")
        assert result["status"] == "error"
        assert "LLM API key not configured" in result["message"]

@pytest.mark.asyncio
async def test_fast_backup():
    """Test /admin backup command."""
    with patch("pathlib.Path.mkdir"), \
         patch("tarfile.open") as mock_tar_open, \
         patch("pathlib.Path.glob", return_value=[]), \
         patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 1024 * 1024
        
        result = await admin_handler("/admin backup")
        assert result["status"] == "success"
        assert "backup_file" in result
        mock_tar_open.assert_called_once()

@pytest.mark.asyncio
async def test_fast_restore():
    """Test /admin restore command."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.mkdir"), \
         patch("tarfile.open") as mock_tar_open, \
         patch("pathlib.Path.rglob", return_value=[]), \
         patch("shutil.rmtree"):
        
        result = await admin_handler("/admin restore some_backup.tar.gz")
        assert result["status"] == "success"
        assert result["message"] == "Restore completed"
        mock_tar_open.assert_called_once()

@pytest.mark.asyncio
async def test_fast_reload():
    """Test /admin reload command."""
    with patch("olav.core.command_registry.CommandRegistry.reload") as mock_reload:
        mock_reload.return_value = {
            "reloaded": {"templates": 5, "whitelisted_commands": 10, "blacklisted_patterns": 2},
            "new_templates": ["template1"],
            "errors": []
        }
        
        result = await admin_handler("/admin reload")
        assert result["status"] == "success"
        assert "Reloaded 5 templates" in result["message"]
        assert "template1" in result["message"]

@pytest.mark.asyncio
async def test_kb_reload():
    """Test /admin kb-reload command."""
    with patch("importlib.util.spec_from_file_location"), \
         patch("importlib.util.module_from_spec") as mock_mod_from_spec:
        mock_mod = MagicMock()
        mock_mod.index_knowledge_files.return_value = "Reloaded 10 chunks from 5 files."
        mock_mod_from_spec.return_value = mock_mod

        result = await admin_handler("/admin kb-reload")
        assert result["status"] == "success"
        assert "Reloaded 10 chunks" in result["message"]
