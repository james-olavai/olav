"""
tests/unit/test_tool_loader.py
──────────────────────────────
Unit coverage for :mod:`olav.server.tool_loader` (P2 cycles 1+2).

The loader discovers workspace-local Python tools from either the
legacy ``.olav/workspace/<n>/`` layout or the new
``.deepagents/agents/<n>/`` layout, and returns a flat
``list[BaseTool]`` suitable for passing to
``create_deep_agent(tools=...)``.

Design under test:

* Layout enum: ``legacy`` or ``new`` — auto-detected when not
  specified.
* Tool sources per agent:
    - ``<agent>/tools/*.py``                   (agent-level tools)
    - ``<agent>/<skill>/tools/*.py``           (legacy: skill nested
                                                under agent dir)
    - ``<agent>/skills/<skill>/tools/*.py``    (new: skills/ subdir)
    - ``<agent>/agents/<sub>/tools/*.py``      (new: subagent tools)
* Missing directories are skipped silently (no crash on partial
  installs).
* Wrapped around :func:`olav.core.tool_discovery.discover_tools` — no
  duplicate import machinery.

The tests drive the loader with synthetic tmp directories + a spy
on ``discover_tools`` so we never actually import Python modules or
require @tool-decorated functions.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ── Test doubles ───────────────────────────────────────────────────────────


class _ToolMarker:
    """Stand-in for a LangChain BaseTool — only name is used in
    assertions."""

    def __init__(self, name: str) -> None:
        self.name = name


def _make_legacy_tree(root: Path) -> None:
    """Create .olav/workspace/ with tools scattered in the legacy
    pattern."""
    ws = root / ".olav" / "workspace"
    for agent in ("core", "ops"):
        d = ws / agent / "tools"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{agent}_tool.py").write_text("# stub\n", encoding="utf-8")
    # Legacy: skill as sibling dir under agent
    skill_tools = ws / "core" / "writer" / "tools"
    skill_tools.mkdir(parents=True, exist_ok=True)
    (skill_tools / "writer_tool.py").write_text("# stub\n", encoding="utf-8")


def _make_new_tree(root: Path) -> None:
    """Create .deepagents/agents/ with tools scattered in the new
    pattern."""
    agents = root / ".deepagents" / "agents"
    for agent in ("core", "ops"):
        # Top-level tools
        d = agents / agent / "tools"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{agent}_tool.py").write_text("# stub\n", encoding="utf-8")
    # New: skill under skills/<name>/
    skill_tools = agents / "core" / "skills" / "writer" / "tools"
    skill_tools.mkdir(parents=True, exist_ok=True)
    (skill_tools / "writer_tool.py").write_text("# stub\n", encoding="utf-8")
    # New: subagent tools under agents/<sub>/tools/
    sub_tools = agents / "core" / "agents" / "analysis" / "tools"
    sub_tools.mkdir(parents=True, exist_ok=True)
    (sub_tools / "analysis_tool.py").write_text("# stub\n", encoding="utf-8")


@pytest.fixture
def spy_discover(monkeypatch: pytest.MonkeyPatch):
    """Replace the underlying ``discover_tools`` so tests don't have
    to write real @tool-decorated modules."""
    calls: list[Path] = []

    def _fake_discover(tools_path: Path, modules=None):
        calls.append(tools_path)
        # Return one marker per file in the directory so tests can
        # assert "did the loader find this dir?" by counting.
        return [
            _ToolMarker(f"{tools_path.name}:{p.stem}")
            for p in tools_path.glob("*.py")
            if p.name != "__init__.py"
        ]

    monkeypatch.setattr("olav.core.tool_discovery.discover_tools", _fake_discover)
    return calls


# ── 1. Module importable ────────────────────────────────────────────────────


def test_module_importable() -> None:
    from olav.server import tool_loader

    assert hasattr(tool_loader, "load_tools_for_agent")
    assert hasattr(tool_loader, "detect_layout")


# ── 2. Auto-detect layout ──────────────────────────────────────────────────


def test_detect_layout_legacy(tmp_path: Path) -> None:
    from olav.server.tool_loader import detect_layout

    _make_legacy_tree(tmp_path)
    assert detect_layout(tmp_path) == "legacy"


def test_detect_layout_new(tmp_path: Path) -> None:
    from olav.server.tool_loader import detect_layout

    _make_new_tree(tmp_path)
    assert detect_layout(tmp_path) == "new"


def test_detect_layout_both_prefers_new(tmp_path: Path) -> None:
    """When both layouts coexist (partial migration), 'new' wins —
    matches plan_migration's idempotence rule."""
    from olav.server.tool_loader import detect_layout

    _make_legacy_tree(tmp_path)
    _make_new_tree(tmp_path)
    assert detect_layout(tmp_path) == "new"


