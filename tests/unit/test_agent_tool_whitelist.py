"""Tests for Patch D' — SKILL.md ``tools:`` list as registration whitelist.

Verifies the decoupling of "implementation sharing" (one .py in
core/tools/) from "registration scope" (per-agent SKILL.md positively
declares what to register).  Stops every agent auto-inheriting every
core tool — the source of prompt-bloat + wrong-tool-pick on local LLMs.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def _write_tool(tools_dir: Path, name: str) -> Path:
    """Write a stub tool .py file that the discover_tools loader will
    pick up via @tool decorator."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    p = tools_dir / f"{name}.py"
    p.write_text(
        f'''
from langchain_core.tools import tool


@tool
def {name}(arg: str = "") -> str:
    """{name} stub for whitelist testing."""
    return f"{name} ran with {{arg}}"
''',
        encoding="utf-8",
    )
    return p


def _write_skill(skill_path: Path, *, tools: list[str] | None = None,
                 name: str = "test") -> Path:
    """Write a SKILL.md with optional tools field."""
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    if tools is None:
        front = f"""---
name: {name}
description: "test"
---
"""
    elif tools == []:
        # Explicit empty list — must use flow syntax for YAML
        front = f"""---
name: {name}
description: "test"
tools: []
---
"""
    else:
        tools_yaml = "\n".join(f"  - {t}" for t in tools)
        front = f"""---
name: {name}
description: "test"
tools:
{tools_yaml}
---
"""
    skill_path.write_text(front, encoding="utf-8")
    return skill_path


def _make_agent_for_dir(agent_dir: Path):
    """Build a minimally-instantiated AgentRunner-like object for
    testing the helpers."""
    from olav.agents.agent import OLAVAgent
    runner = OLAVAgent.__new__(OLAVAgent)
    runner._agent_dir = agent_dir
    return runner


# ── _read_tools_filter ──────────────────────────────────────────────


def test_read_tools_filter_present_returns_set(tmp_path):
    skill = _write_skill(tmp_path / "SKILL.md", tools=["foo", "bar"])
    runner = _make_agent_for_dir(tmp_path)
    f = runner._read_tools_filter(skill)
    assert f == {"foo", "bar"}


def test_read_tools_filter_empty_list_is_strict_zero(tmp_path):
    """``tools: []`` is "I want zero tools" — filter is empty SET, not None."""
    skill = _write_skill(tmp_path / "SKILL.md", tools=[])
    runner = _make_agent_for_dir(tmp_path)
    f = runner._read_tools_filter(skill)
    assert f == set()  # Not None — empty set means strict-zero


def test_read_tools_filter_missing_returns_none(tmp_path):
    """No ``tools:`` field → None → backward-compat (load all)."""
    skill = _write_skill(tmp_path / "SKILL.md", tools=None)
    runner = _make_agent_for_dir(tmp_path)
    assert runner._read_tools_filter(skill) is None


def test_read_tools_filter_warns_on_dict_entries(tmp_path, caplog):
    """``- path: ./tools/X.py`` dict entries silently produced an
    empty whitelist (ISSUE-AUDIT-AUDITOR-PATH-DICT-FORMAT, 2026-05-10).

    The filter must now emit a logger.warning naming the SKILL.md
    path + count so future regressions surface during agent build.
    """
    import logging

    skill = tmp_path / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        """---
name: test
description: "test"
tools:
  - path: ./tools/map_engine.py
  - path: ./tools/render_report.py
---
""",
        encoding="utf-8",
    )
    runner = _make_agent_for_dir(tmp_path)
    with caplog.at_level(logging.WARNING):
        f = runner._read_tools_filter(skill)
    # Dict entries → dropped → empty set (strict-zero, same as `tools: []`)
    assert f == set()
    # But the user gets told why
    msg = "\n".join(r.getMessage() for r in caplog.records)
    assert "dict entries" in msg
    assert "bare-string" in msg


# ── _load_tools_from_skill with whitelist ───────────────────────────


def test_load_tools_filters_by_skill_md_tools_list(tmp_path):
    """SKILL.md declares 2 of 3 .py — only the declared 2 load."""
    _write_tool(tmp_path / "tools", "alpha")
    _write_tool(tmp_path / "tools", "beta")
    _write_tool(tmp_path / "tools", "gamma")  # NOT in declared list
    skill = _write_skill(tmp_path / "SKILL.md", tools=["alpha", "beta"])

    runner = _make_agent_for_dir(tmp_path)
    loaded = runner._load_tools_from_skill(skill)
    names = {t.name for t in loaded}
    assert names == {"alpha", "beta"}
    assert "gamma" not in names


