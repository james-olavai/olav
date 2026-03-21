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


from deepagents import create_deep_agent
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.duckdb import DuckDBSaver

from olav.core.config import settings
from olav.core.llm import LLMFactory
from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore
from olav.core.tool_discovery import discover_tools

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


def _inject_static_context(prompt: str, skill_dir: Path, metadata: dict) -> str:
    """Append static_context files to the system prompt.

    Reads the ``static_context:`` list from SKILL.md frontmatter and appends
    each referenced file to the prompt as a fenced context block.

    SKILL.md format::

        static_context:
          - path: ./references/ROUTING_EXPERT_GUIDE.md
          - path: ./references/BASELINE_SCHEMA.md

    Args:
        prompt: Base system prompt string.
        skill_dir: Directory containing the SKILL.md (used to resolve relative paths).
        metadata: Parsed SKILL.md frontmatter dict.

    Returns:
        Prompt with static context appended, or original prompt if no context.
    """
    static_ctx = metadata.get("static_context")
    if not static_ctx:
        return prompt

    appended: list[str] = []
    for entry in static_ctx:
        # Support both {path: ...} dict and bare string
        rel_path = entry.get("path", entry) if isinstance(entry, dict) else entry
        # Strip leading $ref: prefix if present
        rel_path = rel_path.removeprefix("$ref:")
        full_path = (skill_dir / rel_path).resolve()
        content = _read_prompt_file(full_path)
        if content:
            label = full_path.name
            appended.append(f"\n\n---\n## Reference: {label}\n\n{content.strip()}")
            logger.debug(f"  injected static_context: {label}")
        else:
            logger.warning(f"static_context file not found: {full_path}")

    if appended:
        logger.info(f"Injected {len(appended)} static_context file(s) from {skill_dir.name}")
        return prompt + "".join(appended)
    return prompt


