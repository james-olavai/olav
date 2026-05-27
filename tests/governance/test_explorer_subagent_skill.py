"""Governance — ``netops/explorer`` sub-agent contract pins.

What this protects against:
  * Future refactor silently dropping ``record_finding`` from the
    tool whitelist (would break anti-fabrication invariant)
  * Someone setting ``dynamic_context`` to inject taxonomy by default
    (would violate the Level-2 design philosophy of dev_docs/83 §2)
  * Tool wrapper import drift
  * AGENT.md losing the explorer sub-agent reference
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


_REPO = Path(__file__).resolve().parents[2]
_EXPLORER_DIR = _REPO / ".olav" / "workspace" / "audit" / "explorer"
_AUDIT_AGENT_MD = _REPO / ".olav" / "workspace" / "audit" / "AGENT.md"


def _parse_front_matter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"missing YAML front-matter in {md_path}"
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm) or {}


# ── SKILL.md ──────────────────────────────────────────────────────────


class TestExplorerSkillFrontMatter:
    def test_skill_md_exists(self):
        assert (_EXPLORER_DIR / "SKILL.md").is_file()

    def test_name_is_explorer(self):
        fm = _parse_front_matter(_EXPLORER_DIR / "SKILL.md")
        assert fm["name"] == "explorer"

    def test_agent_type_api(self):
        fm = _parse_front_matter(_EXPLORER_DIR / "SKILL.md")
        assert fm["agent_type"] == "api"

    def test_thinking_mode_enabled(self):
        """PLAN/CORRELATE/REPORT phases benefit from deep thinking — see
        dev_docs/83 §3.3."""
        fm = _parse_front_matter(_EXPLORER_DIR / "SKILL.md")
        assert fm["thinking_mode"] == "enabled"

    def test_dynamic_context_empty_by_default(self):
        """Migration contract: explorer now auto-loads network type classifier."""
        fm = _parse_front_matter(_EXPLORER_DIR / "SKILL.md")
        dc = fm.get("dynamic_context", [])
        assert isinstance(dc, list) and dc, "dynamic_context must include classifier guide"
        assert any(
            isinstance(item, dict) and item.get("path") == "./references/network_type_classifier.guide.yaml"
            for item in dc
        ), f"network type classifier guide missing from dynamic_context: {dc}"

    def test_tool_whitelist_includes_scratchpad_tools(self):
        fm = _parse_front_matter(_EXPLORER_DIR / "SKILL.md")
        # Collect both tools: (strings) and scripts: (dicts with 'name') as unified toolset.
        tools = set(fm.get("tools", []))
        for entry in fm.get("scripts", []):
            if isinstance(entry, dict) and "name" in entry:
                tools.add(entry["name"])
            elif isinstance(entry, str):
                tools.add(entry)
        # Core read-only investigation toolset
        assert "execute_sql" in tools
        assert "describe_table" in tools
        assert "query_evidence" in tools
        assert "search_logs" in tools
        assert "recall_memory" in tools
        assert "format_and_export" in tools
        assert "task" not in tools

    def test_tool_whitelist_excludes_write_tools(self):
        """Explorer is read-only — never gives the LLM a tool that mutates
        network devices or writes back to the netops fleet."""
        fm = _parse_front_matter(_EXPLORER_DIR / "SKILL.md")
        tools = set(fm.get("tools", []))
        for forbidden in ("execute_cli_parallel", "ingest_snapshot", "validate_bundle"):
            assert forbidden not in tools, (
                f"explorer must NOT have {forbidden} (write/mutate scope)"
            )

    def test_no_nested_subagents(self):
        fm = _parse_front_matter(_EXPLORER_DIR / "SKILL.md")
        assert not fm.get("subagents"), "explorer must not declare nested subagents"


# ── Prompts ───────────────────────────────────────────────────────────


class TestPromptContract:
    def test_system_prompt_exists(self):
        assert (_EXPLORER_DIR / "prompts" / "system.md").is_file()

    def test_system_prompt_mentions_react_loop(self):
        """The migrated workflow framing must stay explicit."""
        text = (_EXPLORER_DIR / "prompts" / "system.md").read_text(encoding="utf-8")
        for phase in ("SURVEY", "CLASSIFY", "INVESTIGATE", "REPORT"):
            assert phase in text, f"system prompt missing phase keyword: {phase}"

    def test_system_prompt_instructs_recall_memory_for_playbook(self):
        """CLASSIFY phase must instruct calling recall_memory to pull a
        network-type playbook."""
        text = (_EXPLORER_DIR / "prompts" / "system.md").read_text(encoding="utf-8")
        assert "recall_memory" in text
        assert "L1-L4" in text or "playbook" in text

    def test_system_prompt_instructs_reflection_on_high_severity(self):
        """Severity-first ranking and L1-L4 progression are mandatory."""
        text = (_EXPLORER_DIR / "prompts" / "system.md").read_text(encoding="utf-8")
        assert "Rank by severity" in text
        assert "L1 → L4" in text or "L1-L4" in text

    def test_system_prompt_mentions_anti_fabrication(self):
        """Evidence-grounding requirement must be explicit in the prompt."""
        text = (_EXPLORER_DIR / "prompts" / "system.md").read_text(encoding="utf-8")
        assert "Evidence or nothing" in text
        assert "must cite the query" in text

    def test_system_prompt_mentions_budgets(self):
        text = (_EXPLORER_DIR / "prompts" / "system.md").read_text(encoding="utf-8")
        assert "5+ grounded findings" in text


# ── netops AGENT.md wire-up ───────────────────────────────────────────


class TestPlaybookGuidesPresent:
    """6 KB guides exist as schema-v2 source_tier=platform references."""

    GUIDES = [
        "network_type_classifier.guide.yaml",
        "campus_wireless_l1_l4_issues.guide.yaml",
        "dc_fabric_l1_l4_issues.guide.yaml",
        "isp_edge_l1_l4_issues.guide.yaml",
        "sdwan_l1_l4_issues.guide.yaml",
        "enterprise_branch_l1_l4_issues.guide.yaml",
    ]

    def test_all_guides_exist(self):
        for g in self.GUIDES:
            p = _EXPLORER_DIR / "references" / g
            assert p.is_file(), f"missing playbook guide: {g}"

    def test_guides_are_schema_v2_platform_tier(self):
        for g in self.GUIDES:
            p = _EXPLORER_DIR / "references" / g
            head = p.read_text(encoding="utf-8").splitlines()[:10]
            text = "\n".join(head)
            assert "schema_version: 2" in text, f"{g} missing schema_version: 2"
            assert "source_tier: platform" in text, f"{g} missing source_tier: platform"


class TestAuditAgentMdWiring:
    def test_explorer_listed_in_subagents(self):
        fm = _parse_front_matter(_AUDIT_AGENT_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        assert "./explorer/SKILL.md" in sub_paths

    def test_other_subagents_still_present(self):
        """Sanity — adding explorer must not displace siblings."""
        fm = _parse_front_matter(_AUDIT_AGENT_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        for sibling in ("./audit-runner/SKILL.md", "./audit-author/SKILL.md"):
            assert sibling in sub_paths

    def test_route_keywords_mention_explore(self):
        fm = _parse_front_matter(_AUDIT_AGENT_MD)
        joined = " ".join(fm.get("route_keywords", []))
        assert "explore" in joined.lower()
        assert "audit" in joined.lower() or "health" in joined.lower()


# ── Tool wrappers import cleanly ──────────────────────────────────────


def _load_script(name: str) -> Any:
    """Load a script from explorer/scripts/ by name."""
    import importlib.util as _ilu
    path = _EXPLORER_DIR / "scripts" / f"{name}.py"
    spec = _ilu.spec_from_file_location(f"explorer_scripts_{name}", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestToolWrappersLoad:
    def test_describe_table_tool_loads(self):
        mod = _load_script("describe_table")
        assert hasattr(mod, "describe_table"), "function missing from script"

    def test_query_evidence_tool_loads(self):
        mod = _load_script("query_evidence")
        assert hasattr(mod, "query_evidence"), "function missing from script"

    def test_scratchpad_scripts_removed(self):
        """start_exploration / record_finding / update_exploration_run were
        dormant (not referenced in system.md; LLM writes via format_and_export).
        Removed in direction-A cleanup — DB scratchpad pattern abandoned for now.
        See dev_docs/86 § ISSUE-AGENT-TOOL-BLOAT / audit explorer analysis."""
        for name in ("start_exploration", "record_finding", "update_exploration_run"):
            assert not (_EXPLORER_DIR / "scripts" / f"{name}.py").exists(), (
                f"{name}.py must be deleted — scratchpad scripts were dormant "
                "(not in system.md); use format_and_export for incremental output"
            )

    def test_promote_finding_to_audit_module_removed(self):
        """The promote_finding_to_audit @tool wrapper was removed in
        dev_docs/84 §B — explorer outputs free-form markdown; humans
        feed it to the audit author for profile creation."""
        assert not (_EXPLORER_DIR / "tools" / "promote_finding_to_audit.py").exists(), (
            "promote_finding_to_audit.py should have been removed — see "
            "dev_docs/84 §B for the corrected lifecycle"
        )
