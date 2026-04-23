# LEGACY-KEEP: the module docstring below references the pre-0b
# "always inject" behaviour as "legacy" — we keep that wording as the
# conservative fallback is still the right default for untiered agents.
"""ARCH-17 P1 — resolve static_context injection mode.

Modes (lowest → highest disclosure):

* ``lazy``     — never push; agents retrieve via ``get_static_context(skill)``
* ``on_intent`` — push only when the router matches the query to the agent
* ``always``   — push at init time (legacy behaviour)

Resolution precedence:

1. ``OLAV_STATIC_CONTEXT_MODE`` env var (operator escape hatch)
2. Agent metadata ``static_context_mode`` key
3. ``TIER_DEFAULTS[<tier>]["static_context_mode"]`` from model_tier
4. ``"always"`` — conservative fallback so legacy agents don't silently
   lose context when the resolver can't make up its mind.

Operator env vars:

* ``OLAV_STATIC_CONTEXT_MODE`` — force a mode (always/on_intent/lazy)
* ``OLAV_DEBUG_CONTEXT=1`` — log per-injection byte/token count vs the
  active tier's ``context_budget`` (useful for prompt-budget
  troubleshooting; see ``is_debug_enabled`` and
  ``olav.agents.agent._debug_log_injection``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_VALID_MODES = frozenset({"always", "on_intent", "lazy"})

# Env override so operators can force a mode without editing agent YAML —
# useful for "prod says something's wrong, flip everyone to always".
_ENV_OVERRIDE = "OLAV_STATIC_CONTEXT_MODE"

# Operator toggle for per-injection debug logging. See module docstring.
_DEBUG_ENV_VAR = "OLAV_DEBUG_CONTEXT"
_DEBUG_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_debug_enabled() -> bool:
    """True when ``OLAV_DEBUG_CONTEXT`` is set to a truthy value.

    Accepted truthy values: ``1`` / ``true`` / ``yes`` / ``on`` (case-insensitive).
    Any other value (unset, empty, ``0``, ``false``, ``foo``) is False.

    When enabled, :func:`olav.agents.agent._inject_static_context` emits an
    INFO-level multi-line summary listing each injected reference's bytes/
    estimated tokens plus the total against the current tier's
    ``context_budget``.
    """
    raw = os.environ.get(_DEBUG_ENV_VAR, "").strip().lower()
    return raw in _DEBUG_TRUTHY


def resolve_mode(agent_metadata: dict[str, Any] | None = None) -> str:
    """Pick the active static_context mode.

    Args:
        agent_metadata: Parsed AGENT.md / SKILL.md frontmatter dict. May
            contain an explicit ``static_context_mode`` key that beats the
            tier inference.

    Returns:
        One of ``"always"``, ``"on_intent"``, or ``"lazy"``.
    """
    # 1. Env-var escape hatch
    env_val = os.environ.get(_ENV_OVERRIDE, "").strip().lower()
    if env_val in _VALID_MODES:
        return env_val

    # 2. Agent frontmatter override
    if agent_metadata:
        explicit = str(agent_metadata.get("static_context_mode") or "").strip().lower()
        if explicit in _VALID_MODES:
            return explicit

    # 3. model_tier default
    try:
        from olav.core.config import get_llm_config, tier_default
        tier = get_llm_config().model_tier
        default = tier_default(tier, "static_context_mode", "always")
        if default in _VALID_MODES:
            return default
    except Exception as exc:  # noqa: BLE001
        logger.debug("static_context tier resolution failed: %s", exc)

    # 4. Conservative fallback
    return "always"


def should_inject(
    mode: str,
    query: str | None = None,
    agent_name: str | None = None,
) -> bool:
    """Decide whether to inject static_context on *this* turn.

    * ``always``    → True (unconditional)
    * ``lazy``      → False (agent pulls via ``get_static_context`` tool)
    * ``on_intent`` → True when the router confidently routes ``query`` to
                      ``agent_name``, False otherwise. On resolver error
                      the function **fails open** (returns True) — it's
                      cheaper to waste a few tokens than to blind the
                      agent on a tough turn.
    """
    if mode == "always":
        return True
    if mode == "lazy":
        return False
    if mode == "on_intent":
        if not query:
            return True  # no query to score → fail open
        return _intent_matches(query, agent_name)
    # Unknown mode string — behave like 'always' so we never silently
    # drop context due to a typo.
    logger.debug("unknown static_context mode %r; treating as 'always'", mode)
    return True


def _intent_matches(query: str, agent_name: str | None) -> bool:
    """True when the semantic router sends ``query`` to ``agent_name``."""
    try:
        from olav.core.router import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("router import failed, falling back to inject: %s", exc)
        return True

    try:
        result = get_router().route(query)
    except Exception as exc:  # noqa: BLE001
        # Router misbehaviour shouldn't blind the agent — fail open.
        logger.debug("router.route failed, falling back to inject: %s", exc)
        return True

    # If no agent_name supplied, inject whenever the router found *any*
    # above-threshold match. This is the "core agent" path.
    if not isinstance(result, dict):
        return True
    routed = result.get("agent")
    confidence = float(result.get("confidence") or 0.0)
    if agent_name is None:
        return confidence >= 0.4
    return routed == agent_name and confidence >= 0.4
