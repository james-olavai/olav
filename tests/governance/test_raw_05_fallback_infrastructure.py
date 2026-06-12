"""RAW-05 (Round 37) — raw_output_store fallback infrastructure pins.

Closes RAW-05 by pinning the runtime wiring (``map_engine._raw_fallback_probe``
kicks in when a profile job sets ``raw_fallback: true``) plus the four
consumer-facing discoverability surfaces:

* ``take_snapshot`` docstring + ``next_step`` advertise raw_output_store
* ``anomaly_engine`` docstring describes the raw_fallback contract
* ``ROUTING_EXPERT_GUIDE.md`` mentions the UNION ALL pattern
* ``health_full_drift`` profile carries ``raw_fallback: true`` on both
  parse-prone anomaly jobs (CPU_Anomaly, Memory_Anomaly)

The runtime wiring is load-bearing — if a future refactor drops the
``_raw_fallback_probe`` call site, ``raw_fallback: true`` becomes a
silent no-op and TextFSM-parse failures look like a clean bill of
health. Test #2 prevents that silently.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.xfail(
    reason=(
        "rev 274 audit collapse: anomaly_engine deleted (audit is now "
        "single-type=sql; profiles use SQL CTEs for any anomaly logic). "
        "rev 259 also moved audit/auditor/ → audit/runner/. Paths below "
        "(MAP_ENGINE / ANOMALY_ENGINE under auditor/tools/) no longer "
        "exist. The raw_fallback runtime in map_engine._raw_fallback_probe "
        "still works for sql jobs; rewrite this governance pin against "
        "audit/runner/tools/map_engine.py if you want it live again."
    ),
    strict=False,
)

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"

MAP_ENGINE = WORKSPACE / "audit" / "auditor" / "tools" / "map_engine.py"
ANOMALY_ENGINE = WORKSPACE / "audit" / "auditor" / "tools" / "anomaly_engine.py"
TAKE_SNAPSHOT = WORKSPACE / "ops" / "tools" / "take_snapshot.py"
ROUTING_GUIDE = WORKSPACE / "ops" / "analyze" / "references" / "ROUTING_EXPERT_GUIDE.md"
HEALTH_PROFILE = WORKSPACE / "audit" / "profiles" / "health_full_drift.md"


# ── infrastructure pins (protect already-shipped runtime behaviour) ──────


def test_files_exist():
    for path in (MAP_ENGINE, ANOMALY_ENGINE, TAKE_SNAPSHOT, ROUTING_GUIDE, HEALTH_PROFILE):
        assert path.is_file(), f"missing RAW-05 consumer: {path}"


def test_map_engine_has_raw_fallback_probe():
    src = MAP_ENGINE.read_text(encoding="utf-8")
    assert "def _raw_fallback_probe(" in src, (
        "map_engine._raw_fallback_probe helper disappeared — this is the "
        "load-bearing RAW-05 probe; raw_fallback: true jobs would become no-ops."
    )


def test_map_engine_wires_probe_in_both_branches():
    """SQL + anomaly branches must both call _raw_fallback_probe."""
    src = MAP_ENGINE.read_text(encoding="utf-8")
    # At least two call sites — one for SQL job type, one for anomaly job type.
    call_count = src.count("_raw_fallback_probe(")
    # Includes the def line; subtract 1 for the definition.
    assert call_count >= 3, (
        f"Expected _raw_fallback_probe wired in both SQL and anomaly branches "
        f"(def + 2 call sites = 3 occurrences). Found: {call_count}. "
        f"RAW-05 fallback may be disabled on one branch."
    )


def test_map_engine_probe_signature():
    """The probe signature (conn, query, max_findings) must stay stable —
    the profile-driven call sites pass these positional args, so reordering
    or renaming breaks the wiring silently."""
    src = MAP_ENGINE.read_text(encoding="utf-8")
    # Locate the def line; look for conn and query and max_findings in params.
    assert "def _raw_fallback_probe(" in src
    # Get ~200 chars after the def
    idx = src.index("def _raw_fallback_probe(")
    chunk = src[idx : idx + 400]
    for expected in ("conn", "query", "max_findings"):
        assert expected in chunk, (
            f"_raw_fallback_probe no longer accepts '{expected}'; callers in "
            f"map_engine.py pass it positionally — silent behavioural change risk."
        )


def test_map_engine_emits_raw_only_data_warning():
    """Sentinel _warning: raw_only_data is the operator-visible signal."""
    src = MAP_ENGINE.read_text(encoding="utf-8")
    assert "raw_only_data" in src, (
        "Lost 'raw_only_data' sentinel — TextFSM parse failures will no longer "
        "surface as warnings in findings output."
    )


# ── profile flags (opt-in markers that activate the infrastructure) ─────


def test_health_profile_has_raw_fallback_flags():
    """CPU_Anomaly and Memory_Anomaly are the two parse-prone jobs — they
    must stay opted into raw fallback, otherwise Junos/SR Linux CPU/memory
    parse failures silently become 'no anomalies detected'."""
    src = HEALTH_PROFILE.read_text(encoding="utf-8")
    # Both flags present
    assert src.count("raw_fallback: true") >= 2, (
        f"Expected raw_fallback: true on at least 2 jobs (CPU_Anomaly + "
        f"Memory_Anomaly). Found {src.count('raw_fallback: true')} occurrence(s)."
    )
    # Near CPU_Anomaly / Memory_Anomaly sections
    for job_name in ("CPU_Anomaly", "Memory_Anomaly"):
        assert job_name in src, f"Lost {job_name} job in health_full_drift profile"


# ── consumer-facing discoverability (Round 37 additions) ────────────────


def test_take_snapshot_docstring_mentions_raw_output_store():
    src = TAKE_SNAPSHOT.read_text(encoding="utf-8")
    assert "raw_output_store" in src, (
        "take_snapshot.py docstring lost raw_output_store reference; operators "
        "reading the tool docstring would not know raw fallback exists (RAW-05 "
        "Round 37 regression)."
    )


def test_take_snapshot_next_step_advertises_raw_fallback():
    """The next_step hint returned to the LLM must mention raw_output_store
    so downstream tool calls know where to look when parse fails."""
    src = TAKE_SNAPSHOT.read_text(encoding="utf-8")
    # Find the next_step literal and ensure raw_output_store is part of it.
    assert 'next_step' in src, "take_snapshot next_step key removed"
    # A coarse but effective check: RAW-05 tag sits in the hint string.
    assert "RAW-05" in src, (
        "take_snapshot next_step no longer tags RAW-05; discoverability pin lost."
    )


def test_anomaly_engine_docstring_describes_raw_fallback():
    src = ANOMALY_ENGINE.read_text(encoding="utf-8")
    assert "Raw fallback" in src or "raw_fallback" in src, (
        "anomaly_engine.py docstring lost the raw fallback explanation."
    )
    assert "raw_output_store" in src, (
        "anomaly_engine.py docstring must mention raw_output_store so profile "
        "authors know where the sentinel findings come from."
    )
    assert "raw_only_data" in src, (
        "anomaly_engine.py docstring lost the raw_only_data sentinel name; "
        "operators reading the engine docs would not recognise the warning."
    )


def test_routing_expert_guide_mentions_raw_fallback():
    src = ROUTING_GUIDE.read_text(encoding="utf-8")
    assert "raw_output_store" in src, (
        "ROUTING_EXPERT_GUIDE.md lost the RAW-05 note; snapshot-boundary "
        "queries no longer document the raw fallback pattern."
    )
    assert "UNION ALL" in src, (
        "ROUTING_EXPERT_GUIDE.md lost the UNION ALL example that shows how to "
        "cover raw-only snapshots."
    )


def test_routing_expert_guide_tags_raw_05():
    src = ROUTING_GUIDE.read_text(encoding="utf-8")
    assert "RAW-05" in src, (
        "ROUTING_EXPERT_GUIDE.md lost the RAW-05 issue tag; future readers "
        "can't cross-reference the note to the governance issue."
    )
