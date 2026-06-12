"""Tests for deepagents native tool injection via SKILL.md sa_filter.

Verifies that skills declaring native FilesystemMiddleware tools
(ls, read_file, glob, grep) in their SKILL.md ``tools:`` list:

  1. Get those names included in sa_filter
  2. Have those tools excluded from _effective_prune (not stripped)
  3. Don't conflict with OLAV's own @tools of the same name
  4. Get ONLY native tools when no matching @tool file exists

This is the correctness gate before removing OLAV's custom read_file
@tool (core/tools/read_file.py).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from olav.agents.agent import OLAVAgent, _DEEPAGENTS_INJECT_TOOLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_skill(skill_path: Path, tools: list[str], name: str = "test") -> Path:
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    tools_yaml = "\n".join(f"  - {t}" for t in tools)
    skill_path.write_text(
        f"---\nname: {name}\ndescription: test\ntools:\n{tools_yaml}\n---\n",
        encoding="utf-8",
    )
    return skill_path


def _make_runner(agent_dir: Path) -> OLAVAgent:
    runner = OLAVAgent.__new__(OLAVAgent)
    runner._agent_dir = agent_dir
    return runner


# ---------------------------------------------------------------------------
# sa_filter correctly includes native tool names
# ---------------------------------------------------------------------------

class TestSaFilterIncludesNativeTools:
    def test_read_file_in_sa_filter(self, tmp_path):
        skill = _write_skill(tmp_path / "SKILL.md", tools=["read_file", "execute_sql"])
        runner = _make_runner(tmp_path)
        sa_filter = runner._read_tools_filter(skill)
        assert "read_file" in sa_filter

    def test_all_native_tools_in_sa_filter(self, tmp_path):
        native = ["ls", "read_file", "glob", "grep"]
        skill = _write_skill(tmp_path / "SKILL.md", tools=native)
        runner = _make_runner(tmp_path)
        sa_filter = runner._read_tools_filter(skill)
        assert sa_filter == set(native)

    def test_mixed_native_and_olav_tools(self, tmp_path):
        skill = _write_skill(
            tmp_path / "SKILL.md",
            tools=["ls", "read_file", "execute_sql", "execute_skill_script"],
        )
        runner = _make_runner(tmp_path)
        sa_filter = runner._read_tools_filter(skill)
        assert {"ls", "read_file", "execute_sql", "execute_skill_script"} == sa_filter


# ---------------------------------------------------------------------------
# _effective_prune excludes declared native tools
# ---------------------------------------------------------------------------

class TestEffectivePruneExcludesNativeTools:
    """Verify that native tools declared in SKILL.md are NOT in _effective_prune."""

    def _effective_prune(self, sa_filter: set[str] | None) -> frozenset[str]:
        if sa_filter is None:
            return _DEEPAGENTS_INJECT_TOOLS
        return _DEEPAGENTS_INJECT_TOOLS - sa_filter

    def test_read_file_not_pruned_when_declared(self, tmp_path):
        skill = _write_skill(tmp_path / "SKILL.md", tools=["read_file"])
        runner = _make_runner(tmp_path)
        sa_filter = runner._read_tools_filter(skill)
        prune = self._effective_prune(sa_filter)
        assert "read_file" not in prune

    def test_ls_glob_grep_not_pruned_when_declared(self, tmp_path):
        skill = _write_skill(tmp_path / "SKILL.md", tools=["ls", "glob", "grep"])
        runner = _make_runner(tmp_path)
        sa_filter = runner._read_tools_filter(skill)
        prune = self._effective_prune(sa_filter)
        assert "ls" not in prune
        assert "glob" not in prune
        assert "grep" not in prune

    def test_undeclared_native_tools_still_pruned(self, tmp_path):
        """ls not declared → still gets pruned even when read_file is kept."""
        skill = _write_skill(tmp_path / "SKILL.md", tools=["read_file"])
        runner = _make_runner(tmp_path)
        sa_filter = runner._read_tools_filter(skill)
        prune = self._effective_prune(sa_filter)
        assert "ls" in prune
        assert "write_file" in prune
        assert "execute" in prune

    def test_no_sa_filter_all_native_tools_pruned(self, tmp_path):
        """No tools: field → sa_filter=None → all native tools pruned."""
        skill_path = tmp_path / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("---\nname: test\ndescription: test\n---\n")
        runner = _make_runner(tmp_path)
        sa_filter = runner._read_tools_filter(skill_path)
        assert sa_filter is None
        prune = self._effective_prune(sa_filter)
        assert prune == _DEEPAGENTS_INJECT_TOOLS


# ---------------------------------------------------------------------------
# No OLAV @tool file → agent only gets native tool (no ghost duplicate)
# ---------------------------------------------------------------------------

class TestNoGhostDuplicateWhenOlavToolRemoved:
    """After removing core/tools/read_file.py, an agent declaring
    ``read_file`` in SKILL.md must get exactly the native tool —
    zero OLAV @tool files for that name."""

    def test_no_olav_read_file_loaded_when_file_absent(self, tmp_path):
        """Core tools dir has no read_file.py → _load_tools_from_skill returns nothing for it."""
        core_dir = tmp_path / "core"
        # Only put execute_sql, NOT read_file
        (core_dir / "tools").mkdir(parents=True)
        tool_file = core_dir / "tools" / "execute_sql.py"
        tool_file.write_text(
            "from langchain_core.tools import tool\n\n"
            "@tool\ndef execute_sql(q: str = '') -> str:\n    '''sql'''\n    return ''\n"
        )
        _write_skill(core_dir / "SKILL.md", tools=["execute_sql", "read_file"])

        runner = _make_runner(core_dir)
        sa_filter = runner._read_tools_filter(core_dir / "SKILL.md")
        tools = runner._load_tools_from_skill(core_dir / "SKILL.md", whitelist=sa_filter)
        names = {t.name for t in tools}

        # execute_sql loads from file; read_file has no @tool file → not in loaded set
        assert "execute_sql" in names
        assert "read_file" not in names  # native tool, not loaded from @tool file

    def test_native_tool_names_not_in_olav_core_tools_dir(self):
        """After the cleanup, none of the native tool names should exist as
        @tool files in core/tools/."""
        from pathlib import Path
        core_tools = (
            Path(__file__).resolve().parents[2]
            / "src" / "olav" / "data" / "workspace" / "core" / "tools"
        )
        if not core_tools.exists():
            pytest.skip("core/tools not found")

        native_names = {"ls", "read_file", "glob", "grep", "write_file", "edit_file", "execute"}
        present = [n for n in native_names if (core_tools / f"{n}.py").exists()]
        assert present == [], (
            f"Native tool files found in core/tools/ — should not exist: {present}"
        )
