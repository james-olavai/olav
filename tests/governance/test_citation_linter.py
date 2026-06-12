"""ARCH-11 Phase 2: citation linter flags sections without [src: …] tags."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.governance._paths import AUDIT_RUNNER_TOOLS

REPO = Path(__file__).resolve().parents[2]
LINTER_PY = AUDIT_RUNNER_TOOLS / "render_report_linter.py"


def _load():
    # dataclass(@dataclass) accesses sys.modules[cls.__module__] during class
    # creation, so we must register the module there before exec_module runs.
    import sys
    spec = importlib.util.spec_from_file_location("linter_under_test", LINTER_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_linter_module_exists():
    assert LINTER_PY.exists()


def test_clean_report_produces_no_violations():
    mod = _load()
    md = (
        "## CPU_Anomaly\n\n"
        "Finding: device R1 has CPU spike.\n"
        "[src: netops.parsed_outputs#snap_A; device=R1; row=0]\n\n"
        "## Memory_Anomaly\n\n"
        "[src: netops.parsed_outputs#snap_A; device=R2]\n\n"
    )
    assert mod.lint_citations(md) == []


def test_missing_citation_is_flagged():
    mod = _load()
    md = (
        "## CPU_Anomaly\n\nFinding: device R1 CPU is spiking.\n\n"
        "## Memory_Anomaly\n\n[src: netops.parsed_outputs; device=R2]\n\n"
    )
    violations = mod.lint_citations(md)
    assert len(violations) == 1
    assert violations[0].section == "CPU_Anomaly"


def test_executive_summary_and_playbook_skipped():
    mod = _load()
    md = (
        "## Executive Summary\n\nAll good.\n\n"
        "## Playbook\n\n1. Check A\n2. Check B\n\n"
        "## CPU_Anomaly\n\n[src: netops.parsed_outputs; device=R1]\n\n"
    )
    assert mod.lint_citations(md) == []


def test_non_empty_section_allowlist_filters_placeholders():
    """When the caller knows which sections are non-empty, only those are audited."""
    mod = _load()
    md = (
        "## CPU_Anomaly\n\nno findings — placeholder.\n\n"  # count==0 -> not in allowlist
        "## Memory_Anomaly\n\nFinding: device R1.\n"       # no cite -> violation
    )
    violations = mod.lint_citations(md, non_empty_sections={"Memory_Anomaly"})
    assert [v.section for v in violations] == ["Memory_Anomaly"]


def test_format_audit_block_success_case():
    mod = _load()
    out = mod.format_audit_block([])
    assert "Citation Audit" in out
    assert "All non-empty sections" in out


def test_format_audit_block_violation_case():
    mod = _load()
    v = mod.CitationViolation(section="CPU_Anomaly", line=5, note="missing")
    out = mod.format_audit_block([v])
    assert "CPU_Anomaly" in out
    assert "line 5" in out
    assert "⚠️" in out


def test_render_report_integrates_linter():
    """render_report.py must wire the linter in behind the emit_sources flag."""
    render = (AUDIT_RUNNER_TOOLS / "render_report.py").read_text(
        encoding="utf-8"
    )
    assert "from render_report_linter import" in render, (
        "render_report.py should import the linter module"
    )
    assert "lint_report_file" in render
    assert "format_audit_block" in render
