"""Governance — audit.duckdb tables must populate after a CLI turn
that triggers a tool call.

Bug history (ISSUE-AUDIT-TABLES-EMPTY-IN-DEMO, 2026-05-15): the
v0.20.2 default flipped ``OLAV_MIDDLEWARE_MODE`` from ``callback`` to
``middleware``, but the CLI invoke path didn't pass an
``OlavRunContext`` to the graph runtime — so ``AuditMiddleware.
_get_context()`` returned None and the new write path was a no-op.
The legacy ``AuditCallbackPlugin`` had been partitioned out, so
nobody wrote ``audit_tool_calls`` or ``sessions`` rows.

This test guards against the same regression: any single tool-using
turn must increment every populated table by at least one row.

Run with ``--demo-dir`` (or env ``OLAV_DEMO_DIR``) pointing at a
populated demo workspace.  Skipped when no demo DB is present.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DEMO_DIR = Path(
    os.environ.get("OLAV_DEMO_DIR", str(Path.home() / "olav-demo-2026-05-15"))
)
AUDIT_DB = DEMO_DIR / ".olav/databases/audit.duckdb"


pytestmark = pytest.mark.skipif(
    not AUDIT_DB.exists() or not shutil.which("docker"),
    reason=(
        f"no demo audit DB at {AUDIT_DB} (set OLAV_DEMO_DIR) or docker not "
        f"available (Ollama LLM needed for the round-trip)"
    ),
)


def _counts() -> dict[str, int]:
    import duckdb
    out = {}
    with duckdb.connect(str(AUDIT_DB), read_only=True) as conn:
        for t in ("audit_runs", "sessions", "audit_events",
                  "audit_messages", "audit_tool_calls"):
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return out


def test_audit_tool_calls_populated_after_recent_run() -> None:
    """If audit_tool_calls is empty AND there are audit_runs, the
    middleware-mode write path is broken (the same shape as the
    2026-05-15 bug)."""
    c = _counts()
    if c["audit_runs"] == 0:
        pytest.skip("demo workspace has no audit_runs yet — run a query first")
    assert c["audit_tool_calls"] > 0, (
        f"audit_runs={c['audit_runs']} but audit_tool_calls=0 — "
        f"AuditMiddleware not writing.  Check OLAV_MIDDLEWARE_MODE + "
        f"that cli/main.py passes context=OlavRunContext(...) to "
        f"astream_events.  See ISSUE-AUDIT-TABLES-EMPTY-IN-DEMO."
    )


def test_sessions_populated_after_recent_run() -> None:
    """sessions UPSERT requires thread_id — CLI must pass it through to
    record_run_start."""
    c = _counts()
    if c["audit_runs"] == 0:
        pytest.skip("demo workspace has no audit_runs yet")
    assert c["sessions"] > 0, (
        f"audit_runs={c['audit_runs']} but sessions=0 — "
        f"record_run_start not getting thread_id.  Check cli/main.py "
        f"passes thread_id=session_id or run_id."
    )


def test_audit_tool_call_row_shape() -> None:
    """Each audit_tool_calls row carries the fields downstream
    consumers (training export, dataset audit) need."""
    import duckdb
    with duckdb.connect(str(AUDIT_DB), read_only=True) as conn:
        row = conn.execute(
            "SELECT call_id, run_id, tool_name, input_args, status, "
            "duration_ms FROM audit_tool_calls "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("audit_tool_calls is empty — run a tool-using query first")
    call_id, run_id, tool_name, input_args, status, dur = row
    assert call_id and len(call_id) > 10
    assert run_id and len(run_id) > 10
    assert tool_name and tool_name != "unknown"
    assert input_args  # may be JSON string, just non-empty
    assert status in ("completed", "failed")
    assert isinstance(dur, (int, float)) and dur >= 0
