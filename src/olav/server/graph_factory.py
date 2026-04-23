"""LangGraph graph factory for OLAV agents.

Imported by ``langgraph dev`` / ``langgraph up`` subprocesses via
``langgraph.json``.  The subprocess reads the agent name from the
``DEEPAGENTS_CLI_SERVER_ASSISTANT_ID`` environment variable (set by
deepagents-cli when spawning the server) and builds the corresponding
OLAV compiled graph.

Why this module exists (Phase 5, v0.20.0)
-----------------------------------------
This factory lets the OLAV agent tree be consumed by anything that
speaks the langgraph-server protocol:

* ``langgraph dev`` for local debugging
* LangSmith Studio for UI-based tracing
* (starting v0.20.2) the deepagents-cli TUI in server-subprocess mode

Until v0.20.2 the TUI still uses the in-process ``agent=<graph>``
path; this module is additive only.  Everything here wraps the
existing :func:`olav.cli.main.create_olav_agent_with_backend` — no
internals are duplicated.

Contract
--------
* Module-level ``graph`` variable whose type is a LangGraph compiled
  graph (langgraph-server requirement).
* ``DEEPAGENTS_CLI_SERVER_ASSISTANT_ID`` read at import time; missing
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

_ENV_ASSISTANT_ID = "DEEPAGENTS_CLI_SERVER_ASSISTANT_ID"
"""Environment variable deepagents-cli sets when spawning the
subprocess.  Keeping the name identical avoids adding another knob."""


def build_graph(assistant_id: str | None = None) -> Any:
    """Construct a compiled OLAV graph for *assistant_id*.

    Thin wrapper over
    :func:`olav.cli.main.create_olav_agent_with_backend` so tests can
    pass an assistant_id explicitly instead of manipulating env vars.

    Args:
        assistant_id: Which top-level agent to build — typically
            ``core`` / ``ops`` / ``audit`` / ``topology`` /
            ``command_learner`` depending on what's installed.  When
            ``None`` or an empty string, falls back to the
            ``DEEPAGENTS_CLI_SERVER_ASSISTANT_ID`` env var, then to
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
    compiled, _backend = create_olav_agent_with_backend(name)
    return compiled


def _validate_workspace(name: str) -> None:
    """Raise :class:`ValueError` when *name* isn't an installed agent.

    A cheap filesystem check — avoids stripping into OLAVAgent
    construction when the root cause is just a typo.  Respects the
    same resolution order the loader itself uses so aliasing via
    ``resolve_workspace_path`` still works.
    """
    from olav.core.workspace import resolve_workspace_path

    try:
        workspace_path = resolve_workspace_path(name)
    except Exception:  # noqa: BLE001  # resolver may raise anything
        workspace_path = None

    agent_md_exists = (
        workspace_path is not None
        and (workspace_path / "AGENT.md").is_file()
    )
    if not agent_md_exists:
        raise ValueError(
            f"No workspace found for agent {name!r}. "
            f"Set {_ENV_ASSISTANT_ID} to one of the installed agents "
            "(typically: core, ops, audit, topology, command_learner)."
        )


# Module-level graph for ``langgraph.json`` to discover.
#
# Evaluated at import time inside the subprocess so the graph is ready
# by the time langgraph-server starts serving ``/health`` and
# ``/threads``.  Deferring to first-request would make failures show
# up as 500s instead of subprocess-start crashes, which is much
# harder to diagnose.
graph = build_graph()


__all__ = ["build_graph", "graph"]
