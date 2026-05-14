#!/usr/bin/env python3
"""
OLAV Orchestrator Agent - v4.0 (MVC: Agent=Controller, Tools=Model, Writer=View)

Architecture:
- OLAVAgent: orchestrator with 3 direct tools (execute_sql, recall_memory, web_search)
- 5 subagents: db_query, api_query, remote, admin, writer
- writer subagent: unified output engine with report-type references
- LangGraph MemorySaver for checkpoint/persistence
- LanceDB for long-term semantic memory
"""

import asyncio
import contextvars
import logging
import os
from pathlib import Path

from langchain_community.cache import SQLiteCache
from langchain_core.globals import set_llm_cache

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware

from olav.agents.delegate_tool import build_delegate_tool
from olav.agents._deepagents_bridge import (
    AnthropicPromptCachingMiddleware,
    AsyncSubAgent,
    CompiledSubAgent,
    HAS_ASYNC_SUBAGENTS,
    HAS_PROMPT_CACHING,
    SubAgent,
    build_summarization_middleware,
    create_deep_agent,
)

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


# ── Deepagents auto-injection: tools to strip from compiled graphs ──
# deepagents' create_agent always appends FilesystemMiddleware (glob,
# grep, ls, read_file, write_file, edit_file, execute) + TodoListMiddleware
# (write_todos) to whatever tools we pass. We can opt out of
# TodoListMiddleware via the `middleware=[]` kwarg (rev 261's
# agent_type:api flag), but FilesystemMiddleware has no opt-out and
# must be pruned post-compile.
#
# Rev 264 (2026-05-11): pruning extended from orchestrator-only (rev 281)
# to also include sub-agent runnables, because A1 / C1 timeout traces on
# gemma4 showed sub-agents triggering FilesystemMiddleware's read_file
# AFTER the business task completed, to "verify" their own output paths.
_DEEPAGENTS_INJECT_TOOLS = frozenset({
    "glob", "grep", "ls",
    "read_file", "write_file", "edit_file",
    "execute",
    "write_todos",
})


# ── Pre-compile `task` tool return_direct injection ─────────────────────
# Background: deepagents `SubAgentMiddleware` builds the `task` delegation
# tool via `_build_task_tool(...)` inside its __init__, then passes it to
# `create_agent`. langgraph factory.py:1436 inspects all tools' return_direct
# at COMPILE time to decide whether to wire an exit_node destination into
# the branch map. Mutating `return_direct` after the graph compiles is
# silently accepted at the attribute level but breaks routing at runtime
# (KeyError in _branch._finish) — see feedback memory 2026-05-12.
#
# To make pure-delegation orchestrators (audit) have a terminal `task`
# tool we monkey-patch `_build_task_tool` to set return_direct=True on the
# returned tool, gated by a contextvars.ContextVar that the OLAVAgent
# constructor sets right before calling create_deep_agent. This way the
# patch is per-agent opt-in and doesn't leak across orchestrators.
_TASK_RETURN_DIRECT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "OLAV_TASK_RETURN_DIRECT", default=False,
)

try:
    import deepagents.middleware.subagents as _ds_subagents
    _ORIGINAL_BUILD_TASK_TOOL = _ds_subagents._build_task_tool

    def _patched_build_task_tool(*args, **kwargs):
        tool = _ORIGINAL_BUILD_TASK_TOOL(*args, **kwargs)
        if _TASK_RETURN_DIRECT.get():
            tool.return_direct = True
            logger.info(
                "✓ Built `task` tool with return_direct=True (pure-delegation orchestrator)"
            )
        return tool

    _ds_subagents._build_task_tool = _patched_build_task_tool
except (ImportError, AttributeError) as _exc:
    logger.warning(
        "Could not patch deepagents `_build_task_tool` (task_return_direct "
        "AGENT.md flag will be a no-op): %s: %s",
        type(_exc).__name__, _exc,
    )


def _prune_graph_tools(graph, unwanted: frozenset[str], label: str) -> None:
    """Strip auto-injected tools from a compiled langgraph.

    ``graph`` is the runnable returned by ``create_agent`` (or
    ``create_deep_agent``). The compiled graph has a ``tools`` node
    whose ``bound._tools_by_name`` dict is the registry the LLM
    sees; mutating it removes the unwanted tools without rebuilding
    the graph.

    Best-effort: any structural mismatch (deepagents version change,
    middleware reorder) is swallowed with a warning — never block
    agent startup.
    """
    if os.environ.get("OLAV_KEEP_BUILTIN_TOOLS"):
        return
    try:
        tools_node = getattr(graph, "nodes", {}).get("tools")
        if tools_node is None or not hasattr(tools_node, "bound"):
            return
        bound = tools_node.bound
        tools_by_name = getattr(bound, "_tools_by_name", None)
        if not isinstance(tools_by_name, dict):
            return
        removed = []
        for name in list(tools_by_name.keys()):
            if name in unwanted:
                del tools_by_name[name]
                removed.append(name)
        if removed:
            logger.info(
                f"✓ Pruned {len(removed)} auto-injected tools from "
                f"{label}: {sorted(removed)} "
                f"(retain={sorted(tools_by_name)})"
            )
    except Exception as exc:  # noqa: BLE001 — never block startup
        logger.warning(
            f"Tool prune failed for {label} (non-fatal): "
            f"{type(exc).__name__}: {exc}"
        )


