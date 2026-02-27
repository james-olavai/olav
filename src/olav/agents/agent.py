#!/usr/bin/env python3
"""
OLAV Orchestrator Agent - v3.4 (DeepAgents + SubAgents)

Architecture:
- OLAVAgent: pure orchestrator with format_and_export only
- olav-ops SubAgent: execute_sql, execute_cli, search_knowledge, format_and_export
- olav-config SubAgent: sync_schemas, sync_inventory, take_snapshot, sync_commands, manage_cron
- LangChain SQLiteCache for LLM caching
- LangGraph MemorySaver for checkpoint/persistence
- LanceDB (via langgraph_adapter) for long-term semantic memory

Replaces: LangGraph StateGraph + flat tool list (agent.py v3.2)
"""

import logging
from pathlib import Path

import langchain
from langchain_community.cache import SQLiteCache
from langgraph.checkpoint.memory import MemorySaver
"""
OLAV Orchestrator Agent - v3.4 (DeepAgents + SubAgents)

Architecture:
- OLAVAgent: pure orchestrator with format_and_export only
- olav-ops SubAgent: execute_sql, execute_cli, search_knowledge, format_and_export
- olav-config SubAgent: sync_schemas, sync_inventory, take_snapshot, sync_commands, manage_cron
- LangChain SQLiteCache for LLM caching
- LangGraph DuckDBSaver for checkpoint/persistence (persistent across restarts)
- LanceDB (via langgraph_adapter) for long-term semantic memory

Replaces: LangGraph StateGraph + flat tool list (agent.py v3.2)
"""

import logging
from pathlib import Path

import langchain
from langchain_community.cache import SQLiteCache
from langgraph.checkpoint.duckdb import DuckDBSaver
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent

from olav.core.config import settings
from olav.core.llm import LLMFactory
from olav.core.tool_discovery import discover_tools
from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore

try:
    import frontmatter as _frontmatter

    _HAS_FRONTMATTER = True
except ImportError:
    _HAS_FRONTMATTER = False

logger = logging.getLogger(__name__)


def _read_prompt_file(path: Path) -> str | None:
    """Read a prompt file, returning None if missing or unreadable."""
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read prompt {path}: {e}")
    return None


def _resolve_env_ref(value: str) -> str:
    """Expand ``${ENV_VAR}`` references in a string against os.environ."""
    import os, re

    def _sub(m: re.Match) -> str:
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            raise RuntimeError(
                f"OLAV.md references env var ${{{var}}} but it is not set. "
                f"Add '{var}=<model-name>' to your .env file."
            )
        return val

    return re.sub(r"\$\{([^}]+)\}", _sub, value)


