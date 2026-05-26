"""netops/analyzer sub-agent governance tests.

Validates the netops analyzer sub-agent (Mode A — change-plan drafter only).
After the 2026-05-26 split (ISSUE-AGENT-TOOL-BLOAT), analyzer owns Mode A
(change planning) and reporter owns Mode B+C (investigation + blast radius).

Guards:
* analyzer/ exists with SKILL.md, scripts/, prompts/, references/
* SKILL.md declares Mode A tools only (4@tool + 3 scripts ≤ 7 total)
* Investigation tools (query_evidence, inspect_blast_radius, diff_snapshots)
  are NOT in analyzer — they live in reporter/
* netops/AGENT.md references both analyzer and reporter sub-agents
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"
ANALYZER = WORKSPACE / "netops" / "analyzer"
REPORTER = WORKSPACE / "netops" / "reporter"

# Mode A tools only (change plan drafter)
_ANALYZER_REQUIRED_TOOLS = (
    "diff_configs",
    "execute_sql",
    "describe_table",
    "inspect_devices",
    "inspect_interfaces",
)

# Tools that moved to reporter — must NOT appear in analyzer
_MOVED_TO_REPORTER = (
    "query_evidence",
    "inspect_blast_radius",
    "diff_snapshots",
    "inspect_routing",
)


# ── Scaffold ─────────────────────────────────────────────────────────────────


def test_analyzer_directory_exists():
    assert ANALYZER.is_dir(), f"netops/analyzer/ missing: {ANALYZER}"
    assert (ANALYZER / "SKILL.md").is_file(), "netops/analyzer/SKILL.md missing"


def test_analyzer_has_scripts_directory():
    assert (ANALYZER / "scripts").is_dir(), "netops/analyzer/scripts/ missing"


def test_reporter_directory_exists():
    """After 2026-05-26 split, reporter must also exist."""
    assert REPORTER.is_dir(), f"netops/reporter/ missing: {REPORTER}"
    assert (REPORTER / "SKILL.md").is_file(), "netops/reporter/SKILL.md missing"


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


def _all_tool_names(meta: dict) -> str:
    tools = meta.get("tools") or []
    joined = " ".join(str(t) for t in tools)
    for entry in (meta.get("scripts") or []):
        if isinstance(entry, dict):
            joined += " " + (entry.get("name", "") or entry.get("path", ""))
        elif isinstance(entry, str):
            joined += " " + entry
    return joined


def test_skill_md_name_is_analyzer():
    meta = _skill_frontmatter()
    assert meta.get("name") == "analyzer", (
        f"frontmatter name should be 'analyzer', got {meta.get('name')!r}"
    )


def test_skill_md_lists_mode_a_tools():
    """analyzer must include all Mode A (change-plan) tools."""
    meta = _skill_frontmatter()
    tools_joined = _all_tool_names(meta)
    for tool_name in _ANALYZER_REQUIRED_TOOLS:
        assert tool_name in tools_joined, (
            f"netops/analyzer SKILL.md missing Mode A tool {tool_name!r} — "
            f"analyzer is the change-plan drafter"
        )


def test_skill_md_excludes_reporter_tools():
    """Tools that moved to reporter must NOT be in analyzer."""
    meta = _skill_frontmatter()
    tools_joined = _all_tool_names(meta)
    for tool_name in _MOVED_TO_REPORTER:
        assert tool_name not in tools_joined, (
            f"netops/analyzer SKILL.md contains {tool_name!r} which moved to reporter "
            f"(Mode B+C) — remove it from analyzer to keep tool count ≤ 7"
        )


def test_skill_md_has_thinking_mode():
    meta = _skill_frontmatter()
    assert "thinking_mode" in meta, (
        "analyzer SKILL.md missing thinking_mode (should be 'enabled')"
    )


def test_tool_count_at_most_7():
    from tests.governance.test_netops_analyzer_reporter_split import _collect_tools
    meta = _skill_frontmatter()
    tools = _collect_tools(meta)
    assert len(tools) <= 7, (
        f"analyzer has {len(tools)} tools (> 7 hard limit): {sorted(tools)}"
    )


# ── Script files ─────────────────────────────────────────────────────────────


def test_mode_a_scripts_exist_on_disk():
    """describe_table / inspect_devices / inspect_interfaces live in analyzer/scripts/."""
    for name in ("describe_table.py", "inspect_devices.py", "inspect_interfaces.py"):
        script = ANALYZER / "scripts" / name
        assert script.is_file(), f"Mode A script missing: {script}"


def test_reporter_scripts_exist_on_disk():
    """query_evidence / diff_snapshots live in reporter/scripts/ (moved from analyzer)."""
    for name in ("query_evidence.py", "diff_snapshots.py"):
        script = REPORTER / "scripts" / name
        assert script.is_file(), f"reporter script missing: {script}"


def test_inspect_routing_moved_to_reporter_or_dropped():
    """inspect_routing was removed from both agents — routing state via execute_sql directly."""
    assert not (ANALYZER / "scripts" / "inspect_routing.py").exists(), (
        "inspect_routing.py must not be in analyzer/scripts/ — "
        "routing queries use execute_sql on the BGP/OSPF views directly"
    )


def test_diff_configs_tool_accessible():
    """diff_configs must be referenced in analyzer SKILL.md."""
    skill_text = (ANALYZER / "SKILL.md").read_text(encoding="utf-8")
    assert "diff_configs" in skill_text, (
        "diff_configs not found in analyzer SKILL.md"
    )


def test_inspect_atool_files_removed_from_netops_tools():
    """After migration, inspect_devices/interfaces/routing must not exist in @tool pool."""
    tools_dir = WORKSPACE / "netops" / "tools"
    for name in ("inspect_devices.py", "inspect_interfaces.py", "inspect_routing.py"):
        assert not (tools_dir / name).exists(), (
            f"@tool file still present in netops/tools/ after migration: {name}"
        )


# ── netops/AGENT.md ─────────────────────────────────────────────────────────


def test_netops_agent_md_references_analyzer():
    agent_md = WORKSPACE / "netops" / "AGENT.md"
    assert agent_md.is_file(), "netops/AGENT.md missing"
    text = agent_md.read_text(encoding="utf-8")
    assert "analyzer" in text, (
        "netops/AGENT.md must reference the analyzer sub-agent"
    )


def test_netops_agent_md_references_reporter():
    agent_md = WORKSPACE / "netops" / "AGENT.md"
    text = agent_md.read_text(encoding="utf-8")
    assert "reporter" in text, (
        "netops/AGENT.md must reference the reporter sub-agent (added 2026-05-26 split)"
    )