def _resolve_env_ref(value: str) -> str:
    """Expand ``${ENV_VAR}`` references in a string against os.environ."""
    import os
    import re

    def _sub(m: re.Match) -> str:
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            raise RuntimeError(
                f"OLAV.md references env var ${{{var}}} but it is not set. "
                f"Set '{var}=<model-name>' via environment variable or .olav/config/api.json."
            )
        return val
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
        session_id: str | None = None,
    ):
        """Initialize OLAV Orchestrator Agent."""
        self.model_name = model_name or settings.llm_model_name
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.olav_base_path = Path(olav_base_path)
        self.agent_id = agent_id or "quick"
        self.session_id = session_id

        # LLM via LLMFactory
        self.llm = LLMFactory.get_chat_model(
            model_name=self.model_name,
            temperature=self.temperature,
            agent_id=self.agent_id,
        )
        logger.info(
            f"OLAV Orchestrator v3.4 initialized: "
            f"model={self.model_name}, temperature={self.temperature}, agent={self.agent_id}"
        )

        # LangChain LLM cache — SQLite (user-isolated in ~/.olav/cache/{user}/)
        from olav.core.config import USER_CACHE_DIR

        cache_path = USER_CACHE_DIR / "llm_cache.db"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            langchain.llm_cache = SQLiteCache(database_path=str(cache_path))
            logger.info(f"✓ LLM cache enabled: {cache_path}")
        except Exception as e:
            logger.warning(f"LLM cache init failed: {e}. Caching disabled.")

        # Checkpointer — AsyncDuckDBSaver: user-isolated, persistent, async-safe
        self.checkpointer = None
        if enable_checkpointer:
            try:
                import os

                from olav.core.checkpointer import create_checkpointer

                _user = os.environ.get("USER") or os.environ.get("USERNAME", "default_user")
                self.checkpointer = create_checkpointer(agent_id=self.agent_id, username=_user)
            except Exception as e:
                logger.warning(
                    f"AsyncDuckDBSaver init failed ({e}), no checkpoint support available"
                )

        # LanceDB long-term semantic memory store
        self.store = None
        try:
            db_path = self.olav_base_path / "databases" / "memory.lance"
            self.store = LangGraphLanceDBStore(db_path=str(db_path))
            logger.info(f"✓ Long-term memory store initialized (LanceDB): {db_path}")
        except Exception as e:
            logger.warning(f"LanceDBStore init failed: {e}. Long-term memory disabled.")
            self.store = None

        # Build agent graph
        olav_config = self._load_olav_config()

        # MANIFEST injection: discover workspace-declared Skills/Agents and
        # merge any that target this agent_id into olav_config before building
        # subagents.  AGENT.md explicit declarations always take priority.
        try:
            from olav.core.agent_registry import discover_agents, merge_into_config

            _manifests = discover_agents(self.olav_base_path / "workspace")
            olav_config = merge_into_config(olav_config, _manifests, self.agent_id)
        except Exception as _e:
            logger.warning("MANIFEST discovery failed (non-fatal): %s", _e)

        subagents = self._build_subagents(olav_config)
        orchestrator_tools = self._load_orchestrator_tools(olav_config)
        logger.info(
            f"✓ Orchestrator tools ({len(orchestrator_tools)}): "
            f"{[t.name for t in orchestrator_tools]}"
        )

        # 插件扣前加载 — 键入 create_deep_agent middleware + callbacks
        from olav.plugins import load_builtin_plugins, load_external_plugins
        from olav.plugins.registry import PluginRegistry

        _disabled = []
        try:
            _disabled = list(olav_config.get("plugins", {}).get("disabled", []))
        except Exception:
            pass
        self.plugin_registry = PluginRegistry(disabled=_disabled)
        load_builtin_plugins(self.plugin_registry)
        load_external_plugins(self.plugin_registry)
        logger.info(
            f"✓ Plugin registry: "
            f"{len(self.plugin_registry.get_middleware_plugins())} middleware, "
            f"{len(self.plugin_registry.get_callback_plugins())} callbacks"
        )

        self.graph = create_deep_agent(
            model=self.llm,
            tools=orchestrator_tools,
            system_prompt=self._get_orchestrator_prompt(olav_config),
            checkpointer=self.checkpointer,
            store=self.store,
            subagents=subagents,
            middleware=self.plugin_registry.get_middleware_plugins(),
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
                _frontmatter.load(f)
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

    def _build_subagents(self, olav_config: dict) -> list[SubAgent | CompiledSubAgent]:
        """Build SubAgents from workspace/AGENT.md config.

        Workspace subagents that declare custom tools are pre-compiled as
        ``CompiledSubAgent`` so that ``create_deep_agent`` uses the runnable
        as-is and does NOT inject ``FilesystemMiddleware`` into them.  Plain
        ``SubAgent`` dicts (no tools) still go through the normal stack.
        """
        subagent_paths = olav_config.get("subagents") or []
        if not subagent_paths:
            logger.info("No subagents defined in AGENT.md")
            return []

        subagents: list[SubAgent | CompiledSubAgent] = []
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

            # Inject static_context references declared in SKILL.md
            prompt = _inject_static_context(prompt, sa_dir, metadata)

            logger.info(f"✓ SubAgent '{name}' ({len(tools)} tools): {[t.name for t in tools]}")

            if tools:
                # Pre-compile with a minimal middleware stack (TodoList only) so
                # that create_deep_agent cannot inject FilesystemMiddleware.  This
                # prevents the subagent from using ls/glob/grep instead of its
                # declared domain tools.
                runnable = create_agent(
                    self.llm,
                    system_prompt=prompt,
                    tools=tools,
                    middleware=[TodoListMiddleware()],
                    name=name,
                )
                subagents.append(
                    {
                        "name": name,
                        "description": description,
                        "runnable": runnable,
                    }
                )
            else:
                subagents.append(
                    {
                        "name": name,
                        "description": description,
                        "system_prompt": prompt,
                        "tools": [],
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
            # Inject static_context references declared in AGENT.md frontmatter
            prompt = _inject_static_context(prompt, self._agent_dir, olav_config)
            logger.info(f"Loaded system prompt from {prompt_file}")
            return prompt

        return olav_config.get("description", "You are OLAV, an AI operations assistant.")

    # ------------------------------------------------------------------
    # Invoke methods (interface for backwards compatibility)
    # ------------------------------------------------------------------

    async def ainvoke(self, input_: str | dict, thread_id: str | None = None, **kwargs) -> dict:
        """Async invoke the agent graph."""
        if isinstance(input_, str):
            input_ = {"messages": [{"role": "user", "content": input_}]}

        config: dict = {"callbacks": self.plugin_registry.get_callback_plugins()}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        try:
            result = await self.graph.ainvoke(input_, config=config, **kwargs)
        except Exception as e:
            logger.error(f"ainvoke failed: {e}")
            return {"status": "error", "response": str(e)}

        return result

    async def invoke(self, input_: str | dict, thread_id: str | None = None, **kwargs) -> dict:
        """Sync invoke (calls async version via asyncio)."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context, use ainvoke directly
                return await self.ainvoke(input_, thread_id, **kwargs)
        except RuntimeError:
            pass

        # Sync context: create new loop
        return asyncio.run(self.ainvoke(input_, thread_id, **kwargs))

    async def close(self) -> None:
        """Release resources (DuckDB connection, etc.)."""
        try:
            from olav.core.checkpointer import AsyncDuckDBSaver

            if isinstance(self.checkpointer, AsyncDuckDBSaver):
                self.checkpointer.conn.close()
                logger.debug("Checkpointer DuckDB connection closed.")
        except Exception as e:
            logger.debug(f"close(): {e}")


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
