"""LangGraph graph factory for OLAV agents.

Imported by ``langgraph dev`` / ``langgraph up`` subprocesses via
``langgraph.json``.  The subprocess reads the agent name from the
``DEEPAGENTS_CODE_SERVER_ASSISTANT_ID`` environment variable (set by
deepagents-code when spawning the server) and builds the corresponding
OLAV compiled graph.

Why this module exists (Phase 5, v0.20.0)
-----------------------------------------
This factory lets the OLAV agent tree be consumed by anything that
speaks the langgraph-server protocol:

* ``langgraph dev`` for local debugging
* LangSmith Studio for UI-based tracing
* (starting v0.20.2) the deepagents-code TUI in server-subprocess mode

Until v0.20.2 the TUI still uses the in-process ``agent=<graph>``
path; this module is additive only.  Everything here wraps the
existing :func:`olav.cli.main.create_olav_agent_with_backend` — no
internals are duplicated.

Contract
--------
* Module-level ``graph`` variable whose type is a LangGraph compiled
  graph (langgraph-server requirement).
* ``DEEPAGENTS_CODE_SERVER_ASSISTANT_ID`` read at import time; missing
  or empty → fall back to ``"core"``.
* Unknown agent name → raise :class:`ValueError` loudly so a
  misconfigured subprocess fails fast instead of silently serving the
  wrong graph.
* No interactive I/O (no prompts, no TTY).  The subprocess is headless.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_ASSISTANT_ID = "core"
"""Agent chosen when the env var is unset or empty.  Matches OLAV's
existing CLI default (``olav`` without ``--agent`` picks core)."""

_ENV_ASSISTANT_ID = "DEEPAGENTS_CODE_SERVER_ASSISTANT_ID"
"""Environment variable deepagents-code sets when spawning the
subprocess.  Keeping the name identical avoids adding another knob."""


def build_graph(assistant_id: str | None = None) -> Any:
    """Construct a compiled OLAV graph for *assistant_id*.

    Thin wrapper over
    :func:`olav.cli.main.create_olav_agent_with_backend` so tests can
    pass an assistant_id explicitly instead of manipulating env vars.

    Args:
        assistant_id: Which top-level agent to build — typically
            ``core`` / ``netops`` / ``audit`` / ``devops`` (post
            R-AGENT-HIERARCHY Phase A 2026-05-09).  When
            ``None`` or an empty string, falls back to the
            ``DEEPAGENTS_CODE_SERVER_ASSISTANT_ID`` env var, then to
            ``"core"``.

    Returns:
        A compiled LangGraph object (a ``langgraph.graph.CompiledGraph``
        or subclass).  Typed as ``Any`` because langgraph's type
        aliases shift between 1.x versions and duck-typing at the
        server layer is sufficient.

    Raises:
        ValueError: When the requested agent has no workspace.
            Bubbles the underlying :class:`FileNotFoundError` /
            ``KeyError`` from the workspace resolver as a clear,
            actionable error — better than a silent default.
    """
    candidate = assistant_id if assistant_id is not None else os.environ.get(
        _ENV_ASSISTANT_ID
    )
    name = (candidate or "").strip() or _DEFAULT_ASSISTANT_ID

    # Pre-flight: confirm the workspace actually exists on disk before
    # we drag in the entire OLAV agent stack.  This lets us raise a
    # clean ValueError with an actionable message instead of whatever
    # RuntimeError ``OLAVAgent._load_olav_config`` bubbles up deep in
    # the call chain.
    _validate_workspace(name)

    # Defer the heavy import so merely importing this module during
    # test collection or linting doesn't drag in the whole OLAV agent
    # stack (plugins, checkpointer, LangChain models).
    from olav.cli.main import create_olav_agent_with_backend

    logger.info(
        "Building OLAV graph for assistant_id=%r (env %s=%r)",
        name,
        _ENV_ASSISTANT_ID,
        os.environ.get(_ENV_ASSISTANT_ID, ""),
    )
    # Disable custom checkpointer/store: langgraph_api ≥0.7.100 raises
    # ValueError when the graph carries a custom checkpointer or store —
    # the platform manages persistence itself (in-memory for local dev,
    # Postgres for cloud).  Passing enable_checkpointer=False compiles
    # the graph without them so the server starts cleanly.
    compiled, _backend = create_olav_agent_with_backend(name, enable_checkpointer=False)
    return compiled


def _validate_workspace(name: str) -> None:
    """Raise :class:`ValueError` when *name* isn't an installed agent."""
    from olav.core.workspace import resolve_workspace_path

    try:
        workspace_path = resolve_workspace_path(name)
    except Exception as exc:
        raise ValueError(
            f"No workspace found for agent {name!r}: workspace resolver raised "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not (workspace_path / "AGENT.md").is_file():
        raise ValueError(
            f"No workspace found for agent {name!r}: "
            f"{workspace_path / 'AGENT.md'} does not exist. "
            f"Set {_ENV_ASSISTANT_ID} to one of the installed agents."
        )


# Module-level graph for ``langgraph.json`` to discover.
#
# Evaluated at import time inside the subprocess so the graph is ready
# by the time langgraph-server starts serving ``/health`` and
# ``/threads``.  Deferring to first-request would make failures show
# up as 500s instead of subprocess-start crashes, which is much
# harder to diagnose.
graph = build_graph()

# ---------------------------------------------------------------------------
# Multi-graph factory for native langgraph_api user_router
#
# When langgraph_api is configured with multiple graph entries (one per
# OLAV agent), it calls make_graph(config) on each run request, passing
# config["configurable"]["graph_id"] to identify which agent to use.
# The cache avoids re-building on every request.
# ---------------------------------------------------------------------------

_graph_cache: dict[str, object] = {}


def make_graph(config: dict | None = None) -> object:
    """Return the compiled OLAV graph for the requested graph_id.

    This is the entry point configured in langgraph.json / LANGSERVE_GRAPHS
    for each registered agent name.  The ``graph_id`` key inside
    ``config["configurable"]`` matches the key in the graphs map so
    langgraph_api can route requests to the right agent.

    Args:
        config: LangGraph run config.  ``config["configurable"]["graph_id"]``
            carries the agent name (e.g. "core", "netops", "audit").
            ``None`` or missing key falls back to "core".

    Returns:
        A compiled LangGraph graph object, cached by graph_id.

    Raises:
        ValueError: When the requested agent workspace doesn't exist.
    """
    graph_id = (config or {}).get("configurable", {}).get("graph_id") or _DEFAULT_ASSISTANT_ID
    if graph_id not in _graph_cache:
        # Cache miss — should only happen after /reload before async rebuild completes,
        # or in test/dev scenarios. olav.api.app pre-warms all registered agents at
        # startup so normal request paths never reach here.
        # Warn visibly: if this fires in production it means event-loop blocking I/O
        # is happening and LANGGRAPH_ALLOW_BLOCKING=true would be needed as a fallback.
        logger.warning(
            "make_graph cache miss for graph_id=%r — building synchronously "
            "(blocks event loop). Check that app.py pre-warmed all agents "
            "and that /reload completed its async rebuild before this request.",
            graph_id,
        )
        _graph_cache[graph_id] = build_graph(graph_id)
    return _graph_cache[graph_id]


__all__ = ["build_graph", "graph", "make_graph", "_graph_cache"]
