"""Governance — netops/analyzer + netops/reporter split contract pins.

What this protects against:
  * analyzer creeping back to Mode B tools (query_evidence, inspect_blast_radius,
    diff_snapshots) — would re-introduce tool bloat > 7
  * reporter missing its investigation tools (query_evidence, diff_snapshots)
  * diff_snapshots being an @tool again (it was demoted to script, FINDING-19)
  * AGENT.md losing the reporter sub-agent reference
  * Either agent exceeding the 7-tool hard limit
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


_REPO = Path(__file__).resolve().parents[2]
_NETOPS = _REPO / ".olav" / "workspace" / "netops"
_ANALYZER_DIR = _NETOPS / "analyzer"
_REPORTER_DIR = _NETOPS / "reporter"
_NETOPS_AGENT_MD = _NETOPS / "AGENT.md"


def _parse_front_matter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"missing YAML front-matter in {md_path}"
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm) or {}


def _skill_body(md_path: Path) -> str:
    """Return content body of a SKILL.md (everything after the YAML front-matter)."""
    text = md_path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        return parts[2].strip() if len(parts) >= 3 else ""
    return text.strip()


def _collect_tools(fm: dict) -> set[str]:
    """Unified tool set: tools: entries + scripts: name entries."""
    tools = set(fm.get("tools", []))
    for entry in fm.get("scripts", []):
        if isinstance(entry, dict) and "name" in entry:
            tools.add(entry["name"])
        elif isinstance(entry, str):
            tools.add(entry)
    return tools


# ── Analyzer (Mode A — Change Plan) ──────────────────────────────────────────


class TestAnalyzerModeA:
    def test_skill_md_exists(self):
        assert (_ANALYZER_DIR / "SKILL.md").is_file()

    def test_tool_count_at_most_8(self):
        # Limit raised from 7 → 8 (2026-05-31): olav_recall_memory added to enable
        # expert-KB guardrail injection from trace_learner failure learning.
        # Budget is still tight — do not add more tools without a clear rationale.
        fm = _parse_front_matter(_ANALYZER_DIR / "SKILL.md")
        tools = _collect_tools(fm)
        assert len(tools) <= 8, (
            f"analyzer has {len(tools)} tools (> 8 hard limit): {sorted(tools)}"
        )

    def test_has_change_plan_tools(self):
        fm = _parse_front_matter(_ANALYZER_DIR / "SKILL.md")
        tools = _collect_tools(fm)
        assert "execute_sql" in tools
        assert "diff_configs" in tools
        assert "format_and_export" in tools
        assert "execute_skill_script" in tools

    def test_no_investigation_tools(self):
        """analyzer is Mode A only — investigation tools must not be present."""
        fm = _parse_front_matter(_ANALYZER_DIR / "SKILL.md")
        tools = _collect_tools(fm)
        for forbidden in ("query_evidence", "inspect_blast_radius", "diff_snapshots"):
            assert forbidden not in tools, (
                f"analyzer must NOT have {forbidden} — belongs in reporter (Mode B+C)"
            )

    def test_has_change_plan_scripts(self):
        fm = _parse_front_matter(_ANALYZER_DIR / "SKILL.md")
        script_names = {
            e["name"] for e in fm.get("scripts", []) if isinstance(e, dict)
        }
        assert "describe_table" in script_names
        assert "inspect_devices" in script_names
        assert "inspect_interfaces" in script_names

    def test_no_investigation_scripts(self):
        fm = _parse_front_matter(_ANALYZER_DIR / "SKILL.md")
        script_names = {
            e["name"] for e in fm.get("scripts", []) if isinstance(e, dict)
        }
        assert "query_evidence" not in script_names, (
            "query_evidence moved to reporter — not in analyzer"
        )
        assert "diff_snapshots" not in script_names, (
            "diff_snapshots demoted to reporter/scripts — not in analyzer"
        )

    def test_scripts_exist_on_disk(self):
        for name in ("describe_table", "inspect_devices", "inspect_interfaces"):
            p = _ANALYZER_DIR / "scripts" / f"{name}.py"
            assert p.is_file(), f"missing script: {p}"

    def test_system_prompt_workflow_a_only(self):
        text = _skill_body(_ANALYZER_DIR / "SKILL.md")
        assert "Workflow A" in text, "analyzer SKILL.md body must describe Workflow A"
        assert "change_plans" in text, "analyzer routes to exports/change_plans/"

    def test_system_prompt_no_workflow_d(self):
        """Mode B investigation content must be in reporter, not analyzer."""
        text = _skill_body(_ANALYZER_DIR / "SKILL.md")
        assert "Workflow D" not in text, (
            "Workflow D (investigation) content must not be in analyzer SKILL.md body"
        )


# ── Reporter (Mode B+C — Investigation + Blast Radius) ───────────────────────


class TestReporterModesBC:
    def test_skill_md_exists(self):
        assert (_REPORTER_DIR / "SKILL.md").is_file()

    def test_tool_count_at_most_9(self):
        # Limit raised from 8 → 9 (2026-06-01): read_file added for
        # read-before-write pattern (prevents duplicate report headers).
        fm = _parse_front_matter(_REPORTER_DIR / "SKILL.md")
        tools = _collect_tools(fm)
        assert len(tools) <= 9, (
            f"reporter has {len(tools)} tools (> 9 hard limit): {sorted(tools)}"
        )

    def test_has_investigation_tools(self):
        fm = _parse_front_matter(_REPORTER_DIR / "SKILL.md")
        tools = _collect_tools(fm)
        assert "execute_sql" in tools
        assert "query_evidence" in tools
        assert "diff_snapshots" in tools
        assert "inspect_blast_radius" in tools
        assert "format_and_export" in tools
        assert "execute_skill_script" in tools

    def test_no_change_plan_tools(self):
        """reporter is Mode B+C — change-plan-specific tools must not be present."""
        fm = _parse_front_matter(_REPORTER_DIR / "SKILL.md")
        tools = _collect_tools(fm)
        assert "diff_configs" not in tools, (
            "diff_configs belongs in analyzer (Mode A) — reporter reads config via query_evidence"
        )

    def test_scripts_exist_on_disk(self):
        for name in ("describe_table", "query_evidence", "diff_snapshots"):
            p = _REPORTER_DIR / "scripts" / f"{name}.py"
            assert p.is_file(), f"missing reporter script: {p}"

    def test_system_prompt_workflow_d(self):
        text = _skill_body(_REPORTER_DIR / "SKILL.md")
        assert "Workflow D" in text or "Investigation" in text
        assert "reports" in text

    def test_system_prompt_blast_radius(self):
        text = _skill_body(_REPORTER_DIR / "SKILL.md")
        assert "blast" in text.lower() or "blast_radius" in text.lower()


# ── diff_snapshots demoted from @tool to plain script ─────────────────────────


class TestDiffSnapshotsDemotion:
    def test_no_at_tool_decorator(self):
        """diff_snapshots must NOT have @tool as a decorator — it is now a plain script (FINDING-19).
        Note: the word '@tool' may appear in docstrings/comments; only the decorator form is forbidden."""
        script = (_REPORTER_DIR / "scripts" / "diff_snapshots.py").read_text()
        # The decorator form appears on its own line: "@tool\ndef ..."
        import re
        assert not re.search(r"^\s*@tool\s*$", script, re.MULTILINE), (
            "diff_snapshots.py re-introduced @tool decorator — "
            "it must remain a plain script (FINDING-19 demotion)"
        )
        assert "from langchain_core.tools import tool" not in script, (
            "diff_snapshots.py must not import langchain_core.tools — "
            "it was demoted from @tool to script"
        )

    def test_plain_function_exists(self):
        import importlib.util as _ilu
        path = _REPORTER_DIR / "scripts" / "diff_snapshots.py"
        spec = _ilu.spec_from_file_location("reporter_diff_snapshots", path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "diff_snapshots"), "diff_snapshots function missing from script"

    def test_old_at_tool_still_in_tools_pool(self):
        """The @tool version in netops/tools/ should still exist for other consumers."""
        netops_tools = _REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "tools"
        assert (netops_tools / "diff_snapshots.py").is_file(), (
            "netops/tools/diff_snapshots.py (@tool version) must be preserved — "
            "may still be used by non-reporter consumers"
        )


# ── netops AGENT.md routing ───────────────────────────────────────────────────


class TestNetopsAgentMdRouting:
    def test_reporter_listed_in_subagents(self):
        fm = _parse_front_matter(_NETOPS_AGENT_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        assert "./reporter/SKILL.md" in sub_paths, (
            "reporter/SKILL.md must be listed as a subagent in netops/AGENT.md"
        )

    def test_analyzer_still_in_subagents(self):
        fm = _parse_front_matter(_NETOPS_AGENT_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        assert "./analyzer/SKILL.md" in sub_paths, (
            "analyzer/SKILL.md must still be listed in netops/AGENT.md"
        )

    def test_both_workspaces_have_reporter(self):
        """Two-workspace sync: reporter must exist in both olav-netops and dev mirror."""
        authoritative = (
            _REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "reporter" / "SKILL.md"
        )
        dev_mirror = _REPO / ".olav" / "workspace" / "netops" / "reporter" / "SKILL.md"
        assert authoritative.is_file(), f"reporter SKILL.md missing in authoritative: {authoritative}"
        assert dev_mirror.is_file(), f"reporter SKILL.md missing in dev mirror: {dev_mirror}"
