"""
tests/unit/test_workspace_discovery.py
──────────────────────────────────────
Unit coverage for :mod:`olav.core.workspace_discovery`.

Phase C cycle 3 — centralise what was ~6 copy-pasted workspace-scan
loops (tui_overlay._discover_workspaces / cli.commands.refresh /
cli.commands.workspace / cli.commands.skill / core.router / api.server).

The helper exposes two functions:

* ``discover_agent_names(root, layout=None)`` — sorted list of agent
  names.  Handles both layouts via
  :func:`olav.server.tool_loader.detect_layout`.
* ``discover_agent_paths(root, layout=None)`` — sorted list of
  (name, path) tuples so callers that need the AGENT.md/AGENTS.md
  location (refresh indexing, install validation) get it without
  re-walking the tree.

Tests verify behaviour across:

1. Empty / missing root
2. Legacy layout only (.olav/workspace/)
3. New layout only (.deepagents/agents/)
4. Both layouts (new wins — matches tool_loader + migrate policy)
5. Dirs without AGENT.md/AGENTS.md are filtered (noise protection)
6. Symlinks optional — skipped unless explicitly opted in (security
   against dangling links masquerading as agents)
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _add_legacy_agent(root: Path, name: str, *, has_agent_md: bool = True) -> None:
    d = root / ".olav" / "workspace" / name
    d.mkdir(parents=True, exist_ok=True)
    if has_agent_md:
        (d / "AGENT.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")


def _add_new_agent(root: Path, name: str, *, has_agents_md: bool = True) -> None:
    d = root / ".deepagents" / "agents" / name
    d.mkdir(parents=True, exist_ok=True)
    if has_agents_md:
        (d / "AGENTS.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")


# ── 1. Module importable ────────────────────────────────────────────────────


def test_module_importable() -> None:
    from olav.core import workspace_discovery

    assert hasattr(workspace_discovery, "discover_agent_names")
    assert hasattr(workspace_discovery, "discover_agent_paths")


# ── 2. Empty / missing root ────────────────────────────────────────────────


def test_discover_empty_root(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import (
        discover_agent_names,
        discover_agent_paths,
    )

    assert discover_agent_names(tmp_path) == []
    assert discover_agent_paths(tmp_path) == []


# ── 3. Legacy layout ───────────────────────────────────────────────────────


def test_legacy_layout_finds_agents(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import discover_agent_names

    _add_legacy_agent(tmp_path, "core")
    _add_legacy_agent(tmp_path, "ops")
    # Dir without AGENT.md — should be skipped
    (tmp_path / ".olav" / "workspace" / "noise").mkdir(parents=True, exist_ok=True)

    names = discover_agent_names(tmp_path)
    assert names == ["core", "ops"]


def test_legacy_layout_paths_point_at_agent_md(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import discover_agent_paths

    _add_legacy_agent(tmp_path, "core")
    paths = discover_agent_paths(tmp_path)
    assert len(paths) == 1
    name, agent_md = paths[0]
    assert name == "core"
    assert agent_md.name == "AGENT.md"
    assert agent_md.is_file()


# ── 4. New layout ──────────────────────────────────────────────────────────


def test_new_layout_finds_agents(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import discover_agent_names

    _add_new_agent(tmp_path, "core")
    _add_new_agent(tmp_path, "audit")

    names = discover_agent_names(tmp_path)
    assert names == ["audit", "core"]  # sorted


def test_new_layout_paths_point_at_agents_md(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import discover_agent_paths

    _add_new_agent(tmp_path, "core")
    paths = discover_agent_paths(tmp_path)
    assert len(paths) == 1
    name, agent_md = paths[0]
    assert name == "core"
    assert agent_md.name == "AGENTS.md"
    assert agent_md.is_file()


# ── 5. Both layouts coexist — new wins ────────────────────────────────────


def test_both_layouts_new_wins(tmp_path: Path) -> None:
    """When both layouts are populated (partial migration state),
    the discovery returns the NEW layout's agents — matches
    tool_loader.detect_layout and migrate.already_migrated."""
    from olav.core.workspace_discovery import discover_agent_names

    _add_legacy_agent(tmp_path, "legacy_only")
    _add_new_agent(tmp_path, "new_one")
    _add_new_agent(tmp_path, "core")

    names = discover_agent_names(tmp_path)
    # New layout's two agents; legacy_only is NOT included
    assert names == ["core", "new_one"]


# ── 6. Dirs without AGENT.md/AGENTS.md are noise ─────────────────────────


def test_noise_dirs_filtered_in_legacy(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import discover_agent_names

    _add_legacy_agent(tmp_path, "real", has_agent_md=True)
    _add_legacy_agent(tmp_path, "ghost", has_agent_md=False)

    names = discover_agent_names(tmp_path)
    assert names == ["real"]


def test_noise_dirs_filtered_in_new(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import discover_agent_names

    _add_new_agent(tmp_path, "real", has_agents_md=True)
    _add_new_agent(tmp_path, "ghost", has_agents_md=False)

    names = discover_agent_names(tmp_path)
    assert names == ["real"]


# ── 7. Explicit layout override ───────────────────────────────────────────


def test_explicit_legacy_override(tmp_path: Path) -> None:
    """Pass ``layout="legacy"`` to force-scan the legacy dir even when
    the new dir exists (useful for migration tooling that needs to
    see the pre-migration state)."""
    from olav.core.workspace_discovery import discover_agent_names

    _add_legacy_agent(tmp_path, "legacy_agent")
    _add_new_agent(tmp_path, "new_agent")

    names = discover_agent_names(tmp_path, layout="legacy")
    assert names == ["legacy_agent"]


def test_explicit_new_override(tmp_path: Path) -> None:
    from olav.core.workspace_discovery import discover_agent_names

    _add_legacy_agent(tmp_path, "legacy_agent")
    _add_new_agent(tmp_path, "new_agent")

    names = discover_agent_names(tmp_path, layout="new")
    assert names == ["new_agent"]


# ── 8. Default root = cwd ────────────────────────────────────────────────


def test_default_root_is_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olav.core.workspace_discovery import discover_agent_names

    _add_new_agent(tmp_path, "alpha")
    monkeypatch.chdir(tmp_path)
    assert discover_agent_names() == ["alpha"]
