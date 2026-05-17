"""Single source of truth for "which agents are installed?".

Before Phase C, ~6 modules independently walked a workspace tree to
answer this question:

* ``olav.cli.tui_overlay._discover_workspaces``
* ``olav.cli.commands.refresh``
* ``olav.cli.commands.workspace``
* ``olav.cli.commands.skill`` (uninstall path)
* ``olav.core.router`` (Tier-2 fallback)
* ``olav.api.server`` (``/agents`` endpoint, deleted in v0.11.0)

Each had subtly different logic: some returned just names, some
returned ``(name, dir)``, some filtered by ``AGENT.md`` presence, some
didn't.  None of them knew about the v0.20.2 ``.deepagents/agents/``
layout.

This module consolidates the pattern.  Call sites migrate to
:func:`discover_agent_names` (names only) or
:func:`discover_agent_paths` (name + agent-definition file path),
both of which transparently handle legacy and new layouts via
:func:`olav.server.tool_loader.detect_layout`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Layout = Literal["legacy", "new"]

_LEGACY_ROOT = Path(".olav") / "workspace"
_NEW_ROOT = Path(".deepagents") / "agents"
_LEGACY_MARKER = "AGENT.md"
_NEW_MARKER = "AGENTS.md"


def discover_agent_names(
    root: Path | None = None,
    *,
    layout: Layout | None = None,
) -> list[str]:
    """Return the sorted list of installed agent names.

    Args:
        root: Project root.  Defaults to :func:`Path.cwd`.
        layout: Force a specific layout.  When ``None``, auto-detects
            via :func:`olav.server.tool_loader.detect_layout`
            (new-wins when both present, matches
            :func:`olav.migrate.v0_20_layout.already_migrated`).

    Returns:
        Sorted list of agent directory names (e.g.
        ``["audit", "core", "ops"]``).
    """
    return [name for name, _ in discover_agent_paths(root, layout=layout)]


def discover_agent_paths(
    root: Path | None = None,
    *,
    layout: Layout | None = None,
) -> list[tuple[str, Path]]:
    """Return sorted ``(name, agent_definition_file)`` pairs.

    The second element is the path to ``AGENT.md`` (legacy) or
    ``AGENTS.md`` (new) — callers that want to read frontmatter
    or assert file presence get it without walking the tree twice.

    Args:
        root: Project root.  Defaults to :func:`Path.cwd`.
        layout: See :func:`discover_agent_names`.

    Returns:
        Sorted list of ``(name, path)`` tuples.  Dirs without the
        layout's marker file (``AGENT.md`` / ``AGENTS.md``) are
        filtered — noise protection against partially-removed
        agents or unrelated subdirs.
    """
    root = (root or Path.cwd()).resolve()

    effective_layout = layout or _detect_layout(root)
    if effective_layout == "new":
        base = root / _NEW_ROOT
        marker = _NEW_MARKER
    else:
        base = root / _LEGACY_ROOT
        marker = _LEGACY_MARKER

    if not base.is_dir():
        return []

    pairs: list[tuple[str, Path]] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        agent_def = entry / marker
        if not agent_def.is_file():
            continue
        pairs.append((entry.name, agent_def))
    return pairs


def _detect_layout(root: Path) -> Layout:
    """Layout auto-detection.

    Thin wrapper over :func:`olav.server.tool_loader.detect_layout`
    so this module doesn't accidentally drift from tool_loader's
    decision.  Imported lazily because tool_loader pulls langchain —
    keeps ``import olav.core.workspace_discovery`` cheap.
    """
    try:
        from olav.server.tool_loader import detect_layout

        tl_layout = detect_layout(root)
        # tool_loader.Layout is 'legacy' | 'new' — matches ours.
        return tl_layout  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "workspace_discovery: tool_loader.detect_layout failed (%s); "
            "falling back to explicit probe",
            exc,
        )
        # Fallback matches the policy: new wins when both present.
        new_root = root / _NEW_ROOT
        if new_root.is_dir() and any(p.is_dir() for p in new_root.iterdir()):
            return "new"
        if (root / _LEGACY_ROOT).is_dir():
            return "legacy"
        return "new"


__all__ = [
    "Layout",
    "discover_agent_names",
    "discover_agent_paths",
]
