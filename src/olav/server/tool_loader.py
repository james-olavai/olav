"""Workspace-local Python tool loader for OLAV agents.

Phase B (v0.20.2) P2 cycle 1.  Factors out the tool-discovery side of
:class:`olav.agents.agent.OLAVAgent` so:

1. The LangGraph subprocess (via :mod:`olav.server.graph_factory`)
   can assemble the same tool list without needing the full
   ``OLAVAgent`` construction.
2. Both the legacy (``.olav/workspace/``) and new
   (``.deepagents/agents/``) directory layouts are supported from a
   single entry point — the mode is auto-detected when not given.
3. Filesystem-shape knowledge is centralised; other modules call
   :func:`load_tools_for_agent` instead of hand-rolling tool dir
   paths.

Discovery shapes
----------------
==============  =========================================================
Layout          Tool dirs scanned per agent
==============  =========================================================
legacy          ``.olav/workspace/<agent>/tools/``
                ``.olav/workspace/<agent>/<skill>/tools/`` (for each
                child dir with its own ``SKILL.md``)
new             ``.deepagents/agents/<agent>/tools/``
                ``.deepagents/agents/<agent>/skills/<skill>/tools/``
                ``.deepagents/agents/<agent>/agents/<sub>/tools/``
==============  =========================================================

Missing directories are skipped — partial installs don't crash the
loader.  The underlying import work is delegated to
:func:`olav.core.tool_discovery.discover_tools`; this module only
decides *which* directories to hand it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

Layout = Literal["legacy", "new"]

_LEGACY_ROOT = Path(".olav") / "workspace"
_NEW_ROOT = Path(".deepagents") / "agents"


def detect_layout(root: Path) -> Layout:
    """Return the workspace layout in use at *root*.

    Rules:
      * ``.deepagents/agents/`` present (and non-empty) → ``"new"``
      * Only ``.olav/workspace/`` present → ``"legacy"``
      * Both present (partial migration) → ``"new"``.  Matches
        :func:`olav.migrate.v0_20_layout.already_migrated`'s rule so
        the loader and the migration planner agree on what "done"
        looks like.
      * Neither present → ``"new"`` so fresh ``olav init`` calls set
        up the new layout.
    """
    new_root = root / _NEW_ROOT
    if new_root.is_dir() and any(p.is_dir() for p in new_root.iterdir()):
        return "new"
    if (root / _LEGACY_ROOT).is_dir():
        return "legacy"
    return "new"


def load_tools_for_agent(
    agent_name: str,
    *,
    layout: Layout | None = None,
    root: Path | None = None,
) -> list[Any]:
    """Return the tool list for *agent_name* in the given workspace.

    Args:
        agent_name: The top-level agent to load tools for.
        layout: Explicit layout to use.  When ``None``, auto-detects
            via :func:`detect_layout`.
        root: Project root.  Defaults to ``Path.cwd()``.

    Returns:
        A flat list of LangChain-compatible tool objects (typed as
        ``Any`` to avoid pulling langchain_core into this module's
        import graph — test doubles can be plain stubs).  Empty list
        when the agent doesn't exist or has no tools.
    """
    root = (root or Path.cwd()).resolve()
    layout = layout or detect_layout(root)

    if layout == "new":
        tool_dirs = _new_layout_tool_dirs(root, agent_name)
    else:
        tool_dirs = _legacy_layout_tool_dirs(root, agent_name)

    # Lazy import so tests can monkey-patch this symbol before the
    # loader is called.  Without ``import ... as`` here, the lookup
    # would be bound at module-load and survive monkey-patching.
    from olav.core import tool_discovery

    collected: list[Any] = []
    for tools_path in tool_dirs:
        if not tools_path.is_dir():
            continue
        try:
            discovered = tool_discovery.discover_tools(tools_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "tool_loader: discover_tools(%s) failed: %s", tools_path, exc
            )
            continue
        collected.extend(discovered)
    return collected


def _new_layout_tool_dirs(root: Path, agent_name: str) -> list[Path]:
    """Enumerate tool directories for *agent_name* under the new layout.

    Order matters — agent-level tools first (most specific context),
    then skills, then subagents.  Some downstream tool deduplication
    paths rely on first-occurrence-wins semantics.
    """
    agent_dir = root / _NEW_ROOT / agent_name
    if not agent_dir.is_dir():
        return []

    dirs: list[Path] = []

    # 1. Agent's own tools
    dirs.append(agent_dir / "tools")

    # 2. Per-skill tools under skills/<name>/tools
    skills_root = agent_dir / "skills"
    if skills_root.is_dir():
        for skill_dir in sorted(skills_root.iterdir()):
            if skill_dir.is_dir():
                dirs.append(skill_dir / "tools")

    # 3. Per-subagent tools under agents/<sub>/tools
    subagents_root = agent_dir / "agents"
    if subagents_root.is_dir():
        for sub_dir in sorted(subagents_root.iterdir()):
            if sub_dir.is_dir():
                dirs.append(sub_dir / "tools")

    return dirs


def _legacy_layout_tool_dirs(root: Path, agent_name: str) -> list[Path]:
    """Enumerate tool directories for *agent_name* under the legacy
    (.olav/workspace/) layout.

    Legacy pattern:
      * ``<agent>/tools/``           — agent-level
      * ``<agent>/<skill>/tools/``   — skill nested as sibling dir
        (detected by ``SKILL.md`` presence in the sibling dir)
    """
    agent_dir = root / _LEGACY_ROOT / agent_name
    if not agent_dir.is_dir():
        return []

    dirs: list[Path] = [agent_dir / "tools"]

    for child in sorted(agent_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name == "tools":
            continue  # already included above
        # Consider this a skill-or-subagent if it has SKILL.md or
        # AGENT.md — both drag along a tools/ dir in practice.
        if (child / "SKILL.md").is_file() or (child / "AGENT.md").is_file():
            dirs.append(child / "tools")
            continue
        # Or, more tolerantly, any child dir that ships a tools/.
        if (child / "tools").is_dir():
            dirs.append(child / "tools")

    return dirs


__all__ = [
    "Layout",
    "detect_layout",
    "load_tools_for_agent",
]
