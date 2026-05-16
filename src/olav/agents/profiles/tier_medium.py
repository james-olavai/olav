"""Harness profile for medium-tier models (13B-34B class, mixtral, mistral-small).

Medium models exhibit a subset of small-tier issues — they still
narrate before tool calls and occasionally batch unreliably — but
their context budgets are roomier (~32K vs 8K) and they handle
``write_todos`` / file operations more reliably than the 7B-8B class.

The profile here is therefore **lighter than tier_small**:
* Keeps ``write_todos`` and filesystem tools (the model uses them
  competently).
* System-prompt suffix still asks for one-tool-per-turn discipline
  (parallel tool reasoning is still flaky in this class).
* No middleware exclusions — TodoListMiddleware adds value for
  multi-step tasks at this tier.

Tier classification source of truth:
``olav.core.config._TIER_REGEX_MEDIUM`` (13b / 14b / 22b / 32b / 34b
/ mixtral / mistral-small).

See ``tier_small.py`` for the scope caveat about CompiledSubAgent.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_SUFFIX = """\
## Medium Local-Model Discipline

- Prefer **one** tool call per turn unless two operations are
  genuinely independent and both results are needed before deciding
  the next step.
- Keep pre-action narration to one sentence ("I'm checking X").
  Multi-paragraph PLAN blocks are wasteful at this tier.
- After a tool returns, do not paraphrase the result back to the
  user; act on it.
- When the task is complete, emit a concise final answer (3-5
  lines max for typical tasks) and stop.
"""


# Concrete spec strings to bind the profile to.  Add new medium-tier
# models by extending this list; tier classification logic in
# ``olav.core.config._TIER_REGEX_MEDIUM`` is the source of truth for
# "is this model medium?".
_MEDIUM_MODEL_SPECS: tuple[str, ...] = (
    "qwen3.6:27b",
    "qwen2.5:14b",
    "qwen2.5:32b",
    "mixtral:8x7b",
    "mistral-small",
)


def register() -> None:
    """Register the medium-tier harness profile with deepagents.

    Called from :func:`olav.agents.profiles.register_olav_profiles`.
    """
    from deepagents.profiles import (
        HarnessProfile,
        register_harness_profile,
    )

    profile = HarnessProfile(
        system_prompt_suffix=_SYSTEM_PROMPT_SUFFIX,
    )
    for spec in _MEDIUM_MODEL_SPECS:
        register_harness_profile(spec, profile)
    logger.debug(
        "✓ medium-tier harness profile bound to %d model specs",
        len(_MEDIUM_MODEL_SPECS),
    )
