"""Unit tests for src/olav/agents/agent.py."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from olav.agents.agent import OLAVAgent, create_olav_agent, _read_prompt_file, _resolve_env_ref

@pytest.fixture
def mock_config(tmp_path):
    """Create a minimal workspace structure for OLAVAgent.

    OLAVAgent expects: {base}/.olav/workspace/quick/AGENT.md
    The old OLAV.md-based fixture was replaced in v0.10.0.
    """
    olav_dir = tmp_path / ".olav"
    agent_dir = olav_dir / "workspace" / "quick"
    (agent_dir / "prompts").mkdir(parents=True)
    (olav_dir / "databases").mkdir(parents=True)

    (agent_dir / "AGENT.md").write_text("""\
---
name: quick-orchestrator
description: "Test Quick Agent"
system_prompt_file: prompts/system.md
subagents: []
---
Test agent body.
""")
    (agent_dir / "prompts" / "system.md").write_text("You are a test orchestrator.")

    return olav_dir

def test_read_prompt_file(tmp_path):
    """Test _read_prompt_file."""
    test_file = tmp_path / "prompt.md"
    test_file.write_text("Hello Prompt")
    assert _read_prompt_file(test_file) == "Hello Prompt"
    
    assert _read_prompt_file(tmp_path / "nonexistent.md") is None

def test_resolve_env_ref():
    """Test _resolve_env_ref."""
    with patch("os.environ.get", return_value="gpt-4"):
        assert _resolve_env_ref("${MODEL_NAME}") == "gpt-4"
    
    assert _resolve_env_ref("literal-model") == "literal-model"
    
    with patch("os.environ.get", return_value=None):
        with pytest.raises(RuntimeError):
            _resolve_env_ref("${MISSING_VAR}")

class TestOLAVAgent:
    """Tests for OLAVAgent class."""
    
    def test_init(self, mock_config):
        """Test initialization."""
        with patch("olav.agents.agent.LLMFactory.get_chat_model"), \
             patch("olav.agents.agent.discover_tools", return_value=[]), \
             patch("olav.agents.agent.create_deep_agent") as mock_create:
            
            agent = OLAVAgent(olav_base_path=str(mock_config), enable_checkpointer=False)
            assert agent.olav_base_path == mock_config
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke(self, mock_config):
        """Test invoke method."""
        with patch("olav.agents.agent.LLMFactory.get_chat_model"), \
             patch("olav.agents.agent.discover_tools", return_value=[]), \
             patch("olav.agents.agent.create_deep_agent") as mock_create:

            mock_graph = MagicMock()
            mock_graph.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="Response")]})
            mock_create.return_value = mock_graph

            agent = OLAVAgent(olav_base_path=str(mock_config), enable_checkpointer=False)
            result = await agent.ainvoke("Hello")

            # ainvoke returns raw graph result
            assert "messages" in result

    @pytest.mark.asyncio
    async def test_close(self, mock_config):
        """Test close method completes without error."""
        with patch("olav.agents.agent.LLMFactory.get_chat_model"), \
             patch("olav.agents.agent.discover_tools", return_value=[]), \
             patch("olav.agents.agent.create_deep_agent"):

            agent = OLAVAgent(olav_base_path=str(mock_config), enable_checkpointer=False)
            await agent.close()  # Should not raise

    def test_load_tools_for_skills(self, mock_config):
        """Test that orchestrator tools can be loaded (no SKILL.md → empty list)."""
        with patch("olav.agents.agent.LLMFactory.get_chat_model"), \
             patch("olav.agents.agent.discover_tools", return_value=[]), \
             patch("olav.agents.agent.create_deep_agent"):

            agent = OLAVAgent(olav_base_path=str(mock_config), enable_checkpointer=False)
            # No SKILL.md in fixture → _load_orchestrator_tools returns []
            tools = agent._load_orchestrator_tools({})
            assert isinstance(tools, list)

    def test_init_llm_cache_error(self, mock_config):
        """Test that LLM cache errors are handled gracefully."""
        with patch("olav.agents.agent.LLMFactory.get_chat_model"), \
             patch("olav.agents.agent.discover_tools", return_value=[]), \
             patch("olav.agents.agent.create_deep_agent"), \
             patch("olav.agents.agent.SQLiteCache", side_effect=Exception("Cache error")):

            # Should not raise exception, just log warning
            OLAVAgent(olav_base_path=str(mock_config), enable_checkpointer=False)

def test_create_olav_agent():
    """Test create_olav_agent factory function."""
    with patch("olav.agents.agent.OLAVAgent") as mock_agent_class:
        create_olav_agent(model_name="test")
        mock_agent_class.assert_called_once()
        assert mock_agent_class.call_args.kwargs.get("model_name") == "test"


def test_load_olav_config_missing(tmp_path):
    """Test _load_olav_config when AGENT.md is missing."""
    (tmp_path / "databases").mkdir()
    with patch("olav.agents.agent.LLMFactory.get_chat_model"), \
         patch("olav.agents.agent.discover_tools", return_value=[]), \
         patch("olav.agents.agent.create_deep_agent"):
        with pytest.raises(RuntimeError, match="AGENT.md not found"):
            OLAVAgent(olav_base_path=str(tmp_path), enable_checkpointer=False)


def test_build_subagents_no_subagents(mock_config):
    """Test _build_subagents with empty subagents list returns []."""
    with patch("olav.agents.agent.LLMFactory.get_chat_model"), \
         patch("olav.agents.agent.discover_tools", return_value=[]), \
         patch("olav.agents.agent.create_deep_agent"):
        agent = OLAVAgent(olav_base_path=str(mock_config), enable_checkpointer=False)
        result = agent._build_subagents({"subagents": []})
        assert result == []