def _read_prompt_file(path: Path) -> str | None:
    """Read a prompt file, returning None if missing or unreadable."""
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read prompt {path}: {e}")
    return None


def _debug_log_injection(
    skill_dir: Path,
    mode: str,
    injected: list[tuple[str, int]],
    available_refs: list[str] | None = None,
) -> None:
    """Emit a multi-line static_context debug summary when enabled.

    Gated by ``OLAV_DEBUG_CONTEXT`` (see
    :func:`olav.agents.static_context_resolver.is_debug_enabled`). No-op
    when the env var is unset — zero overhead beyond a single env lookup.

    Output format (one log record, ``\\n``-joined)::

        OLAV_DEBUG_CONTEXT: agent=<name> mode=<mode> tier=<tier> budget=<N>T
          + ROUTING_EXPERT_GUIDE.md: 12345B (~3086T)
          + REQUIRED_INFO_CHECK.md: 2345B (~586T)
          → injected: 14690B (~3672T) / 8000T budget (45.9%)

    Token estimate is ``bytes // 4`` to match the heuristic used by
    ``tests/governance/test_v018_1_spec_guardrails.py::test_core_prompt_within_small_tier_budget``.
    """
    try:
        from olav.agents.static_context_resolver import is_debug_enabled
    except Exception:  # noqa: BLE001
        return
    if not is_debug_enabled():
        return

    try:
        from olav.core.config import get_llm_config, tier_default
        tier = get_llm_config().model_tier
        budget_tokens = int(tier_default(tier, "context_budget", 0) or 0)
    except Exception:  # noqa: BLE001
        tier, budget_tokens = "unknown", 0

    lines = [
        f"OLAV_DEBUG_CONTEXT: agent={skill_dir.name} "
        f"mode={mode} tier={tier} budget={budget_tokens}T"
    ]
    if mode != "always" and available_refs:
        lines.append(
            f"  (skipped init inject; {len(available_refs)} ref(s) available for lazy load: "
            f"{', '.join(available_refs)})"
        )
    total_bytes = 0
    for label, nbytes in injected:
        tokens = nbytes // 4
        total_bytes += nbytes
        lines.append(f"  + {label}: {nbytes}B (~{tokens}T)")
    total_tokens = total_bytes // 4
    if injected:
        if budget_tokens:
            pct = 100.0 * total_tokens / budget_tokens
            lines.append(
                f"  → injected: {total_bytes}B (~{total_tokens}T) "
                f"/ {budget_tokens}T budget ({pct:.1f}%)"
            )
        else:
            lines.append(f"  → injected: {total_bytes}B (~{total_tokens}T)")
    logger.info("\n".join(lines))


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

    # ARCH-17 P1: honour mode — only "always" bakes static_context into the
    # init prompt. "on_intent" and "lazy" modes leave the prompt lean;
    # StaticContextPlugin (per-turn) and get_static_context(@tool) handle
    # the other two paths.
    try:
        from olav.agents.static_context_resolver import resolve_mode
        mode = resolve_mode(metadata)
    except Exception as exc:  # noqa: BLE001
        logger.debug("static_context_resolver failed, defaulting to always: %s", exc)
        mode = "always"
    if mode != "always":
        logger.info(
            "static_context mode=%s for %s — skipping init-time inject",
            mode, skill_dir.name,
        )
        # Let the model self-direct: list the available references so it
        # knows what it can ask ``get_static_context(name)`` for.
        available = []
        for entry in static_ctx:
            rel = entry.get("path", entry) if isinstance(entry, dict) else entry
            rel = str(rel).removeprefix("$ref:")
            available.append(Path(rel).stem)
        _debug_log_injection(skill_dir, mode, [], available_refs=available)
        if available:
            hint = (
                f"\n\n---\n## References (call ``get_static_context(name)`` to retrieve)\n"
                f"Available: {', '.join(available)}\n"
            )
            return prompt + hint
        return prompt

    appended: list[str] = []
    injected_pairs: list[tuple[str, int]] = []
    for entry in static_ctx:
        # Support both {path: ...} dict and bare string
        rel_path = entry.get("path", entry) if isinstance(entry, dict) else entry
        # Strip leading $ref: prefix if present
        rel_path = rel_path.removeprefix("$ref:")
        full_path = (skill_dir / rel_path).resolve()
        content = _read_prompt_file(full_path)
        if content:
            label = full_path.name
            block = f"\n\n---\n## Reference: {label}\n\n{content.strip()}"
            appended.append(block)
            injected_pairs.append((label, len(block.encode("utf-8"))))
            logger.debug(f"  injected static_context: {label}")
        else:
            logger.warning(f"static_context file not found: {full_path}")

    if appended:
        logger.info(f"Injected {len(appended)} static_context file(s) from {skill_dir.name}")
        _debug_log_injection(skill_dir, "always", injected_pairs)
        return prompt + "".join(appended)
    _debug_log_injection(skill_dir, "always", injected_pairs)
    return prompt