def test_detect_layout_none(tmp_path: Path) -> None:
    """Empty dir → 'new' (fresh project gets the new layout default)."""
    from olav.server.tool_loader import detect_layout

    assert detect_layout(tmp_path) == "new"


# ── 3. Legacy layout: scan .olav/workspace/<n>/tools + skill/tools ────────


def test_load_tools_legacy_agent_only(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    from olav.server.tool_loader import load_tools_for_agent

    _make_legacy_tree(tmp_path)
    tools = load_tools_for_agent("ops", layout="legacy", root=tmp_path)

    assert len(tools) == 1
    assert tools[0].name == "tools:ops_tool"
    # Only the agent's own tools dir scanned
    assert len(spy_discover) == 1
    assert spy_discover[0].name == "tools"


def test_load_tools_legacy_with_skill(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    from olav.server.tool_loader import load_tools_for_agent

    _make_legacy_tree(tmp_path)
    tools = load_tools_for_agent("core", layout="legacy", root=tmp_path)

    # Expect: core/tools/core_tool.py + core/writer/tools/writer_tool.py
    tool_names = sorted(t.name for t in tools)
    assert tool_names == ["tools:core_tool", "tools:writer_tool"]
    assert len(spy_discover) == 2


def test_load_tools_legacy_missing_agent(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    from olav.server.tool_loader import load_tools_for_agent

    # Agent doesn't exist — must not crash
    tools = load_tools_for_agent("nonexistent", layout="legacy", root=tmp_path)
    assert tools == []
    assert spy_discover == []  # never even called discover


# ── 4. New layout: scan agent + skills/*/tools + agents/<sub>/tools ───────


def test_load_tools_new_agent_only(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    from olav.server.tool_loader import load_tools_for_agent

    _make_new_tree(tmp_path)
    tools = load_tools_for_agent("ops", layout="new", root=tmp_path)
    assert len(tools) == 1
    assert tools[0].name == "tools:ops_tool"


def test_load_tools_new_with_skill_and_subagent(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    from olav.server.tool_loader import load_tools_for_agent

    _make_new_tree(tmp_path)
    tools = load_tools_for_agent("core", layout="new", root=tmp_path)

    # core/tools/core_tool.py + core/skills/writer/tools/writer_tool.py
    # + core/agents/analysis/tools/analysis_tool.py
    tool_names = sorted(t.name for t in tools)
    assert tool_names == [
        "tools:analysis_tool",
        "tools:core_tool",
        "tools:writer_tool",
    ]


def test_load_tools_new_missing_skill_dir(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    """Agent exists with top-level tools but no skills/ subdir — must
    not crash."""
    from olav.server.tool_loader import load_tools_for_agent

    root = tmp_path
    agent_tools = root / ".deepagents" / "agents" / "core" / "tools"
    agent_tools.mkdir(parents=True, exist_ok=True)
    (agent_tools / "bare.py").write_text("# stub\n", encoding="utf-8")

    tools = load_tools_for_agent("core", layout="new", root=root)
    assert len(tools) == 1


# ── 5. Layout defaults to auto-detect when omitted ────────────────────────


def test_load_tools_auto_detect_legacy(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    from olav.server.tool_loader import load_tools_for_agent

    _make_legacy_tree(tmp_path)
    tools = load_tools_for_agent("ops", root=tmp_path)  # no layout arg
    assert len(tools) == 1


def test_load_tools_auto_detect_new(
    tmp_path: Path, spy_discover: list[Path]
) -> None:
    from olav.server.tool_loader import load_tools_for_agent

    _make_new_tree(tmp_path)
    tools = load_tools_for_agent("ops", root=tmp_path)
    assert len(tools) == 1
