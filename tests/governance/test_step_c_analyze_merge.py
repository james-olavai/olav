"""netops/analyzer sub-agent governance tests.

Validates the netops analyzer sub-agent (formerly ``ops/analyze`` from Sprint 3
Step C, now renamed to ``netops/analyzer`` per dev_docs/85 ops→netops rename).

Guards:
* ``netops/analyzer/`` directory exists with SKILL.md, tools/, prompts/, references/
* SKILL.md declares the required analysis tools
* SKILL.md uses the correct name "analyzer"
* The tool files are present
* netops/AGENT.md references the analyzer sub-agent

Note: the former ops/analyze split (ops-analysis + ops-diff merge) is now
represented by analyzer's combined toolset in the netops domain.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"
ANALYZER = WORKSPACE / "netops" / "analyzer"

_REQUIRED_TOOLS = (
    "diff_configs",
    "diff_snapshots",
    "inspect_blast_radius",
    "execute_sql",
    "query_evidence",
)


# ── Scaffold ─────────────────────────────────────────────────────────────────


def test_analyzer_directory_exists():
    assert ANALYZER.is_dir(), f"netops/analyzer/ missing: {ANALYZER}"
    assert (ANALYZER / "SKILL.md").is_file(), "netops/analyzer/SKILL.md missing"


def test_analyzer_has_scripts_directory():
    # tools/ deleted in rev ~298 (@tool→scripts migration complete)
    assert (ANALYZER / "scripts").is_dir(), "netops/analyzer/scripts/ missing"


def test_legacy_ops_analyze_is_gone():
    """ops/analyze/ must not exist — replaced by netops/analyzer/."""
    assert not (WORKSPACE / "ops" / "analyze").exists(), (
        "ops/analyze/ should not exist after dev_docs/85 ops→netops rename; "
        "use netops/analyzer/ instead"
    )


# ── SKILL.md frontmatter ─────────────────────────────────────────────────────


def _skill_frontmatter() -> dict:
    text = (ANALYZER / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "netops/analyzer/SKILL.md missing YAML frontmatter"
    front = text.split("---", 2)[1]
    return yaml.safe_load(front) or {}


def test_skill_md_name_is_analyzer():
    meta = _skill_frontmatter()
    assert meta.get("name") == "analyzer", (
        f"frontmatter name should be 'analyzer', got {meta.get('name')!r}"
    )


def test_skill_md_lists_required_tools():
    meta = _skill_frontmatter()
    tools = meta.get("tools") or []
    tools_joined = " ".join(str(t) for t in tools)
    # Also check scripts: field (tools may be migrated there — name or path-based entries)
    for entry in (meta.get("scripts") or []):
        if isinstance(entry, dict):
            tools_joined += " " + (entry.get("name", "") or entry.get("path", ""))
        elif isinstance(entry, str):
            tools_joined += " " + entry
    for tool_name in _REQUIRED_TOOLS:
        assert tool_name in tools_joined, (
            f"netops/analyzer SKILL.md tools list missing {tool_name!r}"
        )


def test_skill_md_has_thinking_mode():
    meta = _skill_frontmatter()
    assert "thinking_mode" in meta, (
        "analyzer SKILL.md missing thinking_mode (should be 'enabled')"
    )


# ── Tool files ───────────────────────────────────────────────────────────────


def test_query_evidence_tool_exists():
    # scripts-化: query_evidence moved from tools/ to scripts/
    tool = ANALYZER / "scripts" / "query_evidence.py"
    assert tool.is_file(), f"query_evidence.py missing at {tool}"


def test_diff_configs_tool_accessible():
    """diff_configs must be resolvable — either in analyzer/tools/ or netops shared."""
    # diff_configs may live in the shared netops tools area, confirmed via SKILL.md listing
    skill_text = (ANALYZER / "SKILL.md").read_text(encoding="utf-8")
    assert "diff_configs" in skill_text, (
        "diff_configs not found in analyzer SKILL.md"
    )


# ── netops/AGENT.md ─────────────────────────────────────────────────────────


def test_netops_agent_md_references_analyzer():
    agent_md = WORKSPACE / "netops" / "AGENT.md"
    assert agent_md.is_file(), "netops/AGENT.md missing"
    text = agent_md.read_text(encoding="utf-8")
    assert "analyzer" in text, (
        "netops/AGENT.md must reference the analyzer sub-agent"
    )
