"""Routing-contract pins for the core orchestrator's system prompt.

Two surfaces matter:
  * `core/AGENT.md` — defines which sub-agents + tools the orchestrator sees
  * `core/prompts/system.md` — guides the LLM's tool-pick decisions

ISSUE-CH10-CORE-ORCHESTRATOR-DOESNT-DELEGATE-SYSLOG (P2, 2026-04-29):
qwen3.6:27b kept calling `execute_sql` against `parsed_outputs`/
`v_show_logging_auto` (device-side `show logging` snapshots) when the
user asked about syslog. The fix is purely prompt + tool surface; this
test guards against regression of the prompt hints.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_DATA = REPO_ROOT / "src" / "olav" / "data" / "workspace" / "core"


def _system_md() -> str:
    # core orchestrator uses SKILL.md body (no separate prompts/system.md since v0.20)
    skill_md = CORE_DATA / "SKILL.md"
    if skill_md.exists():
        return skill_md.read_text(encoding="utf-8")
    return (CORE_DATA / "prompts" / "system.md").read_text(encoding="utf-8")


def test_search_logs_is_a_direct_core_tool():
    """search_logs MUST be present as a direct tool under core/tools/ or core/scripts/.
    If it regresses to being only under admin/tools/ or a sub-agent,
    the core orchestrator has to delegate which qwen3.6:27b doesn't
    reliably do."""
    # Post-scripts-migration: check scripts/ first, fall back to tools/
    tool_file = CORE_DATA / "scripts" / "search_logs.py"
    if not tool_file.exists():
        tool_file = CORE_DATA / "tools" / "search_logs.py"
    assert tool_file.exists(), (
        f"search_logs.py missing from {CORE_DATA}/scripts/ and tools/ — core orchestrator "
        "must have it as a DIRECT tool, not behind a sub-agent boundary."
    )


def test_system_prompt_cheatsheet_routes_syslog_to_search_logs():
    """The Tool selection table in system.md MUST list `search_logs`
    against syslog/log/severity intent. Without this, small models
    fall back to execute_sql against the wrong table."""
    text = _system_md()
    assert "search_logs" in text, (
        "system.md no longer mentions search_logs — orchestrator has "
        "no hint to use the right tool for syslog queries"
    )
    # Cheatsheet table row check: 'Syslog' line must point at search_logs
    syslog_rows = [
        line for line in text.splitlines()
        if "Syslog" in line and "|" in line
    ]
    assert syslog_rows, "no syslog cheatsheet row found in system.md"
    assert any("search_logs" in r for r in syslog_rows), (
        f"syslog cheatsheet row(s) don't reference search_logs: {syslog_rows!r}"
    )


def test_system_prompt_anti_pattern_blocks_execute_sql_for_syslog():
    """Anti-pattern block MUST explicitly forbid execute_sql for syslog
    queries — the original CH10 demo failure was 9 pointless execute_sql
    calls against parsed_outputs."""
    text = _system_md()
    apat = text.split("## Anti-patterns", 1)[-1]
    assert "execute_sql" in apat and "syslog" in apat.lower(), (
        "Anti-patterns block must call out execute_sql-for-syslog as forbidden"
    )
    # The explicit redirect to search_logs must be in the same block
    assert "search_logs" in apat, (
        "Anti-pattern entry must redirect to search_logs"
    )


def test_syslog_routing_guide_exists():
    """A dedicated routing guide MUST exist so AutoRecall can inject
    it on syslog queries. Belt + braces with the cheatsheet."""
    # guides/ was renamed to references/ in v0.20
    guide = CORE_DATA / "references" / "syslog_search_during_troubleshooting.guide.yaml"
    if not guide.exists():
        guide = CORE_DATA / "guides" / "syslog_search_during_troubleshooting.guide.yaml"
    assert guide.exists(), (
        f"missing routing guide at {guide} — AutoRecall has no targeted "
        "memory entry to inject for syslog queries"
    )
    text = guide.read_text(encoding="utf-8")
    # Must declare critical syslog keywords for memory recall hits
    for kw in ("syslog", "search_logs", "severity"):
        assert kw in text, (
            f"guide missing keyword {kw!r} — recall match degraded"
        )