class OLAVAgent:
    """OLAV orchestrator powered by DeepAgents + SubAgents."""

    def __init__(
        self,
        model_name: str | None = None,
        temperature: float | None = None,
        olav_base_path: str = ".olav",
        enable_checkpointer: bool = True,
        agent_id: str | None = None,
    ):
        """Initialize OLAV Orchestrator Agent."""
        self.model_name = model_name or settings.llm_model_name
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.olav_base_path = Path(olav_base_path)
        self.agent_id = agent_id or "quick"

        # LLM via LLMFactory
        self.llm = LLMFactory.get_chat_model(temperature=self.temperature)
        logger.info(
            f"OLAV Orchestrator v3.4 initialized: provider={settings.llm_provider}, "
            f"model={self.model_name}, temperature={self.temperature}"
        )

        # LangChain LLM cache — SQLite
        cache_path = self.olav_base_path / "databases" / "llm_cache.db"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            langchain.llm_cache = SQLiteCache(database_path=str(cache_path))
            logger.info(f"✓ LLM cache enabled: {cache_path}")
        except Exception as e:
            logger.warning(f"LLM cache init failed: {e}. Caching disabled.")

        # Checkpointer — using MemorySaver (DuckDBSaver has async issues in LangGraph 1.0)
        self.checkpointer = None
        if enable_checkpointer:
            try:
                from langgraph.checkpoint.memory import MemorySaver
                self.checkpointer = MemorySaver()
                logger.info("✓ Checkpointer initialized (MemorySaver)")
            except Exception as e:
                logger.warning(f"MemorySaver init failed: {e}. No checkpoint.")

        # LanceDB long-term semantic memory store
        self.store = None
        try:
            db_path = self.olav_base_path / "databases" / "memory.lancedb"
            self.store = LangGraphLanceDBStore(db_path=str(db_path))
            logger.info(f"✓ Long-term memory store initialized (LanceDB): {db_path}")
        except Exception as e:
            logger.warning(f"LanceDBStore init failed: {e}. Long-term memory disabled.")
            self.store = None

        # Build agent graph
        olav_config = self._load_olav_config()
        subagents = self._build_subagents(olav_config)
        orchestrator_tools = self._load_orchestrator_tools(olav_config)
        logger.info(
            f"✓ Orchestrator tools ({len(orchestrator_tools)}): "
            f"{[t.name for t in orchestrator_tools]}"
        )

        self.graph = create_deep_agent(
            model=self.llm,
            tools=orchestrator_tools,
            system_prompt=self._get_orchestrator_prompt(olav_config),
            checkpointer=self.checkpointer,
            store=self.store,
            subagents=subagents,
        )

    # ------------------------------------------------------------------
    # Tool loading helpers
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Workspace AGENT.md config loading
    # ------------------------------------------------------------------

    def _load_olav_config(self) -> dict:
        """Load workspace/AGENT.md YAML frontmatter."""
        workspace_path = self.olav_base_path / "workspace"
        agent_dir = workspace_path / self.agent_id
        agent_md = agent_dir / "AGENT.md"

        if not agent_md.exists():
            raise RuntimeError(
                f"AGENT.md not found at {agent_md}. "
                f"Workspace agent '{self.agent_id}' does not exist."
            )

        if not _HAS_FRONTMATTER:
            raise RuntimeError(
                "python-frontmatter is not installed. Run: uv add python-frontmatter"
            )

        try:
            with open(agent_md, encoding="utf-8") as f:
                post = _frontmatter.load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to parse AGENT.md: {e}") from e

        if not post.metadata:
            raise RuntimeError("AGENT.md has no YAML frontmatter.")

        logger.info(f"✓ AGENT.md config loaded: {list(post.metadata.keys())}")
        self._agent_dir = agent_dir
        return post.metadata

    def _load_orchestrator_tools(self, olav_config: dict) -> list:
        """Load tools from AGENT.md."""
        skill_path = self._agent_dir / "SKILL.md"
        if skill_path.exists():
            return self._load_tools_from_skill(skill_path)
        logger.info("No SKILL.md found, using subagents only")
        return []

    def _load_tools_from_skill(self, skill_path: Path) -> list:
        """Load tools from a SKILL.md file."""
        try:
            with open(skill_path, encoding="utf-8") as f:
                post = _frontmatter.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse SKILL.md {skill_path}: {e}")
            return []

        tools_dir = skill_path.parent / "tools"
        if tools_dir.is_dir():
            return discover_tools(tools_dir)
        return []

    # ------------------------------------------------------------------
    # SubAgent construction
    # ------------------------------------------------------------------

    def _build_subagents(self, olav_config: dict) -> list[SubAgent]:
        """Build SubAgents from workspace/AGENT.md config."""
        subagent_paths = olav_config.get("subagents") or []
        if not subagent_paths:
            logger.info("No subagents defined in AGENT.md")
            return []

        subagents: list[SubAgent] = []
        for sa_path in subagent_paths:
            if isinstance(sa_path, dict):
                sa_path = sa_path.get("path", "")

            sa_full_path = self._agent_dir / sa_path
            sa_dir = sa_full_path.parent
            sa_name = sa_dir.name

            skill_md = sa_full_path
            if not skill_md.exists():
                logger.warning(f"Subagent SKILL.md not found: {skill_md}")
                continue

            try:
                with open(skill_md, encoding="utf-8") as f:
                    post = _frontmatter.load(f)
            except Exception as e:
                logger.warning(f"Failed to parse {skill_md}: {e}")
                continue

            metadata = post.metadata or {}
            name = metadata.get("name", sa_name)
            description = metadata.get("description", f"SubAgent: {sa_name}")

            tools_dir = sa_dir / "tools"
            tools = []
            if tools_dir.is_dir():
                tools = discover_tools(tools_dir)

            prompt_file = metadata.get("system_prompt_file", "prompts/system.md")
            prompt_path = sa_dir / prompt_file
            prompt = _read_prompt_file(prompt_path)
            if not prompt:
                prompt = f"You are the {name} agent."

            logger.info(f"✓ SubAgent '{name}' ({len(tools)} tools): {[t.name for t in tools]}")

            subagents.append(
                {
                    "name": name,
                    "description": description,
                    "system_prompt": prompt,
                    "tools": tools,
                }
            )

        return subagents

    def _get_orchestrator_prompt(self, olav_config: dict) -> str:
        """Get the system prompt for the orchestrator."""
        prompt_file = self._agent_dir / "prompts" / "system.md"
        prompt = _read_prompt_file(prompt_file)

        if prompt:
            try:
                prompt = _resolve_env_ref(prompt)
            except RuntimeError as e:
                logger.warning(f"Failed to resolve env vars in prompt: {e}")
            logger.info(f"Loaded system prompt from {prompt_file}")
            return prompt

        return olav_config.get("description", "You are OLAV, a network operations AI assistant.")


def create_olav_agent(
    model_name: str | None = None,
    temperature: float | None = None,
    olav_base_path: str = ".olav",
    enable_checkpointer: bool = True,
    agent_id: str | None = None,
) -> OLAVAgent:
    """Factory function to create an OLAV agent."""
    return OLAVAgent(
        model_name=model_name,
        temperature=temperature,
        olav_base_path=olav_base_path,
        enable_checkpointer=enable_checkpointer,
        agent_id=agent_id,
    )
