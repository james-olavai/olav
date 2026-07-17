"""analyzer's format_and_export is terminal (return_direct) — stop discipline.

A change plan is one file (analyzer constraint #5), so the agent must STOP the
moment format_and_export saves it. Without this, small local models (gemma4-31b)
keep querying after the file is written and time out. Declared in the analyzer
SKILL.md as ``return_direct_tools: [format_and_export]`` and applied in
``_build_subagents`` on THIS agent's fresh tool instance (reporter, which
append-exports repeatedly, must NOT be affected).

Verified from the real OLAVAgent build path (DoD: wiring proof), via the
info-log the injection emits — the compiled sub-agent's tools are opaque.
"""
from __future__ import annotations

import logging

import pytest


def test_analyzer_skill_declares_format_and_export_terminal():
    """The SKILL.md contract itself."""
    import frontmatter
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    skill = repo / "olav-netops" / ".olav" / "workspace" / "netops" / "analyzer" / "SKILL.md"
    md = frontmatter.load(skill)
    rd = md.metadata.get("return_direct_tools") or []
    assert "format_and_export" in rd, (
        "analyzer must declare format_and_export as return_direct_tools"
    )


def test_build_sets_return_direct_on_analyzer_format_and_export(caplog):
    """Real build path: constructing the netops agent must set return_direct
    on the analyzer sub-agent's format_and_export instance."""
    pytest.importorskip("deepagents")
    from olav.agents.agent import OLAVAgent

    with caplog.at_level(logging.INFO):
        OLAVAgent(agent_id="netops")

    hit = [
        r.getMessage() for r in caplog.records
        if "analyzer" in r.getMessage()
        and "format_and_export" in r.getMessage()
        and "return_direct=True" in r.getMessage()
    ]
    assert hit, (
        "expected the return_direct injection log for analyzer/format_and_export; "
        "the terminal-tool stop discipline did not fire from the real build path"
    )
