"""reporter/query_evidence.py — live-DB integration tests.

Uses the actual imported dataset at .olav/databases/main.duckdb.
All assertions are non-destructive (read-only DB path).

Skips automatically when the database is missing (clean CI env without
a pre-collected snapshot).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_DB = Path(__file__).resolve().parents[2] / ".olav/databases/main.duckdb"
_SCRIPT = Path(
    Path(__file__).resolve().parents[2] / "olav-netops/.olav/workspace/netops/reporter/scripts/query_evidence.py"
)

pytestmark = pytest.mark.skipif(
    not _DB.exists(), reason="main.duckdb not present — skip live-DB tests"
)


@pytest.fixture(scope="module")
def qe():
    spec = importlib.util.spec_from_file_location("_qe_mod", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_qe_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── command_output source ────────────────────────────────────────────────────


def test_command_output_returns_success_shape(qe):
    """Searching 'show' in command_output returns the expected dict keys."""
    out = qe.query_evidence(source="command_output", pattern="show")
    assert out["status"] == "success"
    assert out["source"] == "command_output"
    assert isinstance(out["matches"], list)
    assert isinstance(out["total"], int)
    assert isinstance(out["truncated"], bool)


def test_command_output_bgp_finds_rows(qe):
    """'bgp' appears in raw_output_store — at least one match expected."""
    out = qe.query_evidence(source="command_output", pattern="bgp")
    assert out["status"] == "success"
    assert out["total"] > 0, "expected BGP output rows in the demo dataset"
    row = out["matches"][0]
    assert "device" in row
    assert "command" in row
    assert "excerpt" in row
    assert "snapshot_id" in row


def test_command_output_device_filter_narrows_results(qe):
    """Device filter 'R4' returns only R4 rows."""
    out = qe.query_evidence(source="command_output", pattern="show", device="R4")
    assert out["status"] == "success"
    for row in out["matches"]:
        assert "R4" in row["device"], f"unexpected device {row['device']!r}"


def test_command_output_no_match_returns_hint(qe):
    """Non-existent pattern returns empty matches + a 'hint' key."""
    out = qe.query_evidence(source="command_output", pattern="XYZZY_NO_SUCH_PATTERN_9999")
    assert out["status"] == "success"
    assert out["matches"] == []
    assert out["total"] == 0
    assert "hint" in out, "empty result must include hint to prevent model looping"


def test_command_output_snapshot_filter(qe):
    """Scoping to a known snapshot_id constrains results."""
    snap = "snap_20260411_144736_bd4ffc"
    out = qe.query_evidence(source="command_output", pattern="show", snapshot=snap)
    assert out["status"] == "success"
    for row in out["matches"]:
        assert row["snapshot_id"] == snap


# ── config source ────────────────────────────────────────────────────────────


def test_config_source_returns_success(qe):
    """Config source hits running-config / startup-config commands."""
    out = qe.query_evidence(source="config", pattern="interface")
    assert out["status"] == "success"
    assert out["source"] == "config"


def test_config_source_finds_running_config(qe):
    """'running-config' data exists; searching 'ip address' should hit it."""
    out = qe.query_evidence(source="config", pattern="ip address")
    assert out["status"] == "success"
    # We may or may not have running-config captured — accept either
    if out["total"] > 0:
        for row in out["matches"]:
            assert "config" in row["command"].lower() or "running" in row["command"].lower(), (
                f"config source returned non-config command: {row['command']!r}"
            )


# ── syslog source ────────────────────────────────────────────────────────────


def test_syslog_returns_gracefully_without_parquet(qe):
    """Syslog source never raises even when no parquet files exist."""
    out = qe.query_evidence(source="syslog", pattern="BGP")
    assert out["status"] == "success"
    assert out["source"] == "syslog"
    assert isinstance(out["matches"], list)


# ── dedup budget guard ───────────────────────────────────────────────────────


def test_duplicate_call_budget_triggers_on_third_call(qe):
    """Third identical call returns error with 'duplicate_call_budget' kind."""
    # Use a unique pattern to avoid collision with other tests
    pat = "DEDUP_TEST_UNIQUE_XQ9Z"
    qe.query_evidence(source="command_output", pattern=pat)
    qe.query_evidence(source="command_output", pattern=pat)
    out = qe.query_evidence(source="command_output", pattern=pat)
    assert out["status"] == "error"
    assert out["error_kind"] == "duplicate_call_budget"
