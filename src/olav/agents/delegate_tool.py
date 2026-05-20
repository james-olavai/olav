"""olav_delegate — isolated subagent delegation tool.

Bypasses deepagents' SubAgentMiddleware to guarantee that each named
subagent runs with ONLY the tools declared in its SKILL.md, with no
FilesystemMiddleware or other deepagents-injected tools.

ARCH-18 (Round 40): returned content is truncated to the current tier's
``return_compact_chars`` budget (small=2000, medium=5000, large=10000)
so a chatty subagent can't single-handedly eat a small-model
orchestrator's context window. Truncation appends a visible
``…[truncated, ran N > M chars]`` suffix — callers can always re-delegate
with more specific scope if they need the tail.

Usage (registered on the orchestrator):
    tools = [olav_delegate, ...]
    graph = create_deep_agent(model=llm, tools=tools, ...)
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# Hard floor so small-tier budgets (2000) still leave room for a meaningful
# response; test environments with no config fall back to this.
_SUBAGENT_RETURN_FALLBACK = 10000


def _resolve_subagent_cap() -> int:
    """Return the current tier's subagent return budget in characters.

    Priority: ``TIER_DEFAULTS[<tier>]["return_compact_chars"]`` first (same
    switchboard ARCH-18 #2 uses for execute_cli / diff_configs / api_request
    response truncation); fall back to ``_SUBAGENT_RETURN_FALLBACK`` if
    config is unavailable.
    """
    try:
        from olav.core.config import get_llm_config, tier_default
        tier = get_llm_config().model_tier
        budget = tier_default(tier, "return_compact_chars", _SUBAGENT_RETURN_FALLBACK)
        return int(budget) if budget else _SUBAGENT_RETURN_FALLBACK
    except Exception:  # noqa: BLE001
        return _SUBAGENT_RETURN_FALLBACK


# Cross-workspace semantic aliases — used when the LLM picks a
# top-level agent name (e.g. ``topology``, registered globally as
# ``.olav/workspace/topology/``) for a request that actually belongs to
# a sub-agent of the current orchestrator.  The map is keyed by the
# *requested* name; resolution checks each candidate target against the
# orchestrator's actual ``_compiled_runnables`` and returns the first
# present.  Order = preference.  Add aliases here, NOT in prompts —
# the prompt is unreliable as a routing mechanism for small models.
_SEMANTIC_ALIASES: dict[str, tuple[str, ...]] = {
    # Cross-workspace name collisions: ``topology`` is also a top-level
    # workspace, but inside netops the Mermaid / blast-radius rendering
    # belongs to ops-analyze (it owns format_and_export(format='mmd')).
    "topology": ("ops-analyze", "analyze", "writer"),
    "topology-viz": ("ops-analyze", "analyze"),
    "topology_viz": ("ops-analyze", "analyze"),
    "diagram": ("writer", "ops-analyze"),
    "mermaid": ("writer", "ops-analyze"),
    # ``simulation`` / ``drift`` / ``diff`` / ``analysis`` are read-side
    # capabilities that map to the analyze sub-agent.
    "simulation": ("sim", "ops-analyze", "analyze"),
    "drift": ("ops-analyze", "analyze"),
    "diff": ("ops-analyze", "analyze"),
    "analysis": ("ops-analyze", "analyze"),
    "analyse": ("ops-analyze", "analyze"),
    # Plain "analyze" → registered as ops-analyze.
    "analyze": ("ops-analyze",),
    # ARCH-30 (2026-05-10): ``sim`` is its own sub-agent post-Phase B+C
    # (R-AGENT-HIERARCHY).  The legacy alias mapping ``sim`` → ops-analyze
    # was correct before the split; it now hides the dedicated sim agent.
    # Resolver checks exact match first, so this entry only matters for
    # workspaces that don't have a sim sub-agent registered (then it
    # falls back to analyze).
    # LEGACY-KEEP: fallback to ops-analyze/analyze intentional for workspaces
    # without a dedicated sim sub-agent (e.g. slim installs, olav-ent).
    "sim": ("sim", "ops-analyze", "analyze"),
}


def _resolve_alias(
    requested_name: str, available: dict[str, Any]
) -> str | None:
    """Return the first registered alias target, or ``None``.

    Lookup is case-insensitive.  ``available`` is the live runnables
    dict — only candidates that are actually present resolve.
    """
    targets = _SEMANTIC_ALIASES.get(requested_name.lower())
    if not targets:
        return None
    for t in targets:
        if t in available:
            return t
    return None


def _best_match(requested: str, available: list[str]) -> str | None:
    """Cheap "did you mean" — substring or prefix overlap on lowercase.

    Returns the highest-scoring match, or ``None`` if nothing reasonable.
    Avoids importing difflib for a 30-char ranking task.
    """
    if not available:
        return None
    req = requested.lower()
    scored: list[tuple[int, str]] = []
    for name in available:
        n = name.lower()
        score = 0
        if req == n:
            score = 100
        elif req in n or n in req:
            score = 50 + min(len(req), len(n))
        else:
            # token-overlap heuristic
            req_tokens = set(req.replace("-", "_").split("_"))
            n_tokens = set(n.replace("-", "_").split("_"))
            common = req_tokens & n_tokens
            score = sum(len(t) for t in common)
        if score > 0:
            scored.append((score, name))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _truncate(content: str, cap: int) -> str:
    """Truncate ``content`` to ``cap`` chars with a visible suffix.

    The suffix includes the full size so the orchestrator LLM can decide
    whether to re-delegate with a narrower scope (e.g. "summarize in 500
    chars") or accept the truncated view as sufficient.
    """
    if cap <= 0 or len(content) <= cap:
        return content
    return content[:cap] + f"\n…[truncated, subagent produced {len(content)} > {cap} chars]"


def build_delegate_tool(
    subagent_runnables: dict[str, Runnable],
) -> Any:
    """Return an ``olav_delegate`` @tool bound to the compiled subagent runnables.

    Args:
        subagent_runnables: Mapping of subagent name → compiled LangChain runnable.
                            Built by OLAVAgent._build_subagents().

    Returns:
        A LangChain tool callable.  Register it on the orchestrator tool list.
    """

    @tool
    def olav_delegate(subagent_name: str, task_description: str) -> str:
        """Delegate a task to a named OLAV subagent with complete tool isolation.

        Unlike deepagents task(), this guarantees the subagent receives ONLY the
        tools declared in its SKILL.md — no FilesystemMiddleware, no write_todos,
        no generic sandbox tools.  Use this for all cross-agent delegation.

        Args:
            subagent_name: Exact name of the subagent (e.g. 'analyzer',
                           'sim', 'investigate').  Call
                           list_platform_services() or check PLATFORM.md to
                           discover available names.
            task_description: Complete, self-contained task description.
                              The subagent has NO memory of the current
                              conversation — include all relevant context.
        """
        runnable = subagent_runnables.get(subagent_name)
        if runnable is None:
            # Auto-route on known semantic aliases first — covers the
            # cross-workspace name collision case where the LLM picks a
            # top-level agent name (e.g. 'topology') for a request that
            # actually belongs to a sub-agent of the current orchestrator
            # (e.g. ops-analyze, which owns topology visualisation).
            # Without auto-route the LLM tends to fall back to ad-hoc SQL
            # and hallucinate the save step (R83.4 Chapter 4 bug).
            redirected = _resolve_alias(subagent_name, subagent_runnables)
            if redirected:
                logger.info(
                    "olav_delegate: alias '%s' → '%s'",
                    subagent_name, redirected,
                )
                runnable = subagent_runnables[redirected]
                subagent_name = redirected  # so the result attribution is accurate
            else:
                available = sorted(subagent_runnables.keys())
                # Suggest the closest match by simple substring/prefix
                # heuristic — small models follow "Did you mean X?" hints
                # more reliably than a flat list.
                suggestion = _best_match(subagent_name, available)
                hint = (
                    f" Did you mean '{suggestion}'? Retry with that name."
                    if suggestion else ""
                )
                return (
                    f"Subagent '{subagent_name}' not found.{hint} "
                    f"Available subagents: {available}"
                )

        try:
            result = runnable.invoke(
                {"messages": [HumanMessage(content=task_description)]}
            )
        except Exception as exc:
            logger.exception("olav_delegate: subagent '%s' raised", subagent_name)
            return f"Subagent '{subagent_name}' failed: {exc}"

        # Extract final AI response, capped to the tier's return budget
        # (ARCH-18 #4 Round 40).
        cap = _resolve_subagent_cap()
        messages = result.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if content and isinstance(content, str):
                return _truncate(content, cap)
            if content and isinstance(content, list):
                # Anthropic structured content blocks
                text_parts = [
                    b.get("text", "") for b in content if isinstance(b, dict)
                ]
                combined = "\n".join(p for p in text_parts if p)
                if combined:
                    return _truncate(combined, cap)

        return f"Subagent '{subagent_name}' completed with no text output."

    return olav_delegate
