"""Harness profile for small-tier local models (gemma / phi-3 / qwen-7b / llama-3.1-8b / mistral-7b family).

The discipline encoded here is **NOT gemma4-specific** — it's the
adherence pattern that every <=8B-class local model exhibits under
deepagents' default tool injection:

* Reaches for ``write_todos`` / ``ls`` / ``read_file`` even when
  not needed (the "plan-loop tail" — see R88-A / R89 / R90 in
  dev_docs/73).
* Generates multi-paragraph PLAN narratives before issuing the
  next tool call, burning context budget on prose.
* Batches parallel tool calls unreliably.

OLAV already classifies models into small / medium / large tiers
via ``olav.core.config._TIER_REGEX_SMALL`` (matches ``gemma`` /
``phi-3`` / ``7b`` / ``8b`` etc.).  This profile is registered
against the concrete spec strings of the small-tier models we
expect to see; adding a new small model means adding one line to
``_SMALL_MODEL_SPECS`` below.

Scope caveat (inherited from deepagents 0.5.4):
    ``HarnessProfile.extra_middleware`` does NOT apply to
    ``CompiledSubAgent``.  OLAV sub-agents are pre-compiled
    (``runnable=create_agent(...)``) and opaque to profile
    injection.  This profile shapes the **orchestrator** only;
    per-sub-agent discipline still lives in ``agent.py:1024-1099``
    (post-compile ``_prune_graph_tools``).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_SUFFIX = """\
## Small Local-Model Discipline

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


# Tools deepagents middleware auto-injects that small models reach for
# unprompted.  All eight are also pruned post-compile by
# ``_DEEPAGENTS_INJECT_TOOLS`` in ``agent.py``; profile-level exclusion
# is the belt, post-compile prune is the suspenders.
_SMALL_TIER_EXCLUDED_TOOLS = frozenset({
    "write_todos",
    "ls",
    "glob",
    "grep",
    "read_file",
    "write_file",
    "edit_file",
    "execute",
})


# Concrete spec strings to bind the profile to.  Profile keys must be
# ``provider`` or ``provider:model`` — deepagents rejects more than
# one colon.  Ollama-style ``name:tag`` identifiers ARE one colon, so
# we register under the bare identifier and rely on deepagents'
# identifier-only resolver fallback
# (``_harness_profile_for_model`` lines 1284-1296).
#
# Adding a new small model: append one line here.  Tier classification
# in ``olav.core.config._TIER_REGEX_SMALL`` is the source of truth for
# "is this model small?"; this list mirrors the concrete tags OLAV
# expects to actually load.
_SMALL_MODEL_SPECS: tuple[str, ...] = (
    # gemma family — Ollama tag form (name:tag)
    "gemma4:31b",
    "gemma4:27b",
    "gemma4:9b",
    "gemma4:e2b",
    "gemma:2b",
    # gemma family — llama.cpp / OpenAI-compat form (hyphenated id, no
    # colon in model name → register under provider:model since the
    # resolver tries ``f"{provider}:{identifier}"`` first).
    "openai:gemma4-31b-it",
    "openai:gemma4-9b-it",
    # gemma family — gguf quantised form served via llama.cpp server
    # (OpenAI-compat endpoint; model_provider=openai from LangChain's view).
    # Add gguf variants here as new quantisations are used in production.
    # Naming convention: <family>-<size>-<variant>-<quant>.gguf
    "openai:gemma-4-31b-it-Q4_K_M.gguf",
    "openai:gemma-4-31b-it-Q8_0.gguf",
    "openai:gemma-4-27b-it-Q4_K_M.gguf",
    "openai:gemma-4-27b-it-Q8_0.gguf",
    "openai:gemma-4-9b-it-Q4_K_M.gguf",
    "openai:gemma-4-9b-it-Q8_0.gguf",
    # phi-3 family
    "phi-3:mini",
    "phi-3:medium",
    # llama family
    "llama-3.1:8b",
    "llama-3.2:3b",
    # qwen family (≤8B variants)
    "qwen2.5:7b",
    # haiku — Anthropic's small tier (per _TIER_REGEX_SMALL)
    "haiku-4-5",
    "claude-haiku-4-5",
    # grok-4.1-fast — OpenRouter, classified small (capability-overlay
    # for Azure-bypass routing lives in grok_overlay.py when added).
    "x-ai/grok-4.1-fast",
)


def register() -> None:
    """Register the small-tier harness profile with deepagents.

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
        excluded_tools=_SMALL_TIER_EXCLUDED_TOOLS,
        excluded_middleware=frozenset({"TodoListMiddleware"}),
    )
    for spec in _SMALL_MODEL_SPECS:
        register_harness_profile(spec, profile)
    logger.debug(
        "✓ small-tier harness profile bound to %d model specs",
        len(_SMALL_MODEL_SPECS),
    )
