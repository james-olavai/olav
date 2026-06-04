"""Tests for B: Jinja-first deterministic audit rendering.

Profile-level `narrative_mode: jinja` opt-in bypasses both per-section
and correlation-pass LLM calls, rendering everything from Jinja
templates against the findings JSON. Two runs over identical inputs
produce byte-identical reports — required for digital signing /
archival / regression diffs.

Default `narrative_mode: llm` keeps existing behaviour unchanged.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_RR_PATH = Path(
    Path(__file__).resolve().parents[2] / "olav-netops/.olav/workspace/audit/audit-runner/scripts/render_report.py"
)


@pytest.fixture(scope="module")
def rr():
    spec = importlib.util.spec_from_file_location("_test_rr_jinja", _RR_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_rr_jinja"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── _render_section_jinja ────────────────────────────────────────────────


def test_section_jinja_empty_findings_uses_placeholder(rr):
    """Zero findings → existing _empty_section placeholder (no LLM)."""
    out = rr._render_section_jinja("BGP_CHECK", {"count": 0, "findings": []})
    assert "BGP_CHECK" in out
    assert "No anomalies detected" in out


def test_section_jinja_renders_table_with_stable_columns(rr):
    """Findings render as Markdown table with pinned column order:
    device → metric_name → metric_value → rest alphabetical."""
    job = {
        "count": 2,
        "findings": [
            {"device": "R1", "metric_name": "X", "metric_value": 1,
             "zzz": "z", "aaa": "a", "severity_hint": "Critical"},
            {"device": "R2", "metric_name": "X", "metric_value": 2,
             "zzz": "z", "aaa": "a", "severity_hint": "Warning"},
        ],
    }
    out = rr._render_section_jinja("J1", job)
    # Header line — column order
    header = [ln for ln in out.split("\n") if ln.startswith("| device")][0]
    cols = [c.strip() for c in header.strip("|").split("|")]
    assert cols.index("device") < cols.index("metric_name") < cols.index("metric_value")
    assert cols.index("metric_value") < cols.index("aaa") < cols.index("zzz")
    # Tally line
    assert "1 Critical / 1 Warning / 0 Info" in out


def test_section_jinja_hides_internal_keys(rr):
    """Internal fields (_warning, _source, severity_hint) NEVER appear
    as table columns."""
    job = {
        "count": 1,
        "findings": [{
            "device": "R1",
            "_source": {"table": "x"},
            "_warning": "stale",
            "severity_hint": "Critical",
            "metric_value": 5,
        }],
    }
    out = rr._render_section_jinja("J1", job)
    header = [ln for ln in out.split("\n") if ln.startswith("| device")][0]
    assert "_source" not in header
    assert "_warning" not in header
    assert "severity_hint" not in header
    # But severity ICON still rendered in the Severity column
    assert "🔴 Critical" in out


def test_section_jinja_supports_zh_locale(rr):
    """Chinese tally + header label."""
    job = {"count": 1, "findings": [{"device": "R1", "severity_hint": "Critical"}]}
    out = rr._render_section_jinja("J1", job, lang="zh")
    assert "严重度" in out  # Chinese header label
    assert "本节统计" in out
    assert "1 严重" in out


# ── _render_executive_summary_jinja ──────────────────────────────────────


def test_exec_summary_jinja_includes_tallies_verdict_items(rr):
    audit = {
        "jobs": {
            "BGP": {"findings": [
                {"device": "SW1", "metric_name": "BGP", "metric_value": 0,
                 "severity_hint": "Critical"},
                {"device": "R1", "metric_name": "BGP", "metric_value": 1,
                 "severity_hint": "Warning"},
            ]},
        },
        "freshness_warning": None,
    }
    out = rr._render_executive_summary_jinja(audit, {}, "en")
    assert "1 Critical and 1 Warning" in out
    assert "🔴 SW1" in out  # critical first
    assert "⚠️ R1" in out
    # Verdict reflects worst severity
    assert "Network Health" in out
    assert "🔴 Critical" in out


def test_exec_summary_jinja_freshness_takes_precedence(rr):
    """Freshness warning → action #1 + verdict modified."""
    audit = {
        "jobs": {
            "X": {"findings": [
                {"device": "R1", "metric_name": "M", "metric_value": 9,
                 "severity_hint": "Critical"},
            ]},
        },
        "freshness_warning": {
            "type": "stale_data",
            "max_hours_since_last_seen": 273.0,
        },
    }
    out = rr._render_executive_summary_jinja(audit, {}, "en")
    # Stale-data line is item #1
    assert "1. 🔴 Global — Stale data (273.0h)" in out
    # Verdict marks unverified
    assert "🔴 Critical (unverified)" in out


def test_exec_summary_jinja_clean_run(rr):
    """No Critical / Warning / freshness → clean verdict + no action items."""
    audit = {"jobs": {}, "freshness_warning": None}
    out = rr._render_executive_summary_jinja(audit, {}, "en")
    assert "0 Critical and 0 Warning" in out
    assert "✅ No action items required" in out
    assert "✅ Healthy" in out


# ── End-to-end byte-determinism (no DB / no LLM) ─────────────────────────


def test_byte_determinism_via_jinja_path(rr, tmp_path):
    """Two calls to render_report with narrative_mode=jinja over the
    same audit JSON produce byte-identical output files (modulo file
    name timestamp)."""
    import json as _json
    audit = {
        "profile": "byte_det",
        "window": "1h",
        "generated_at": "2026-05-12T00:00:00+00:00",
        "freshness_warning": None,
        "jobs": {
            "BGP": {"count": 2, "findings": [
                {"device": "SW1", "metric_name": "BGP", "metric_value": 0,
                 "severity_hint": "Critical"},
                {"device": "R1", "metric_name": "BGP", "metric_value": 2,
                 "severity_hint": "Info"},
            ]},
        },
        "incident_clusters": [],
    }
    json_path = tmp_path / "audit.json"
    json_path.write_text(_json.dumps(audit))
    profile = tmp_path / "byte_det.md"
    profile.write_text(
        "---\nname: byte_det\nnarrative_mode: jinja\n"
        "jobs:\n  - name: BGP\n    type: sql\n    severity: Info\n"
        "    query: \"SELECT 1\"\n    section_prompt: dummy\n---\n# body\n"
    )
    # Render twice with the same input
    r1 = rr.render_report(
        json_path=str(json_path), profile_path=str(profile),
        output_dir=str(tmp_path / "run1"),
    )
    r2 = rr.render_report(
        json_path=str(json_path), profile_path=str(profile),
        output_dir=str(tmp_path / "run2"),
    )
    import re as _re
    p1 = Path(_re.search(r"Report saved:\s+(\S+)", r1).group(1))
    p2 = Path(_re.search(r"Report saved:\s+(\S+)", r2).group(1))
    # Resolve relative paths against cwd if necessary
    if not p1.is_absolute():
        p1 = Path.cwd() / p1
    if not p2.is_absolute():
        p2 = Path.cwd() / p2
    assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8"), (
        "narrative_mode=jinja MUST produce byte-identical report bodies "
        "across runs — this is the determinism contract that enables "
        "signed / archived audit reports."
    )
