"""analyzer/inspect_blast_radius — quantified impact for change plans (2026-07-18).

Design decision: redundancy/decommission-class change plans need a cited
blast-radius number in their Risk section (ITIL: impact assessment is the
change author's duty), but the orchestrator routes to ONE sub-agent and the
analyzer cannot reach reporter — so the analyzer gets the SCRIPT twin of
reporter's @tool (no tool-slot cost, no schema overhead). Routing stays
clean: the blast_radius INTENT remains reporter-only.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
NETOPS_WS = REPO / "olav-netops" / ".olav" / "workspace" / "netops"
SKILLPACK_WS = (REPO / "olav-netops" / "src" / "olav_netops" / "data" / "skillpack"
                / ".olav" / "workspace" / "netops")


def _frontmatter(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8").split("---")[1])


def test_analyzer_declares_blast_radius_script_in_both_copies():
    for ws in (NETOPS_WS, SKILLPACK_WS):
        fm = _frontmatter(ws / "analyzer" / "SKILL.md")
        entries = {s["name"]: s for s in fm.get("scripts", [])}
        assert "inspect_blast_radius" in entries, f"missing in {ws}"
        assert entries["inspect_blast_radius"]["file"] == "inspect_blast_radius.py"
        assert "execute_skill_script" in fm["tools"]


def test_analyzer_script_byte_identical_to_canonical():
    """Duplicated shared scripts must match the canonical netops/scripts copy."""
    canonical = (NETOPS_WS / "scripts" / "inspect_blast_radius.py").read_bytes()
    for ws in (NETOPS_WS, SKILLPACK_WS):
        dup = (ws / "analyzer" / "scripts" / "inspect_blast_radius.py").read_bytes()
        assert dup == canonical, f"{ws}/analyzer copy drifted from canonical"


def test_blast_radius_intent_stays_reporter_only():
    """The routing boundary: 'blast radius' as a user-facing intent belongs to
    reporter; the analyzer uses the script internally while drafting. If this
    fails, someone added the intent to analyzer and the orchestrator can now
    misroute what-if investigations."""
    analyzer_fm = _frontmatter(NETOPS_WS / "analyzer" / "SKILL.md")
    reporter_fm = _frontmatter(NETOPS_WS / "reporter" / "SKILL.md")
    assert "blast_radius" not in (analyzer_fm["metadata"].get("intents") or [])
    assert "blast_radius" in (reporter_fm["metadata"].get("intents") or [])
    assert "blast" not in analyzer_fm["description"].lower().replace(
        "blast-radius what-if, use reporter", ""
    ), "analyzer description should not advertise blast radius (routing signal)"
