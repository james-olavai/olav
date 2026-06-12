"""ARCH-11 Phase 1: ``emit_sources`` profile flag decorates findings.

When a profile sets ``emit_sources: true``:
    * anomaly_engine attaches a ``_source`` dict to each finding
    * map_engine attaches ``_source`` to SQL-job findings
    * render_report surfaces an ``Evidence`` markdown block with
      ``[src: …]`` tags pulled from each finding's ``_source``

When the flag is absent (default) nothing is added — existing audit
reports stay byte-identical.

NOTE (rev 274, 2026-05-12): audit collapsed to single ``type: sql``
after the collect/audit boundary review. anomaly_engine +
baseline_engine were deleted; the elif chain in map_engine for
lancedb/anomaly/api_anomaly was replaced with a deprecation
warning. The map_engine._attach_sql_sources contract still applies
to SQL findings — but the auditor/ → runner/ path move (rev 259)
plus the engine deletions (rev 274) make every test here probe
files that no longer exist. The whole file is xfail'd; rewrite
against ``audit/runner/tools/map_engine.py`` if you want this
governance check live again.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.xfail(
    reason=(
        "rev 259 moved audit/auditor/ → audit/runner/; rev 274 deleted "
        "anomaly_engine.py + baseline_engine.py. AUDITOR_TOOLS path "
        "below points at a directory that no longer exists. Either "
        "delete this file or rewrite against runner/tools/map_engine.py "
        "(the sql-side _attach_sql_sources still exists)."
    ),
    strict=False,
)

REPO = Path(__file__).resolve().parents[2]
AUDITOR_TOOLS = REPO / ".olav" / "workspace" / "audit" / "auditor" / "tools"


def _load(mod_name: str):
    path = AUDITOR_TOOLS / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(f"{mod_name}_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _format_source_suffix ─────────────────────────────────────────────────────


def test_format_source_suffix_empty_returns_empty():
    render = _load("render_report")
    assert render._format_source_suffix(None) == ""
    assert render._format_source_suffix({}) == ""


def test_format_source_suffix_full_tag():
    render = _load("render_report")
    out = render._format_source_suffix(
        {
            "table": "netops.parsed_outputs",
            "snapshot_id": "snap_20260101",
            "device": "R1",
            "row_index": 5,
        }
    )
    assert out.startswith("[src: ")
    assert out.endswith("]")
    assert "netops.parsed_outputs#snap_20260101" in out
    assert "device=R1" in out
    assert "row=5" in out


def test_format_source_suffix_table_only():
    render = _load("render_report")
    out = render._format_source_suffix({"table": "netops.topology_links"})
    assert out == "[src: netops.topology_links]"


# ── _build_evidence_block ────────────────────────────────────────────────────


def test_evidence_block_omitted_when_no_sources():
    render = _load("render_report")
    findings = [{"device_name": "R1", "count": 3}, {"device_name": "R2"}]
    assert render._build_evidence_block(findings) == ""


def test_evidence_block_lists_each_source():
    render = _load("render_report")
    findings = [
        {
            "device_name": "R1",
            "_source": {
                "table": "netops.parsed_outputs",
                "snapshot_id": "snap_A",
                "device": "R1",
                "row_index": 0,
            },
        },
        {
            "device_name": "R2",
            "_source": {
                "table": "netops.parsed_outputs",
                "snapshot_id": "snap_A",
                "device": "R2",
                "row_index": 1,
            },
        },
    ]
    block = render._build_evidence_block(findings)
    assert "## Evidence" in block
    assert "device=R1" in block
    assert "device=R2" in block
    assert "row=0" in block and "row=1" in block


# ── _attach_sql_sources ──────────────────────────────────────────────────────


def test_attach_sql_sources_reads_from_clause():
    map_eng = _load("map_engine")
    findings = [
        {"device_name": "R1", "count": 3, "snapshot_id": "snap_X"},
        {"device_name": "R2", "count": 1, "snapshot_id": "snap_X"},
    ]
    map_eng._attach_sql_sources(
        findings,
        "SELECT device_name, count FROM netops.parsed_outputs "
        "WHERE command ILIKE '%ospf%'",
    )
    assert findings[0]["_source"]["table"] == "netops.parsed_outputs"
    assert findings[0]["_source"]["device"] == "R1"
    assert findings[0]["_source"]["snapshot_id"] == "snap_X"
    assert findings[0]["_source"]["row_index"] == 0
    assert findings[1]["_source"]["row_index"] == 1


def test_attach_sql_sources_unknown_table():
    map_eng = _load("map_engine")
    findings = [{"x": 1}]
    map_eng._attach_sql_sources(findings, "SELECT 1")
    assert findings[0]["_source"]["table"] == "unknown"


# ── anomaly_engine emit_sources propagation ──────────────────────────────────


def test_anomaly_engine_signature_accepts_emit_sources():
    anomaly = _load("anomaly_engine")
    import inspect

    sig = inspect.signature(anomaly.run_anomaly_job)
    assert "emit_sources" in sig.parameters, (
        "run_anomaly_job must accept emit_sources kwarg (ARCH-11 Phase 1)"
    )
    assert sig.parameters["emit_sources"].default is False


def test_map_engine_reads_emit_sources_flag():
    """Map engine must propagate the profile flag into anomaly + SQL paths."""
    src = (AUDITOR_TOOLS / "map_engine.py").read_text(encoding="utf-8")
    assert 'profile.get("emit_sources"' in src, (
        "map_engine must read emit_sources from profile config"
    )
    assert "_attach_sql_sources" in src, (
        "map_engine must call _attach_sql_sources when emit_sources is true"
    )