def test_load_tools_no_filter_field_loads_all_backward_compat(tmp_path):
    """No ``tools:`` field → all .py in tools/ load (current behaviour)."""
    _write_tool(tmp_path / "tools", "alpha")
    _write_tool(tmp_path / "tools", "beta")
    skill = _write_skill(tmp_path / "SKILL.md", tools=None)

    runner = _make_agent_for_dir(tmp_path)
    loaded = runner._load_tools_from_skill(skill)
    names = {t.name for t in loaded}
    assert names == {"alpha", "beta"}  # both load — no filter


def test_load_tools_explicit_whitelist_overrides_skill_md(tmp_path):
    """Explicit ``whitelist`` arg wins over the SKILL.md own list.

    Used by ``_build_tools`` to filter core/tools/ by the calling
    agent's declared list (cross-directory resolution).
    """
    _write_tool(tmp_path / "tools", "alpha")
    _write_tool(tmp_path / "tools", "beta")
    _write_tool(tmp_path / "tools", "gamma")
    # SKILL.md says 2 — but caller passes a different filter
    skill = _write_skill(tmp_path / "SKILL.md", tools=["alpha", "beta"])

    runner = _make_agent_for_dir(tmp_path)
    loaded = runner._load_tools_from_skill(skill, whitelist={"gamma"})
    names = {t.name for t in loaded}
    assert names == {"gamma"}


def test_load_tools_empty_tools_dir_returns_empty(tmp_path):
    skill = _write_skill(tmp_path / "SKILL.md", tools=["alpha"])
    # No tools/ dir created
    runner = _make_agent_for_dir(tmp_path)
    assert runner._load_tools_from_skill(skill) == []


def test_load_tools_filter_with_typo_silently_drops(tmp_path):
    """If SKILL.md declares ``foobar`` but only ``foo`` exists, the
    declared-but-missing entry is silently ignored (prevents typo
    from breaking agent boot)."""
    _write_tool(tmp_path / "tools", "foo")
    skill = _write_skill(tmp_path / "SKILL.md", tools=["foobar", "foo"])

    runner = _make_agent_for_dir(tmp_path)
    loaded = runner._load_tools_from_skill(skill)
    names = {t.name for t in loaded}
    assert names == {"foo"}


# ── End-to-end behaviour: cross-directory resolution ────────────────


def test_agent_pulls_only_declared_tools_from_core_pool(tmp_path):
    """Simulates the post-Patch-D' state for a sub-agent:

    core/tools/ has [execute_skill_script, format_and_export, read_file]
    lab/tools/ has [exec_on_node]
    lab/SKILL.md tools: [execute_skill_script, exec_on_node]

    Result: lab gets exactly those 2 tools — NOT format_and_export
    or read_file (which would have been auto-loaded under old
    behaviour).
    """
    # Set up core
    core_dir = tmp_path / "core"
    _write_tool(core_dir / "tools", "execute_skill_script")
    _write_tool(core_dir / "tools", "format_and_export")
    _write_tool(core_dir / "tools", "read_file")
    _write_skill(core_dir / "SKILL.md", tools=[
        "execute_skill_script", "format_and_export", "read_file",
    ])

    # Set up lab (sub-agent style)
    lab_dir = tmp_path / "lab"
    _write_tool(lab_dir / "tools", "exec_on_node")
    lab_skill = _write_skill(lab_dir / "SKILL.md",
                              tools=["execute_skill_script", "exec_on_node"])

    runner = _make_agent_for_dir(lab_dir)

    # Apply lab's filter to core tools (cross-directory resolution)
    sa_filter = runner._read_tools_filter(lab_skill)
    core_tools = runner._load_tools_from_skill(
        core_dir / "SKILL.md", whitelist=sa_filter,
    )
    own_tools = runner._load_tools_from_skill(
        lab_skill, whitelist=sa_filter,
    )
    combined_names = {t.name for t in core_tools} | {t.name for t in own_tools}

    assert combined_names == {"execute_skill_script", "exec_on_node"}
    # Critical: format_and_export and read_file (in core/tools/) NOT loaded
    assert "format_and_export" not in combined_names
    assert "read_file" not in combined_names