def _resolve_env_ref(value: str) -> str:
    """Expand ``${ENV_VAR}`` references in a string against os.environ.

    Only simple identifier references (e.g. ``${OPENAI_API_KEY}``) are
    expanded.  Shell parameter-expansion syntax such as ``${VAR:?error}``,
    ``${VAR:-default}``, or ``${VAR:+alt}`` is intentionally left unchanged
    so that documentation examples in prompts/system.md are not misinterpreted
    as missing environment variables.
    """
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

    # Only match bare identifiers: letters, digits, underscores — no shell operators
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _sub, value)


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
        workspace: str | None = None,
    ):
        """Initialize OLAV Orchestrator Agent."""
        self.model_name = model_name or settings.llm_model_name
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.olav_base_path = Path(olav_base_path)
        self.agent_id = agent_id or "core"
        self.session_id = session_id
        self.workspace = workspace

        # Pre-load AGENT.md frontmatter so we can read ``thinking_mode``
        # *before* LLM construction (R-VERTICAL-SLICE 2026-05-09,
        # dev_docs/74).  Cached on self to avoid double-loading later.
        try:
            self._preloaded_olav_config = self._load_olav_config()
        except Exception as _e:
            logger.debug("AGENT.md preload failed (non-fatal): %s", _e)
            self._preloaded_olav_config = {}

        _orchestrator_thinking = self._preloaded_olav_config.get("thinking_mode")

        # LLM via LLMFactory
        self.llm = LLMFactory.get_chat_model(
            model_name=self.model_name,
            temperature=self.temperature,
            agent_id=self.agent_id,
            thinking_mode=_orchestrator_thinking,
        )
        logger.info(
            f"OLAV Orchestrator v3.4 initialized: "
            f"model={self.model_name}, temperature={self.temperature}, "
            f"agent={self.agent_id}, thinking={_orchestrator_thinking or 'default'}"
        )

        # Fire session.start hook (non-blocking)
        try:
            from olav.core.hooks import fire_hook
            import os
            fire_hook(
                "session.start",
                agent_id=self.agent_id,
                model=self.model_name,
                user=os.environ.get("USER", "unknown"),
            )
        except Exception:
            pass

        # LangChain LLM cache — SQLite (user-isolated in ~/.olav/cache/{user}/)
        from olav.core.config import USER_CACHE_DIR

        cache_path = USER_CACHE_DIR / "llm_cache.db"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            set_llm_cache(SQLiteCache(database_path=str(cache_path)))
            logger.info(f"✓ LLM cache enabled: {cache_path}")
        except Exception as e:
            logger.warning(f"LLM cache init failed: {e}. Caching disabled.")

        # Checkpointer — AsyncSqliteSaver: user-isolated, persistent, async-safe
        self.checkpointer = None
        if enable_checkpointer:
            try:
                import os

                from olav.core.checkpointer import create_checkpointer

                _user = os.environ.get("USER") or os.environ.get("USERNAME", "default_user")
                from olav.core.workspace import get_active_workspace
                _ws = self.workspace or get_active_workspace()
                self.checkpointer = create_checkpointer(
                    agent_id=self.agent_id, username=_user, workspace=_ws
                )
            except Exception as e:
                logger.warning(
                    f"AsyncSqliteSaver init failed ({e}), no checkpoint support available"
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

        # Build agent graph (reuse the preloaded config from above)
        olav_config = self._preloaded_olav_config or self._load_olav_config()

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

        # Append remote async subagents from api.json (non-blocking, graceful skip on error)
        try:
            from olav.agents.remote_subagents import load_remote_subagents
            import olav.core.config as _cfg
            api_config = getattr(_cfg.settings, "_api", {}) or {}
            remote_sas = load_remote_subagents(config=api_config)
            if remote_sas:
                subagents = list(subagents) + remote_sas
                logger.info(
                    "✓ Remote subagents loaded: %s",
                    [sa["name"] for sa in remote_sas],
                )
        except Exception as _e:
            logger.warning("Remote subagent loading failed (non-fatal): %s", _e)

        # Build olav_delegate tool bound to compiled subagent runnables.
        # Gives the orchestrator a way to delegate with guaranteed tool isolation,
        # bypassing deepagents' SubAgentMiddleware (which injects FilesystemMiddleware).
        _compiled_runnables = {
            sa["name"]: sa["runnable"]
            for sa in subagents
            if "runnable" in sa
        }
        orchestrator_tools = self._load_orchestrator_tools(olav_config)
        if _compiled_runnables:
            orchestrator_tools = list(orchestrator_tools) + [build_delegate_tool(_compiled_runnables)]
            logger.info(
                f"✓ olav_delegate registered with {len(_compiled_runnables)} subagents: "
                f"{sorted(_compiled_runnables.keys())}"
            )
        logger.info(
            f"✓ Orchestrator tools ({len(orchestrator_tools)}): "
            f"{[t.name for t in orchestrator_tools]}"
        )

        # 插件扣前加载 — 键入 create_deep_agent middleware + callbacks
        from olav.plugins import load_builtin_plugins, load_external_plugins
        from olav.plugins.middleware._mode import (
            partition_for_mode,
            resolve_middleware_mode,
        )
        from olav.plugins.registry import PluginRegistry

        _disabled = []
        try:
            _disabled = list(olav_config.get("plugins", {}).get("disabled", []))
        except Exception:
            pass
        self.plugin_registry = PluginRegistry(disabled=_disabled)
        load_builtin_plugins(self.plugin_registry)
        load_external_plugins(self.plugin_registry)

        # P3 dual-path: OLAV_MIDDLEWARE_MODE selects whether audit events
        # flow through the legacy AuditCallbackPlugin or the new
        # AuditMiddleware.  Both are loaded; the partitioner drops the
        # opposite path's audit plugin so events aren't recorded twice.
        # v0.20.1 default is "callback" (zero user-visible change); v0.20.2
        # flips the default to "middleware" for Phase 6 TUI cutover.
        self._middleware_mode = resolve_middleware_mode()
        effective_middleware, effective_callbacks = partition_for_mode(
            self.plugin_registry, self._middleware_mode
        )
        logger.info(
            "✓ Plugin registry: %d middleware, %d callbacks (mode=%s)",
            len(effective_middleware),
            len(effective_callbacks),
            self._middleware_mode,
        )

        # ISSUE-CTX-PROMPT-INFLATION fix (2026-04-30):
        # deepagents' built-in summarization (graph.py:449) calls
        # ``compute_summarization_defaults`` which falls back to
        # ``trigger=("tokens", 170000)`` when ``model.profile`` lacks
        # ``max_input_tokens`` — i.e. for any local llama.cpp / vLLM
        # endpoint, summarization never fires before the 64K ctx wall.
        # Fix: set ``profile.max_input_tokens`` from ``llm.context_budget``
        # (api.json) or fallback to TIER_DEFAULTS so deepagents picks the
        # fraction-based path (default 0.85 × budget) automatically.
        # Adding a second SummarizationMiddleware errors out with
        # "duplicate middleware instances" — patching the model is
        # the only clean route.
        try:
            from olav.core.config import TIER_DEFAULTS, get_llm_config
            _llm_cfg = get_llm_config()
            _budget = _llm_cfg.context_budget  # api.json llm.context_budget
            if _budget is None or _budget <= 0:
                _budget = int(TIER_DEFAULTS.get(_llm_cfg.model_tier, {}).get("context_budget") or 0)
            if _budget > 0:
                # langchain models expose .profile as a dict-like attr.
                # Prime it so compute_summarization_defaults picks the
                # fraction path (0.85 × budget trigger, 0.10 × budget keep).
                if not hasattr(self.llm, "profile") or self.llm.profile is None:
                    try:
                        self.llm.profile = {}  # type: ignore[attr-defined]
                    except Exception:
                        pass
                if isinstance(getattr(self.llm, "profile", None), dict):
                    self.llm.profile.setdefault("max_input_tokens", _budget)  # type: ignore[union-attr]
                    logger.info(
                        "✓ Model profile.max_input_tokens=%d (summarization "
                        "trigger ≈ %d tok at 0.85 fraction)",
                        _budget, int(_budget * 0.85),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Summarization budget priming skipped: %s", exc)

        # R100/S4 (2026-04-29): deny deepagents' default write_file /
        # edit_file (which operate on a LangGraph state["files"] virtual
        # FS that is NOT real disk).  When the LLM was given an open-
        # ended "save to exports/" prompt, it sometimes picked the
        # virtual write_file (looks simpler — just file_path + content)
        # over OLAV's format_and_export, got a deceptive success, then
        # spent N turns trying to chmod a non-existent file.  Demo7
        # Ch8 v8 (canonical "Write a bash script to backup running-
        # config") looped for 20 minutes on this.
        #
        # Denying write redirects the model to format_and_export (the
        # only OLAV-registered write-class tool) on the next attempt.
        # Reads are still allowed so cross-turn data passing via state
        # files keeps working.
        #
        # Override via env: OLAV_ALLOW_VIRTUAL_FS_WRITES=1 to disable
        # this restriction (debug only — prefer real-disk tools).
        #
        # Optional dep: deepagents.middleware.permissions exists in
        # deepagents >= 0.5.3.  Older versions silently skip the feature.
        _fs_permissions = None
        if not os.environ.get("OLAV_ALLOW_VIRTUAL_FS_WRITES"):
            try:
                from deepagents.middleware.permissions import (
                    FilesystemPermission,
                )
                _fs_permissions = [
                    FilesystemPermission(
                        operations=["write"], paths=["/**"], mode="deny",
                    ),
                    # 2026-05-01 Ch9 fix — deny virtual-FS read/list ops
                    # too.  When user asks "list profiles" / "what reports
                    # exist", small models (gemma4:31b) reach for
                    # ls/glob/grep on the deepagents in-memory virtual
                    # FS instead of delegating to a sub-agent or running
                    # a skill script.  Result: empty list, false-negative
                    # answer.  Denying virtual-FS read pushes the model
                    # to use real-disk paths (read_file core tool, or
                    # task() delegation, or execute_skill_script).
                    # Override with OLAV_ALLOW_VIRTUAL_FS_READS=1.
                    *([] if os.environ.get("OLAV_ALLOW_VIRTUAL_FS_READS") else [
                        FilesystemPermission(
                            operations=["read"], paths=["/**"], mode="deny",
                        ),
                        FilesystemPermission(
                            operations=["list"], paths=["/**"], mode="deny",
                        ),
                    ]),
                ]
                logger.info(
                    "✓ deepagents virtual-FS writes denied "
                    "(OLAV_ALLOW_VIRTUAL_FS_WRITES=1 to disable)"
                )
            except ImportError:
                logger.debug(
                    "deepagents.middleware.permissions not available "
                    "(need >= 0.5.3); virtual-FS writes will silently "
                    "succeed and may deceive the agent on open-ended "
                    "save tasks"
                )

        _create_kwargs: dict = dict(
            model=self.llm,
            tools=orchestrator_tools,
            system_prompt=self._get_orchestrator_prompt(olav_config),
            checkpointer=self.checkpointer,
            store=self.store,
            subagents=subagents,
            middleware=effective_middleware,
        )
        if _fs_permissions is not None:
            _create_kwargs["permissions"] = _fs_permissions

        # Per-orchestrator opt-in for terminal `task` tool. The contextvar
        # is read by `_patched_build_task_tool` during create_deep_agent →
        # SubAgentMiddleware → _build_task_tool. Setting return_direct=True
        # at this point lets langgraph wire the exit_node into the compiled
        # branch map (post-compile mutation does not work; see memory
        # feedback_return_direct_post_compile.md).
        _task_rd_token = _TASK_RETURN_DIRECT.set(bool(olav_config.get("task_return_direct")))
        try:
            self.graph = create_deep_agent(**_create_kwargs)
        finally:
            _TASK_RETURN_DIRECT.reset(_task_rd_token)
        # Store middleware ref for manual invocation — deepagents 0.5.2
        # accepts the `middleware` kwarg but doesn't mount it on the graph.
        self._olav_middleware = list(effective_middleware)
        self._olav_callbacks = list(effective_callbacks)

        # 2026-05-10 INVIVO-ORCH-FILESYSTEM-LEAK fix: deepagents auto-
        # injects FilesystemMiddleware tools (glob, grep, ls, read_file,
        # write_file, edit_file) and TodoListMiddleware (write_todos)
        # into the orchestrator's tool registry. The FilesystemPermission
        # deny rules silently fail to match relative glob patterns
        # (paths=["/**"] doesn't match "**/r3-r4-ebgp*"), so the LLM
        # successfully calls glob to search files instead of dispatching
        # to a sub-agent.
        #
        # T15 in-vivo failure: prompt "fix wrong interface in r3-r4-ebgp"
        # → orchestrator called glob("**/r3-r4-ebgp*") + glob(
        # "/exports/**/*.tcf.yaml"), never reached task("sim").
        #
        # Surgical fix: prune the offending tools from the compiled
        # graph's tool registry. Orchestrators that declare a `tools:`
        # whitelist in SKILL.md should ONLY have those tools (plus
        # olav_delegate/task for sub-agent dispatch).
        self._prune_orchestrator_tools(olav_config)

    def _prune_orchestrator_tools(self, olav_config: dict) -> None:
        """Strip auto-injected filesystem / todo tools from the compiled
        orchestrator graph (post-create_deep_agent fixup).

        Why this is post-compile rather than pre: deepagents'
        ``create_deep_agent`` appends FilesystemMiddleware tools to
        whatever ``tools=`` we pass, and there is no public API to
        opt out of the base middleware stack. The simplest path is
        to mutate the compiled tool registry on the ``tools`` node
        afterward.

        Tools removed by default: ``glob``, ``grep``, ``ls``,
        ``read_file``, ``write_file``, ``edit_file``, ``execute``,
        ``write_todos``. Sub-agent dispatch tools (``task``,
        ``olav_delegate``) and OLAV-declared tools are preserved.
        Override via ``OLAV_KEEP_BUILTIN_TOOLS=1`` if a debug session
        needs the unfiltered set.
        """
        if os.environ.get("OLAV_KEEP_BUILTIN_TOOLS"):
            logger.info(
                "Orchestrator tool prune SKIPPED — OLAV_KEEP_BUILTIN_TOOLS=1"
            )
            return

        _prune_graph_tools(self.graph, _DEEPAGENTS_INJECT_TOOLS, f"orchestrator '{self.agent_id}'")

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
        """Load tools: core workspace tools (global) + this agent's tools.

        Core workspace tools (e.g. recall_memory, execute_sql) are always
        loaded first so they are available in every agent regardless of
        workspace. Agent-specific tools are appended after, with duplicates
        (by name) removed.

        If AGENT.md frontmatter has an ``excluded_tools`` list, those tool
        names are removed from the final set before returning. This allows
        domain agents (e.g. ops/lab) to suppress generic core tools (e.g.
        web_search) that would interfere with their constrained workflows.
        """
        tools: list = []
        seen_names: set[str] = set()

        def _add(new_tools: list) -> None:
            for t in new_tools:
                if t.name not in seen_names:
                    tools.append(t)
                    seen_names.add(t.name)

        # Patch D' (2026-05-08): cross-directory tool resolution.
        # If the agent's own SKILL.md declares a ``tools:`` list, that
        # list applies to BOTH core/tools/ and the agent's own tools/
        # — i.e., the agent positively states what it wants from the
        # combined pool.  Without this, declaring ``tools:
        # [execute_skill_script, exec_on_node]`` in lab/SKILL.md
        # wouldn't pull execute_skill_script (which lives in
        # core/tools/, not lab/tools/).
        skill_path = self._agent_dir / "SKILL.md"
        own_filter: set[str] | None = None
        if skill_path.exists():
            own_filter = self._read_tools_filter(skill_path)
        else:
            # AGENT.md may carry a tools field instead (orchestrators)
            agent_md = self._agent_dir / "AGENT.md"
            if agent_md.exists():
                own_filter = self._read_tools_filter(agent_md)

        # ① Load core workspace tools, filtered by this agent's
        # declared list.  When no filter is declared, current behaviour
        # is preserved (all core tools auto-load — backward compat).
        core_skill = self.olav_base_path / "workspace" / "core" / "SKILL.md"
        if core_skill.exists():
            _add(self._load_tools_from_skill(core_skill, whitelist=own_filter))

        # ② Load this agent's own tools, filtered by the same list
        if skill_path.exists():
            _add(self._load_tools_from_skill(skill_path, whitelist=own_filter))
        elif not core_skill.exists():
            logger.info("No SKILL.md found, using subagents only")

        # ③ Apply excluded_tools from AGENT.md frontmatter
        excluded: list[str] = list(olav_config.get("excluded_tools", []))
        if excluded:
            before = len(tools)
            tools = [t for t in tools if t.name not in excluded]
            logger.info(
                f"excluded_tools filter: removed {before - len(tools)} tools "
                f"({excluded}); {len(tools)} tools remaining"
            )

        return tools

    def _load_tools_from_skill(
        self,
        skill_path: Path,
        whitelist: set[str] | None = None,
    ) -> list:
        """Load tools from a SKILL.md file's adjacent ``tools/`` directory.

        Patch D' (2026-05-08): registration is now decoupled from
        implementation sharing.  SKILL.md / AGENT.md may declare a
        ``tools:`` list; when present, the loader returns ONLY tools
        whose name is in that list.  This stops every agent from
        auto-inheriting every .py file in ``tools/`` regardless of
        whether it's relevant — the source of the prompt-bloat +
        wrong-tool-pick issues local LLMs hit on multi-step tasks.

        The function reads the skill's own ``tools:`` field as the
        default filter; callers may pass an explicit ``whitelist``
        when filtering by a different agent's declaration (used by
        ``_build_tools`` to filter core/tools/ by the calling agent's
        declared list — see Patch D' rationale).

        Backward compatibility: if neither the SKILL.md nor the
        explicit whitelist provides a filter, all .py files in the
        adjacent ``tools/`` directory are returned (current behaviour).
        """
        try:
            with open(skill_path, encoding="utf-8") as f:
                post = _frontmatter.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse SKILL.md {skill_path}: {e}")
            return []

        tools_dir = skill_path.parent / "tools"
        if not tools_dir.is_dir():
            return []
        all_tools = discover_tools(tools_dir)

        # Determine the filter (whitelist).  Explicit caller arg wins;
        # else fall back to this SKILL.md's own ``tools:`` field.
        effective_filter = whitelist
        if effective_filter is None:
            tools_field = (post.metadata or {}).get("tools")
            if isinstance(tools_field, list):
                # Strict mode: list present (even empty) → use as filter
                effective_filter = {
                    t for t in tools_field if isinstance(t, str)
                }

        if effective_filter is None:
            return all_tools  # backward-compat: no filter declared

        filtered = [t for t in all_tools if t.name in effective_filter]
        # Surface drops in debug logs (helps spot SKILL.md typos quickly)
        dropped = {t.name for t in all_tools} - {t.name for t in filtered}
        if dropped:
            logger.debug(
                "SKILL.md %s: filtered out %d unsubscribed tool(s): %s",
                skill_path, len(dropped), sorted(dropped),
            )
        return filtered

    def _read_tools_filter(self, skill_path: Path) -> set[str] | None:
        """Read the ``tools:`` list from a SKILL.md / AGENT.md
        frontmatter and return it as a name set, or ``None`` when the
        field is absent.

        Used by ``_build_tools`` to apply this agent's declared filter
        when loading core tools (cross-directory resolution: agent
        declares ``execute_skill_script``; impl lives in core/tools/).
        """
        try:
            with open(skill_path, encoding="utf-8") as f:
                post = _frontmatter.load(f)
        except Exception:
            return None
        tools_field = (post.metadata or {}).get("tools")
        if isinstance(tools_field, list):
            names: set[str] = set()
            dropped_dicts = 0
            for t in tools_field:
                if isinstance(t, str):
                    names.add(t)
                elif isinstance(t, dict):
                    dropped_dicts += 1
            if dropped_dicts:
                logger.warning(
                    "SKILL.md %s declares %d tools as dict entries "
                    "(e.g. `- path: ./tools/X.py`); strict whitelist "
                    "requires bare-string tool names. Dropped entries "
                    "result in 0 tools loaded for this agent — convert "
                    "to bare-string format.",
                    skill_path, dropped_dicts,
                )
            return names
        return None

    # ------------------------------------------------------------------
    # SubAgent construction
    # ------------------------------------------------------------------

    def _build_subagents(self, olav_config: dict) -> list[SubAgent | CompiledSubAgent | AsyncSubAgent]:
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

            # Patch D' (2026-05-08): apply sub-agent's declared tools
            # filter to BOTH its own tools/ and inherited core/tools/.
            # Sub-agent's SKILL.md is authoritative for what it sees.
            sa_filter = self._read_tools_filter(skill_md)

            tools_dir = sa_dir / "tools"
            tools = []
            if tools_dir.is_dir():
                discovered = discover_tools(tools_dir)
                if sa_filter is not None:
                    tools = [t for t in discovered if t.name in sa_filter]
                else:
                    tools = discovered

            # R-VERTICAL-SLICE 2026-05-09 (dev_docs/74): also discover
            # tools from the parent orchestrator's tools/ dir, filtered
            # by the sub-agent's whitelist.  This lets sub-agents share
            # a domain-level tool library (e.g. netops/tools/inspect_*.py
            # used by both ``analyze`` and ``sim``) without duplicating
            # files.  Whitelist is mandatory: without one, parent tools
            # are skipped to keep the implicit blast radius small.
            parent_tools_dir = self._agent_dir / "tools"
            if parent_tools_dir.is_dir() and sa_filter is not None:
                parent_discovered = discover_tools(parent_tools_dir)
                existing_names = {t.name for t in tools}
                for t in parent_discovered:
                    if t.name in sa_filter and t.name not in existing_names:
                        tools.append(t)

            # Prepend core workspace tools — filtered by the sub-agent's
            # declared list when present, so e.g. lab declaring
            # ``tools: [execute_skill_script, exec_on_node]`` pulls
            # execute_skill_script from core/tools/ but no other core tool.
            core_skill = None
            _base = getattr(self, "olav_base_path", None)
            if _base is not None:
                core_skill = _base / "workspace" / "core" / "SKILL.md"
            if core_skill is not None and core_skill.exists():
                core_tools = self._load_tools_from_skill(
                    core_skill, whitelist=sa_filter,
                )
                existing_names = {t.name for t in tools}
                # Prepend core tools; subagent-local tools take precedence on name clash
                tools = [t for t in core_tools if t.name not in existing_names] + tools

            prompt_file = metadata.get("system_prompt_file", "prompts/system.md")
            prompt_path = sa_dir / prompt_file
            prompt = _read_prompt_file(prompt_path)
            if not prompt:
                prompt = f"You are the {name} agent."

            # Inject static_context references declared in SKILL.md
            prompt = _inject_static_context(prompt, sa_dir, metadata)

            # R-VERTICAL-SLICE 2026-05-09 (dev_docs/74): per-sub-agent
            # ``thinking_mode`` overrides the orchestrator's setting.  When
            # the sub-agent's mode differs from what ``self.llm`` was
            # constructed with, build a dedicated LLM for this sub-agent.
            sa_thinking = metadata.get("thinking_mode")
            sa_llm = self.llm
            _orch_thinking = (self._preloaded_olav_config or {}).get("thinking_mode")
            if sa_thinking is not None and sa_thinking != _orch_thinking:
                try:
                    sa_llm = LLMFactory.get_chat_model(
                        model_name=self.model_name,
                        temperature=self.temperature,
                        agent_id=name,
                        thinking_mode=sa_thinking,
                    )
                    logger.info(
                        f"  → sub-agent '{name}' uses dedicated LLM "
                        f"(thinking_mode={sa_thinking})"
                    )
                except Exception as _e:
                    logger.warning(
                        f"  ! per-agent LLM init failed for '{name}' "
                        f"({_e}); falling back to orchestrator LLM"
                    )
                    sa_llm = self.llm

            logger.info(f"✓ SubAgent '{name}' ({len(tools)} tools): {[t.name for t in tools]}")

            # Always compile subagents as CompiledSubAgent (runnable) so deepagents
            # uses them as-is and does NOT inject FilesystemMiddleware.
            # Previously, zero-tool subagents were passed as plain SubAgent dicts,
            # which caused deepagents to rebuild them with the full middleware stack.
            #
            # agent_type: api — pure API/query agents skip TodoListMiddleware to keep
            # the execution path minimal (no filesystem side-effects expected).
            _is_api_agent = metadata.get("agent_type", "").strip().lower() in ("api", "query")
            _middleware = [] if _is_api_agent else [TodoListMiddleware()]
            # ARCH-19 Round 42: tier-aware summarization threshold — small
            # tier fires at 50% of context_budget, medium at 65%, large at
            # 80% (via TIER_DEFAULTS.summarization_trigger_pct).
            try:
                from olav.core.config import get_llm_config
                _tier = get_llm_config().model_tier
            except Exception:
                _tier = None
            _summ = build_summarization_middleware(self.llm, tier=_tier)
            if _summ is not None:
                _middleware.append(_summ)
            if HAS_PROMPT_CACHING and AnthropicPromptCachingMiddleware is not None:
                _middleware.append(AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"))

            # dev_docs/77 §2.6.2: a sub-agent that itself declares
            # ``subagents:`` in its SKILL.md needs deepagents'
            # ``SubAgentMiddleware`` to inject the ``task`` tool so it
            # can delegate to its peers (e.g. analyzer → sim).  Build
            # via ``create_deep_agent`` in that case; the deepagents
            # middleware then auto-wires the task tool.
            sa_nested_subagents = metadata.get("subagents") or []
            if sa_nested_subagents:
                # Recursive build: nested ``- path:`` entries are
                # resolved relative to *this* sub-agent's directory,
                # so temporarily swap _agent_dir for the inner call.
                _saved_agent_dir = self._agent_dir
                try:
                    self._agent_dir = sa_dir
                    nested = self._build_subagents(
                        {"subagents": sa_nested_subagents},
                    )
                finally:
                    self._agent_dir = _saved_agent_dir
                logger.info(
                    f"  → '{name}' is a recursive deep-agent with "
                    f"{len(nested)} nested sub-agent(s); task() auto-injected"
                )
                # create_deep_agent installs its own complete middleware
                # stack (TodoListMiddleware + SubAgentMiddleware +
                # FilesystemMiddleware + summarization + prompt-caching
                # when configured at the orchestrator level).  Passing
                # ANY of our sub-agent-level middleware produces
                # "Please remove duplicate middleware instances".  Let
                # deepagents own the full stack; we just pass the
                # tools + subagents wiring.
                runnable = create_deep_agent(
                    model=sa_llm,
                    system_prompt=prompt,
                    tools=tools,
                    subagents=nested,
                    name=name,
                )
            else:
                runnable = create_agent(
                    sa_llm,
                    system_prompt=prompt,
                    tools=tools,  # may be empty list — still prevents FilesystemMiddleware
                    middleware=_middleware,
                    name=name,
                )
            # Rev 264: sub-agent runnable also gets deepagents
            # FilesystemMiddleware injection (glob/grep/ls/read_file/
            # write_file/edit_file). Even with the SKILL.md whitelist
            # filtering OLAV's own tools, deepagents adds these on
            # top. gemma4 was triggering read_file post-task to
            # "verify" its own output — pruning here stops that
            # plan-loop tail. write_todos handled via agent_type:api.
            _prune_graph_tools(runnable, _DEEPAGENTS_INJECT_TOOLS, f"sub-agent '{name}'")
            subagents.append(
                {
                    "name": name,
                    "description": description,
                    "runnable": runnable,
                }
            )

        return subagents

    def _get_orchestrator_prompt(self, olav_config: dict) -> str:
        """Get the system prompt for the orchestrator.

        Build order:
          1. PLATFORM.md context (global — platform topology, registered agents)
          2. Agent's own prompts/system.md
          3. static_context files declared in AGENT.md frontmatter
        """
        # ① PLATFORM.md global context
        try:
            from olav.core.platform_registry import PlatformRegistry
            platform_ctx = PlatformRegistry.load(self.olav_base_path / "workspace").as_context()
        except Exception as _e:
            logger.debug("PLATFORM.md context unavailable: %s", _e)
            platform_ctx = ""

        # ② Agent-specific system prompt
        prompt_file = self._agent_dir / "prompts" / "system.md"
        agent_prompt = _read_prompt_file(prompt_file)

        if agent_prompt:
            try:
                agent_prompt = _resolve_env_ref(agent_prompt)
            except RuntimeError as e:
                logger.warning(f"Failed to resolve env vars in prompt: {e}")
            # ③ Inject static_context from AGENT.md frontmatter
            agent_prompt = _inject_static_context(agent_prompt, self._agent_dir, olav_config)
            logger.info(f"Loaded system prompt from {prompt_file}")
        else:
            agent_prompt = olav_config.get("description", "You are OLAV, an AI operations assistant.")

        if platform_ctx:
            return platform_ctx + "\n\n---\n\n" + agent_prompt
        return agent_prompt

    # ------------------------------------------------------------------
    # Invoke methods (interface for backwards compatibility)
    # ------------------------------------------------------------------

    async def ainvoke(self, input_: str | dict, thread_id: str | None = None, **kwargs) -> dict:
        """Async invoke the agent graph."""
        if isinstance(input_, str):
            input_ = {"messages": [{"role": "user", "content": input_}]}

        # Use mode-filtered callback list so AuditCallbackPlugin is
        # dropped when OLAV_MIDDLEWARE_MODE=middleware (otherwise audit
        # events get recorded twice — once via callback, once via
        # AuditMiddleware's graph hooks).
        # Back-compat: tests that bypass __init__ (e.g. via
        # ``object.__new__(OLAVAgent)``) never set ``_olav_callbacks``
        # — fall back to the raw registry list so those tests still
        # work without carrying stale partitioning logic.
        effective_callbacks = getattr(self, "_olav_callbacks", None)
        if effective_callbacks is None:
            effective_callbacks = self.plugin_registry.get_callback_plugins()
        config: dict = {"callbacks": effective_callbacks}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        # Rev 267: cap langgraph recursion to prevent small-LLM post-reply
        # hallucination loops (rev 264 observed: gemma4 31B nothink streams
        # spurious traceback text after final reply → langgraph re-enters
        # LLM → no-op → re-enters → wall-clock timeout). 30 leaves plenty
        # of headroom for legitimate multi-tool flows (audit Run = 2 calls,
        # Author Mode 3 ≤ 5 calls, sim/lab ≤ 10) while capping the worst-case
        # loop at ~10× the longest legit path. Override via env if a flow
        # genuinely needs more.
        config["recursion_limit"] = int(
            os.environ.get("OLAV_LANGGRAPH_RECURSION_LIMIT", "30")
        )

        try:
            result = await self.graph.ainvoke(input_, config=config, **kwargs)
        except asyncio.CancelledError as e:
            # CancelledError is BaseException in Python 3.8+, not Exception.
            # Typically raised when memory extraction or an LLM API call times
            # out during graph execution.  Degrade gracefully instead of letting
            # the coroutine die silently with exit-code 0.
            logger.warning("ainvoke cancelled (likely LLM API timeout during memory extraction): %s", e)
            return {"status": "error", "response": f"Agent execution was cancelled: {e}"}
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
        """Release resources (SQLite connection, etc.)."""
        # Fire session.end hook (non-blocking)
        try:
            from olav.core.hooks import fire_hook
            fire_hook("session.end", agent_id=self.agent_id)
        except Exception:
            pass
        try:
            from olav.core.checkpointer import AsyncSqliteSaver

            if isinstance(self.checkpointer, AsyncSqliteSaver):
                self.checkpointer.conn.close()
                logger.debug("Checkpointer SQLite connection closed.")
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
