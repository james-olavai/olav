#!/usr/bin/env python3
"""
OLAV Orchestrator Agent - v3.4 (DeepAgents + SubAgents)

Architecture:
- OLAVAgent: pure orchestrator with format_and_export only
- olav-ops SubAgent: execute_sql, execute_cli, search_knowledge, format_and_export
- olav-config SubAgent: sync_schemas, sync_inventory, take_snapshot, sync_commands, manage_cron
- LangChain SQLiteCache for fast repeated query routing

Replaces: LangGraph StateGraph + flat tool list (agent.py v3.2)
"""

import logging
from pathlib import Path

import langchain
from langchain_community.cache import SQLiteCache
from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.store.duckdb import DuckDBStore
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent

from config.settings import settings
from olav.core.llm import LLMFactory
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


def _resolve_env_ref(value: str) -> str:
    """Expand ``${ENV_VAR}`` references in a string against os.environ.

    Example::

        _resolve_env_ref("${OLAV_INSPECTION_MODEL}")  # → value of env var
        _resolve_env_ref("claude-opus-4-5")           # → unchanged

    Raises:
        RuntimeError: If the referenced env var is not set.
    """
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
    ):
        """Initialize OLAV Orchestrator Agent.

        Args:
            model_name: LLM model (defaults to settings.llm_model_name)
            temperature: LLM temperature (defaults to settings.llm_temperature)
            olav_base_path: Path to .olav directory
            enable_checkpointer: Enable DuckDB conversation state persistence
        """
        self.model_name = model_name or settings.llm_model_name
        self.temperature = (
            temperature if temperature is not None else settings.llm_temperature
        )
        self.olav_base_path = Path(olav_base_path)

        # LLM via LLMFactory (supports OpenRouter, Groq, custom endpoints)
        self.llm = LLMFactory.get_chat_model(temperature=self.temperature)
        logger.info(
            f"OLAV Orchestrator v3.3 initialized: provider={settings.llm_provider}, "
            f"model={self.model_name}, temperature={self.temperature}"
        )

        # LangChain LLM cache — SQLite, speeds up identical repeated queries
        cache_path = self.olav_base_path / "databases" / "llm_cache.db"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            langchain.llm_cache = SQLiteCache(database_path=str(cache_path))
            logger.info(f"✓ LLM cache enabled: {cache_path}")
        except Exception as e:
            logger.warning(f"LLM cache init failed: {e}. Caching disabled.")

        # DuckDB checkpointer — short-term conversation memory
        self.checkpointer = None
        if enable_checkpointer:
            db_path = self.olav_base_path / "databases" / "agent.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                import duckdb
                conn = duckdb.connect(str(db_path))
                self.checkpointer = DuckDBSaver(conn=conn)
                logger.info("✓ Checkpointer initialized (DuckDBSaver)")
            except Exception as e:
                logger.warning(f"DuckDBSaver init failed: {e}. Memory only.")

        # DuckDB long-term memory store — cross-thread persistent
        self.store = None
        try:
            store_path = self.olav_base_path / "databases" / "memory_store.duckdb"
            store_path.parent.mkdir(parents=True, exist_ok=True)
            import duckdb as _ddb
            _store_conn = _ddb.connect(str(store_path))
            self.store = DuckDBStore(_store_conn)

            # Workaround: DuckDBStore.setup() uses row["v"] but DuckDB returns tuples
            import types

            def _patched_setup(self_store: DuckDBStore) -> None:
                import duckdb as _ddb2
                with self_store.conn.cursor() as cur:
                    try:
                        cur.execute(
                            "SELECT v FROM store_migrations ORDER BY v DESC LIMIT 1"
                        )
                        row = cur.fetchone()
                        version = row[0] if row is not None else -1
                    except _ddb2.CatalogException:
                        version = -1
                        cur.execute(
                            "CREATE TABLE IF NOT EXISTS store_migrations "
                            "(v INTEGER PRIMARY KEY)"
                        )
                    for v, migration in enumerate(
                        self_store.MIGRATIONS[version + 1 :], start=version + 1
                    ):
                        cur.execute(migration)
                        cur.execute(
                            "INSERT INTO store_migrations (v) VALUES (?)", (v,)
                        )

            self.store.setup = types.MethodType(_patched_setup, self.store)
            self.store.setup()
            logger.info("✓ Long-term memory store initialized (DuckDBStore)")
        except Exception as e:
            logger.warning(
                f"DuckDBStore init failed: {e}. Long-term memory disabled."
            )
            self.store = None

        # Build SubAgents and orchestrator graph (config driven from OLAV.md)
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

    def _load_tools_for_skills(
        self,
        skill_names: list[str],
        include: set[str] | None = None,
        exclude: set[str] | None = None,
    ) -> list:
        """Load @tool-decorated functions from specific skill directories.

        Args:
            skill_names: Skill directory names under .olav/skills/
            include: If provided, only these tool names are returned
            exclude: If provided, these tool names are skipped

        Returns:
            Deduplicated list of LangChain tool objects (last write wins)
        """
        tools_by_name: dict = {}
        for skill_name in skill_names:
            tools_path = self.olav_base_path / "skills" / skill_name / "tools"
            if not tools_path.is_dir():
                logger.debug(f"  Skill tools path missing: {tools_path}")
                continue
            for tool in discover_tools(tools_path):
                if include and tool.name not in include:
                    continue
                if exclude and tool.name in exclude:
                    continue
                tools_by_name[tool.name] = tool
        return list(tools_by_name.values())

    # ------------------------------------------------------------------
    # OLAV.md config loading
    # ------------------------------------------------------------------

    def _load_olav_config(self) -> dict:
        """Load OLAV.md YAML frontmatter for SubAgent/orchestrator config.

        Raises:
            RuntimeError: If OLAV.md is missing, unreadable, or has no frontmatter.
        """
        olav_md = self.olav_base_path / "OLAV.md"
        if not olav_md.exists():
            raise RuntimeError(
                f"OLAV.md not found at {olav_md}. "
                "SubAgent registration requires .olav/OLAV.md with a valid 'subagents:' section."
            )
        if not _HAS_FRONTMATTER:
            raise RuntimeError(
                "python-frontmatter is not installed. "
                "Run: uv add python-frontmatter"
            )
        try:
            with open(olav_md, encoding="utf-8") as f:
                post = _frontmatter.load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to parse OLAV.md: {e}") from e
        if not post.metadata:
            raise RuntimeError(
                "OLAV.md has no YAML frontmatter. "
                "Add '---\norchestrator: ...\nsubagents: [...]\n---' at the top."
            )
        logger.info(f"✓ OLAV.md config loaded: {list(post.metadata.keys())}")
        return post.metadata

    def _load_orchestrator_tools(self, olav_config: dict) -> list:
        """Load orchestrator tools from OLAV.md orchestrator.skills / include_tools.

        Raises:
            RuntimeError: If 'orchestrator' section is missing from OLAV.md config.
        """
        orch = olav_config.get("orchestrator")
        if not orch:
            raise RuntimeError(
                "OLAV.md is missing the 'orchestrator:' section. "
                "Add 'orchestrator: {skills: [...], include_tools: [...], prompt: ...}' "
                "to .olav/OLAV.md."
            )
        skills = orch.get("skills") or []
        include_raw = orch.get("include_tools")
        include = set(include_raw) if include_raw else None
        return self._load_tools_for_skills(skills, include=include)

    # ------------------------------------------------------------------
    # SubAgent construction
    # ------------------------------------------------------------------

    def _build_subagents(self, olav_config: dict) -> list[SubAgent]:
        """Build SubAgents from OLAV.md frontmatter config.

        Each entry under ``subagents:`` may specify:
        - name          (required)
        - description   (required)
        - skills        list of skill directory names to scan for tools
        - include_tools only load these tool names (mutually exclusive with exclude_tools)
        - exclude_tools skip these tool names
        - prompt        relative path under .olav/skills/ to system prompt file
        """
        subagent_defs = olav_config.get("subagents") or []
        if not subagent_defs:
            raise RuntimeError(
                "OLAV.md has no 'subagents:' entries. "
                "Add at least one subagent definition to .olav/OLAV.md."
            )

        subagents: list[SubAgent] = []
        for sa_def in subagent_defs:
            name = sa_def["name"]
            description = sa_def["description"].strip()
            skills = sa_def.get("skills") or []

            include_raw = sa_def.get("include_tools")
            exclude_raw = sa_def.get("exclude_tools")
            include = set(include_raw) if include_raw else None
            exclude = set(exclude_raw) if exclude_raw else None

            tools = self._load_tools_for_skills(skills, include=include, exclude=exclude)
            logger.info(
                f"✓ SubAgent '{name}' ({len(tools)} tools): {[t.name for t in tools]}"
            )

            # Load prompt — path required in OLAV.md, file must exist
            prompt_rel = sa_def.get("prompt")
            if not prompt_rel:
                raise RuntimeError(
                    f"SubAgent '{name}' is missing a 'prompt:' path in OLAV.md. "
                    "Add 'prompt: <skill>/prompts/<file>.md' to the subagent definition."
                )
            prompt = _read_prompt_file(self.olav_base_path / "skills" / prompt_rel)
            if not prompt:
                raise RuntimeError(
                    f"SubAgent '{name}': prompt file not found or empty: "
                    f".olav/skills/{prompt_rel}. "
                    "Create the file or fix the 'prompt:' path in OLAV.md."
                )

            interrupt_on: dict | None = sa_def.get("interrupt_on") or None

            # Optional per-SubAgent model override.
            # OLAV.md supports a literal name ("claude-opus-4-5") or an env
            # var reference ("${OLAV_INSPECTION_MODEL}") resolved at startup.
            # Omit the field to share the orchestrator's model (LLM_MODEL_NAME).
            subagent_llm = None
            raw_model = sa_def.get("model")
            if raw_model:
                resolved = _resolve_env_ref(str(raw_model))
                subagent_llm = LLMFactory.get_chat_model(model_name=resolved)
                logger.info(f"  SubAgent '{name}' uses model override: {resolved}")

            subagents.append(
                SubAgent(
                    name=name,
                    description=description,
                    system_prompt=prompt,
                    tools=tools,
                    **({"model": subagent_llm} if subagent_llm else {}),
                    **({"interrupt_on": interrupt_on} if interrupt_on else {}),
                )
            )

        return subagents

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    def _get_orchestrator_prompt(self, olav_config: dict) -> str:
        """Load orchestrator system prompt from OLAV.md orchestrator.prompt.

        Raises:
            RuntimeError: If the prompt path is missing or the file cannot be read.
        """
        prompt_rel = (olav_config.get("orchestrator") or {}).get("prompt")
        if not prompt_rel:
            raise RuntimeError(
                "OLAV.md orchestrator section is missing a 'prompt:' path. "
                "Add 'prompt: <skill>/prompts/<file>.md' under 'orchestrator:'."
            )
        prompt = _read_prompt_file(self.olav_base_path / "skills" / prompt_rel)
        if not prompt:
            raise RuntimeError(
                f"Orchestrator prompt file not found: .olav/skills/{prompt_rel}. "
                "Create the file or fix the 'prompt:' path in OLAV.md."
            )
        return prompt

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def invoke(self, query: str, thread_id: str | None = None) -> dict:
        """Invoke the orchestrator with a natural language query.

        Args:
            query: User query
            thread_id: Optional conversation thread ID

        Returns:
            dict with keys: status, response, thread_id
        """
        try:
            input_data = {"messages": [{"role": "user", "content": query}]}
            config = None
            if self.checkpointer:
                config = {
                    "configurable": {
                        "thread_id": thread_id or f"thread-{id(input_data)}"
                    }
                }

            logger.info(f"[invoke] query={query[:100]!r}")
            result = await self.graph.ainvoke(input_data, config=config)

            messages = result.get("messages", [])
            if messages:
                last = messages[-1]
                content = (
                    last.content if hasattr(last, "content") else str(last)
                )
                return {
                    "status": "success",
                    "response": content,
                    "thread_id": thread_id or "default",
                }

            return {"status": "error", "message": "No response generated"}

        except Exception as e:
            logger.error(f"Agent invocation failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def stream(self, query: str, thread_id: str | None = None):
        """Stream agent events for real-time feedback.

        Args:
            query: User query
            thread_id: Optional conversation thread ID

        Yields:
            LangGraph streaming events
        """
        try:
            input_data = {"messages": [{"role": "user", "content": query}]}
            config = None
            if thread_id and self.checkpointer:
                config = {"configurable": {"thread_id": thread_id}}

            async for event in self.graph.astream(input_data, config=config):
                yield event

        except Exception as e:
            logger.error(f"Agent stream failed: {e}", exc_info=True)
            yield {"error": str(e)}


def create_olav_agent(**kwargs) -> OLAVAgent:
    """Create an OLAV Orchestrator Agent instance."""
    return OLAVAgent(**kwargs)


if __name__ == "__main__":
    import asyncio
    import json

    async def main():
        agent = create_olav_agent()
        result = await agent.invoke("How many devices do we have?")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(main())
