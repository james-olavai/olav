"""Tests for ops tool consolidation (dev_docs/26. OPS_TOOL_CONSOLIDATION.md).

Verifies the Single Source of Truth layout:
- Canonical tool files live in ops/tools/
- All duplicate locations are symlinks pointing to the canonical source
- analysis agent has exactly one tool: run_python_simulation
- Broken symlinks are fixed
- Deleted private API tools are gone
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------

REPO = Path(__file__).parent.parent.parent
WORKSPACE = REPO / ".olav/workspace"
OPS = WORKSPACE / "ops"
OPS_TOOLS = OPS / "tools"
CORE_TOOLS = WORKSPACE / "core/tools"
CONFIG_TOOLS = WORKSPACE / "config/tools"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_symlink(path: Path) -> bool:
    return path.is_symlink()


def symlink_target(path: Path) -> Path:
    """Return the Path that a symlink resolves to (relative → absolute)."""
    target = os.readlink(path)
    if not os.path.isabs(target):
        return (path.parent / target).resolve()
    return Path(target).resolve()


def resolves_ok(path: Path) -> bool:
    """True if path is a symlink and its target exists."""
    return path.is_symlink() and path.resolve().exists()


# ---------------------------------------------------------------------------
# Phase A — symlink replacement
# ---------------------------------------------------------------------------


class TestPhaseASymlinks:
    """core/tools and config/tools must contain the canonical ops tools (v0.15: quick→core)."""

    # core/tools — v0.15: tools copied/symlinked into core from ops

    def test_core_execute_cli_exists(self):
        p = CORE_TOOLS / "execute_cli.py"
        assert p.exists(), f"{p} must exist in core/tools"

    def test_core_execute_cli_content_matches_ops(self):
        p = CORE_TOOLS / "execute_cli.py"
        canonical = OPS_TOOLS / "execute_cli.py"
        assert p.exists() and canonical.exists()
        # Either symlink to canonical, or same content
        if p.is_symlink():
            assert p.resolve() == canonical.resolve()
        else:
            assert p.read_text() == canonical.read_text()

    def test_core_diff_configs_exists(self):
        p = CORE_TOOLS / "diff_configs.py"
        assert p.exists(), f"{p} must exist in core/tools"

    def test_core_diff_configs_content_matches_ops(self):
        p = CORE_TOOLS / "diff_configs.py"
        canonical = OPS_TOOLS / "diff_configs.py"
        assert p.exists() and canonical.exists()
        if p.is_symlink():
            assert p.resolve() == canonical.resolve()
        else:
            assert p.read_text() == canonical.read_text()

    def test_core_search_commands_exists(self):
        p = CORE_TOOLS / "search_commands.py"
        assert p.exists(), f"{p} must exist in core/tools"

    def test_core_search_commands_content_matches_ops(self):
        p = CORE_TOOLS / "search_commands.py"
        canonical = OPS_TOOLS / "search_commands.py"
        assert p.exists() and canonical.exists()
        if p.is_symlink():
            assert p.resolve() == canonical.resolve()
        else:
            assert p.read_text() == canonical.read_text()

    def test_config_execute_cli_is_symlink(self):
        p = CONFIG_TOOLS / "execute_cli.py"
        assert is_symlink(p), f"{p} must be a symlink"

    def test_config_execute_cli_points_to_canonical(self):
        p = CONFIG_TOOLS / "execute_cli.py"
        expected = (OPS_TOOLS / "execute_cli.py").resolve()
        assert symlink_target(p) == expected

    def test_config_diff_configs_is_symlink(self):
        p = CONFIG_TOOLS / "diff_configs.py"
        assert is_symlink(p), f"{p} must be a symlink"

    def test_config_diff_configs_points_to_canonical(self):
        p = CONFIG_TOOLS / "diff_configs.py"
        expected = (OPS_TOOLS / "diff_configs.py").resolve()
        assert symlink_target(p) == expected

    def test_config_search_commands_is_symlink(self):
        p = CONFIG_TOOLS / "search_commands.py"
        assert is_symlink(p), f"{p} must be a symlink"

    def test_config_search_commands_points_to_canonical(self):
        p = CONFIG_TOOLS / "search_commands.py"
        expected = (OPS_TOOLS / "search_commands.py").resolve()
        assert symlink_target(p) == expected

    # diff/tools

    def test_diff_diff_configs_is_symlink(self):
        p = OPS / "diff/tools/diff_configs.py"
        assert is_symlink(p), f"{p} must be a symlink"

    def test_diff_diff_configs_points_to_canonical(self):
        p = OPS / "diff/tools/diff_configs.py"
        expected = (OPS_TOOLS / "diff_configs.py").resolve()
        assert symlink_target(p) == expected


# ---------------------------------------------------------------------------
# Phase B — analysis agent simplification
# ---------------------------------------------------------------------------


class TestPhaseBAnalysis:
    """analysis agent should have exactly one tool: run_python_simulation."""

    def test_run_python_simulation_exists_in_ops_tools(self):
        """Canonical source must be a physical file in ops/tools/."""
        p = OPS_TOOLS / "run_python_simulation.py"
        assert p.exists(), f"Canonical source missing: {p}"
        assert not p.is_symlink(), f"{p} must be a physical file, not a symlink"

    def test_analysis_run_python_simulation_is_symlink(self):
        p = OPS / "analysis/tools/run_python_simulation.py"
        assert is_symlink(p), f"{p} must be a symlink to ops/tools/"

    def test_analysis_run_python_simulation_points_to_canonical(self):
        p = OPS / "analysis/tools/run_python_simulation.py"
        expected = (OPS_TOOLS / "run_python_simulation.py").resolve()
        assert symlink_target(p) == expected

    def test_analysis_execute_cli_deleted(self):
        p = OPS / "analysis/tools/execute_cli.py"
        assert not p.exists(), f"{p} must be deleted (contradicts network_isolation=True)"

    def test_analysis_topology_deleted(self):
        p = OPS / "analysis/tools/topology.py"
        assert not p.exists(), f"{p} must be deleted (redundant: sandbox nx covers DuckPGQ)"

    def test_analysis_tools_directory_only_has_simulation(self):
        """analysis/tools/ must contain ONLY run_python_simulation.py."""
        tools_dir = OPS / "analysis/tools"
        py_files = [f.name for f in tools_dir.iterdir() if f.name.endswith(".py")]
        assert py_files == ["run_python_simulation.py"], (
            f"analysis/tools/ should only have run_python_simulation.py, got: {py_files}"
        )

    def test_analysis_skill_md_tools_list(self):
        """SKILL.md tools must only list run_python_simulation."""
        skill_md = OPS / "analysis/SKILL.md"
        content = skill_md.read_text()
        # Parse YAML frontmatter (between --- delimiters)
        parts = content.split("---\n")
        frontmatter = yaml.safe_load(parts[1])
        tools = frontmatter.get("tools", [])
        assert tools == ["run_python_simulation"], (
            f"analysis SKILL.md tools should be ['run_python_simulation'], got: {tools}"
        )

    def test_analysis_skill_md_no_execute_cli_in_tools(self):
        skill_md = OPS / "analysis/SKILL.md"
        content = skill_md.read_text()
        parts = content.split("---\n")
        frontmatter = yaml.safe_load(parts[1])
        tools = frontmatter.get("tools", [])
        assert "execute_cli" not in tools

    def test_analysis_skill_md_no_topology_in_tools(self):
        skill_md = OPS / "analysis/SKILL.md"
        content = skill_md.read_text()
        parts = content.split("---\n")
        frontmatter = yaml.safe_load(parts[1])
        tools = frontmatter.get("tools", [])
        assert "topology" not in tools

    def test_analysis_system_md_no_execute_cli_instruction(self):
        """system.md must not instruct agent to use execute_cli."""
        system_md = OPS / "analysis/prompts/system.md"
        content = system_md.read_text()
        # Should not have an instruction to call execute_cli
        assert "Use `execute_cli`" not in content, (
            "system.md still instructs agent to use execute_cli (removed tool)"
        )

    def test_analysis_system_md_no_topology_tool_instruction(self):
        """system.md must not instruct agent to use topology tool."""
        system_md = OPS / "analysis/prompts/system.md"
        content = system_md.read_text()
        assert "Use `topology` tool" not in content, (
            "system.md still instructs agent to use topology tool (removed)"
        )

    def test_lab_run_python_simulation_points_to_canonical(self):
        """lab symlink must point to ops/tools/, not the deleted ops/sim/."""
        p = OPS / "lab/tools/run_python_simulation.py"
        assert is_symlink(p), f"{p} must be a symlink"
        expected = (OPS_TOOLS / "run_python_simulation.py").resolve()
        assert symlink_target(p) == expected, (
            f"lab symlink points to wrong target: {symlink_target(p)}, expected {expected}"
        )

    def test_lab_run_python_simulation_not_broken(self):
        p = OPS / "lab/tools/run_python_simulation.py"
        assert resolves_ok(p), f"Symlink {p} is broken (target does not exist)"


# ---------------------------------------------------------------------------
# Phase C — probe execute_cli_parallel uplift
# ---------------------------------------------------------------------------


class TestPhaseCProbe:
    """execute_cli_parallel must be canonical in ops/tools/, probe uses symlink."""

    def test_execute_cli_parallel_exists_in_ops_tools(self):
        p = OPS_TOOLS / "execute_cli_parallel.py"
        assert p.exists(), f"Canonical source missing: {p}"
        assert not p.is_symlink(), f"{p} must be a physical file"

    def test_probe_execute_cli_parallel_is_symlink(self):
        p = OPS / "probe/tools/execute_cli_parallel.py"
        assert is_symlink(p), f"{p} must be a symlink to ops/tools/"

    def test_probe_execute_cli_parallel_points_to_canonical(self):
        p = OPS / "probe/tools/execute_cli_parallel.py"
        expected = (OPS_TOOLS / "execute_cli_parallel.py").resolve()
        assert symlink_target(p) == expected

    def test_probe_execute_cli_parallel_not_broken(self):
        p = OPS / "probe/tools/execute_cli_parallel.py"
        assert resolves_ok(p)


# ---------------------------------------------------------------------------
# Phase D — lab private API tools deleted
# ---------------------------------------------------------------------------


class TestPhaseDCleanup:
    """Private API helper tools replaced by platform service_call."""

    def test_query_api_schema_deleted(self):
        p = OPS / "lab/tools/_query_api_schema.py"
        assert not p.exists(), f"{p} must be deleted (use platform service_call instead)"

    def test_get_definition_schema_deleted(self):
        p = OPS / "lab/tools/_get_definition_schema.py"
        assert not p.exists(), f"{p} must be deleted (use platform service_call instead)"


# ---------------------------------------------------------------------------
# General integrity — no broken symlinks in ops workspace
# ---------------------------------------------------------------------------


class TestSymlinkIntegrity:
    """All symlinks in the ops workspace must resolve without error."""

    def _collect_symlinks(self) -> list[Path]:
        result = []
        for root, dirs, files in os.walk(OPS):
            # Skip _generated (auto-generated, may have their own issues)
            dirs[:] = [d for d in dirs if d != "_generated"]
            for name in files:
                p = Path(root) / name
                if p.is_symlink():
                    result.append(p)
        return result

    def test_no_broken_symlinks_in_ops(self):
        broken = [str(p) for p in self._collect_symlinks() if not resolves_ok(p)]
        assert not broken, f"Broken symlinks found:\n" + "\n".join(broken)

    def test_core_tools_not_broken(self):
        if not CORE_TOOLS.exists():
            return  # core/tools doesn't exist yet — skip
        broken = [
            str(p)
            for p in CORE_TOOLS.iterdir()
            if p.is_symlink() and not resolves_ok(p)
        ]
        assert not broken, f"Broken core/tools symlinks: {broken}"

    def test_config_symlinks_not_broken(self):
        broken = [
            str(p)
            for p in CONFIG_TOOLS.iterdir()
            if p.is_symlink() and not resolves_ok(p)
        ]
        assert not broken, f"Broken config/tools symlinks: {broken}"
