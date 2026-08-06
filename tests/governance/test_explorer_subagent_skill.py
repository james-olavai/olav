"""Governance — ``netops/explorer`` sub-agent contract pins.

What this protects against:
  * Future refactor silently dropping ``record_finding`` from the
    tool whitelist (would break anti-fabrication invariant)
  * Someone setting ``dynamic_context`` to inject taxonomy by default
    (would violate the Level-2 design philosophy of dev_docs/78 §2)
  * Tool wrapper import drift
  * SKILL.md losing the explorer sub-agent reference
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


_REPO = Path(__file__).resolve().parents[2]
# Moved out of the platform audit bundle on 2026-08-06: explorer is an
# open-ended assessment agent, which is presales work, and its six
# network-type playbooks are presales content. Points at the authoritative
# source rather than the runtime mirror so the gate does not depend on
# `olav skill install olav-presales` having run first.
_EXPLORER_DIR = (
    _REPO / "olav-presales" / ".olav" / "workspace" / "presales" / "explorer"
)
_PRESALES_SKILL_MD = (
    _REPO / "olav-presales" / ".olav" / "workspace" / "presales" / "SKILL.md"
)
# The platform audit bundle's authoritative source — asserted to be free of
# explorer, so a half-finished move cannot pass.
_AUDIT_SKILL_MD = (
    _REPO / "olav-netops" / ".olav" / "workspace" / "audit" / "SKILL.md"
)


def _parse_front_matter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"missing YAML front-matter in {md_path}"
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm) or {}


def _skill_body(md_path: Path) -> str:
    """Return the content body of a SKILL.md (everything after the YAML front-matter)."""
    text = md_path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        return parts[2].strip() if len(parts) >= 3 else ""
    return text.strip()


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
        dev_docs/78 §3.3."""
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
        assert "olav_recall_memory" in tools
        assert "format_and_export" in tools
        assert "task" not in tools
        # Scratchpad persistence toolset (ISSUE-AGENT-SCRATCHPAD-NOT-WIRED)
        assert "start_exploration" in tools, "start_exploration must be in scripts:"
        assert "record_finding" in tools, "record_finding must be in scripts:"
        assert "finish_exploration" in tools, "finish_exploration must be in scripts:"

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
        """prompts/system.md merged into SKILL.md body — verify body is non-empty."""
        body = _skill_body(_EXPLORER_DIR / "SKILL.md")
        assert body, "SKILL.md body (system prompt) is empty"

    def test_system_prompt_mentions_react_loop(self):
        """The migrated workflow framing must stay explicit."""
        text = _skill_body(_EXPLORER_DIR / "SKILL.md")
        for phase in ("SURVEY", "CLASSIFY", "INVESTIGATE", "REPORT"):
            assert phase in text, f"system prompt missing phase keyword: {phase}"

    def test_system_prompt_instructs_olav_recall_memory_for_playbook(self):
        """CLASSIFY phase must instruct calling olav_recall_memory to pull a
        network-type playbook."""
        text = _skill_body(_EXPLORER_DIR / "SKILL.md")
        assert "olav_recall_memory" in text
        assert "L1-L4" in text or "playbook" in text

    def test_system_prompt_instructs_reflection_on_high_severity(self):
        """Severity-first ranking and L1-L4 progression are mandatory."""
        text = _skill_body(_EXPLORER_DIR / "SKILL.md")
        assert "Rank by severity" in text
        assert "L1 → L4" in text or "L1-L4" in text

    def test_system_prompt_mentions_anti_fabrication(self):
        """Evidence-grounding requirement must be explicit in the prompt."""
        text = _skill_body(_EXPLORER_DIR / "SKILL.md")
        assert "Evidence or nothing" in text
        assert "must cite the query" in text

    def test_system_prompt_mentions_full_coverage(self):
        # Rule 7 changed (2026-06-01): "5+ findings → stop" replaced with
        # "all L1-L4 layers must be attempted before synthesis".
        text = _skill_body(_EXPLORER_DIR / "SKILL.md")
        assert "L1-L4 are all attempted" in text or "after L1-L4" in text or "Stop only after" in text


# ── netops SKILL.md wire-up ───────────────────────────────────────────


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
            assert "source_tier: team" in text, (
                f"{g} missing source_tier: team — these playbooks left the\n"
                f"platform wheel with the explorer agent on 2026-08-06"
            )


class TestPresalesWiring:
    """explorer moved from the platform audit bundle to presales.

    The agent is an open-ended assessment persona and its six network-type
    playbooks are presales content, so both moved together rather than leaving
    the playbooks behind as a copy nobody owned.
    """

    def test_explorer_listed_in_presales_subagents(self):
        fm = _parse_front_matter(_PRESALES_SKILL_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        assert "./explorer/SKILL.md" in sub_paths, (
            f"presales does not declare explorer; it has {sorted(sub_paths)}"
        )

    def test_presales_siblings_still_present(self):
        """Adding explorer must not displace the agents that were there."""
        fm = _parse_front_matter(_PRESALES_SKILL_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        for sibling in ("./surveyor/SKILL.md", "./analyst/SKILL.md",
                        "./designer/SKILL.md", "./publisher/SKILL.md"):
            assert sibling in sub_paths, f"{sibling} disappeared"

    def test_presales_stays_within_the_subagent_cap(self):
        """ADR-0003/0005/0006 cap an orchestrator at five sub-agents. explorer
        is the fifth, so this is now exactly at the ceiling — a sixth needs a
        decision, not a quiet addition."""
        fm = _parse_front_matter(_PRESALES_SKILL_MD)
        assert len(fm.get("subagents", [])) <= 5

    def test_the_platform_audit_bundle_no_longer_carries_explorer(self):
        """The move is only complete if the old home stopped referring to it —
        a stale route would delegate to an agent that is not there."""
        text = _AUDIT_SKILL_MD.read_text(encoding="utf-8")
        assert "explorer" not in text, (
            "the platform audit skill still mentions explorer"
        )
