"""Harness profile for gemma4:* model family (Ollama / OpenAI-compat).

Targets the local-deployment small-model adherence patterns OLAV has
been working around since R88-A (dev_docs/77).  Encodes them as a
declarative ``HarnessProfile`` instead of scattered ``if`` branches.

What the profile encodes
------------------------

1. **Excluded auto-tools** — deepagents injects ``write_todos``,
   ``ls``, ``grep``, ``read_file``, ``write_file``, ``edit_file``,
   ``execute`` via ``TodoListMiddleware`` + ``FilesystemMiddleware``.
   On gemma4:31b these cause the well-known "plan-loop tail" where
   the model calls ``read_file`` post-task to "verify" its own output.
   The orchestrator already prunes them post-compile via
   ``_prune_graph_tools`` (``agent.py``).  Profile-level exclusion is
   a stricter belt: the model never even SEES the tools, so it can't
   bias toward them.

2. **System-prompt suffix** — small-model tool-call discipline:
   one tool call per turn, no parallel, no "thinking out loud" before
   the call, no post-tool-result recapitulation.

3. **TodoListMiddleware exclude** — same reasoning as (1) but the
   middleware also drives ``write_todos`` tool registration.  Letting
   it run wastes the model's first turn on TODO-plan ceremony.

What the profile does NOT touch (yet)
-------------------------------------

- Summarization middleware: tier-aware threshold (50%/65%/80%) is
  already handled in ``agent.py:_summ = build_summarization_middleware
  (tier=_tier)``.  Folding it in is P1.3.
- AnthropicPromptCachingMiddleware: only meaningful for Anthropic
  models; gemma4 doesn't use it.

Scope caveat
------------

deepagents 0.5.4's profile applies to the **main agent**, the
**auto-added general-purpose subagent**, and **declarative SubAgent
dicts**.  It does NOT apply to ``CompiledSubAgent`` — OLAV's
sub-agents are pre-compiled (``runnable=create_agent(...)``) and
opaque to profile injection.  So this profile shapes the
*orchestrator* only; per-sub-agent discipline still lives in
``agent.py:1024-1099``.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_SUFFIX = """\
## Local Small-Model Discipline (gemma4 family)

- Make **one** tool call per turn.  Do not batch parallel tool calls
  even when the framework would allow it — the local model's
  parallel-tool reasoning is unreliable.
- Do not narrate what you are about to do.  Pick the tool, call it,
  read the result, decide the next step.  Brief inner monologue is
  fine; multi-paragraph plans before action are not.
- After a tool returns, do not echo or paraphrase the result back to
  the user.  Use it to drive the next decision.  The CLI prints tool
  outputs directly.
- Stay strictly inside the tools you were given.  If you reach for a
  tool that is not in your list, the orchestrator will not accept it
  — pick a different path.
- When the task is complete, emit a short final answer (1-3 lines)
  and stop.  Do not invent follow-up checks the user did not ask for.
"""


# Tools deepagents middleware auto-injects that gemma4 reaches for
# unprompted.  All seven are pruned post-compile today via
# ``_DEEPAGENTS_INJECT_TOOLS`` in ``agent.py``; the profile makes the
# exclusion declarative + visible to the model at compile time.
_GEMMA4_EXCLUDED_TOOLS = frozenset({
    "write_todos",
    "ls",
    "glob",
    "grep",
    "read_file",
    "write_file",
    "edit_file",
    "execute",
})


# Model specs to bind this profile to.
#
# Profile keys MUST be ``provider`` or ``provider:model`` — deepagents
# rejects keys with more than one ``:``.  Ollama-style model identifiers
# (``gemma4:31b`` = name:tag) have their own colon, so the canonical
# ``provider:model`` form would be ``openai:gemma4:31b`` which has two
# colons and is rejected at registration time.
#
# Workaround: register under the **bare identifier** (one colon) — the
# resolver's identifier-only fallback (`_harness_profile_for_model`
# line 1291) matches the model when its ``model_dump`` identifier equals
# the key.  Works for both OpenAI-compat (model_name = ``gemma4:31b``)
# and an eventual native Ollama provider (identifier still
# ``gemma4:31b``).
_GEMMA4_MODEL_SPECS: tuple[str, ...] = (
    "gemma4:31b",   # current production tag (Ollama)
    "gemma4:9b",    # potential lighter variant
    "gemma4:27b",   # mid-tier variant
)


def register() -> None:
    """Register the gemma4 family harness profile with deepagents.

    Called from :func:`olav.agents.profiles.register_olav_profiles`.
    Safe to call multiple times — re-registration merges on top per
    deepagents 0.5.4 semantics.
    """
    from deepagents.profiles import (
        HarnessProfile,
        register_harness_profile,
    )

    profile = HarnessProfile(
        system_prompt_suffix=_SYSTEM_PROMPT_SUFFIX,
        excluded_tools=_GEMMA4_EXCLUDED_TOOLS,
        excluded_middleware=frozenset({"TodoListMiddleware"}),
    )
    for spec in _GEMMA4_MODEL_SPECS:
        register_harness_profile(spec, profile)
    logger.debug(
        "✓ gemma4 harness profile bound to %s",
        ", ".join(_GEMMA4_MODEL_SPECS),
    )
