"""Tests for two small operational fixes (2026-05-12):

  * ISSUE-ADMIN-STATUS-TOOLS-COUNT-ZERO — `olav admin status` was
    counting only legacy `.olav/tools/*.py` (usually empty); real
    tools live in `.olav/workspace/<agent>/tools/*.py` (and one
    sub-agent layer deeper post-rev-259). Fix counts BOTH places.

  * ISSUE-CH10-SYSLOG-CLOCK-SKEW-1H-WINDOW — `search_logs` used
    `NOW() - INTERVAL N HOUR` against host clock; when the host clock
    drifts vs the Parquet ingestion timestamps, narrow windows return
    zero rows even though data exists. Fix auto-falls-back to 24h
    window and surfaces a clock-skew hint.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


# ── ADMIN-STATUS-TOOLS-COUNT-ZERO ───────────────────────────────────────


def _make_workspace(tmp_path: Path, layout: list[tuple[str, int]]) -> Path:
    """Build a workspace tree at tmp_path with given (sub-path, n_tools) entries."""
    base = tmp_path / ".olav"
    (base / "workspace").mkdir(parents=True)
    for sub, n_tools in layout:
        d = base / "workspace" / sub
        d.mkdir(parents=True, exist_ok=True)
        # Create AGENT.md so agents_count works
        (d / "AGENT.md").write_text("---\nname: x\n---\n")
        tools_dir = d / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        for i in range(n_tools):
            (tools_dir / f"t{i}.py").write_text("# tool\n")
    return base


def test_admin_status_counts_workspace_tools(tmp_path, monkeypatch):
    """ADMIN-STATUS-TOOLS-COUNT-ZERO: count must reflect tools under
    `.olav/workspace/<agent>/tools/*.py`, not just legacy
    `.olav/tools/*.py`."""
    base = _make_workspace(tmp_path, [
        ("core", 5),
        ("netops", 12),
        ("audit", 8),
    ])
    monkeypatch.chdir(tmp_path)
    from olav.cli.admin import admin_handler
    out = asyncio.run(admin_handler("/admin status"))
    assert out["status"] == "success"
    # Allow for legacy `.olav/tools/` to also contribute (none in this
    # fixture), so check >= rather than ==.
    assert out["data"]["tools_count"] >= 25, (
        f"expected ≥25 tools across 3 agents; got {out['data']['tools_count']}"
    )


def test_admin_status_counts_subagent_tools(tmp_path, monkeypatch):
    """Post-rev-259 the audit workspace has nested sub-agents
    (runner/, author/, curator/), each with their own tools/ dir.
    The count MUST descend one level into those sub-agents too."""
    base = _make_workspace(tmp_path, [
        ("audit", 0),  # parent has no direct tools
        ("audit/runner", 4),
        ("audit/author", 3),
        ("audit/curator", 5),
    ])
    monkeypatch.chdir(tmp_path)
    from olav.cli.admin import admin_handler
    out = asyncio.run(admin_handler("/admin status"))
    assert out["data"]["tools_count"] >= 12, (
        "sub-agent tools must be counted via the 2-level glob"
    )


def test_admin_status_excludes_init_py(tmp_path, monkeypatch):
    """__init__.py files MUST NOT inflate the count — they're not tools."""
    base = _make_workspace(tmp_path, [("core", 3)])
    # Add __init__.py at every level
    for p in (base / "workspace" / "core" / "tools" / "__init__.py",):
        p.write_text("")
    monkeypatch.chdir(tmp_path)
    from olav.cli.admin import admin_handler
    out = asyncio.run(admin_handler("/admin status"))
    assert out["data"]["tools_count"] == 3


def test_admin_status_no_workspace_returns_zero(tmp_path, monkeypatch):
    """Fresh install with no workspace → tools_count = 0 (no error)."""
    monkeypatch.chdir(tmp_path)
    from olav.cli.admin import admin_handler
    out = asyncio.run(admin_handler("/admin status"))
    assert out["status"] == "success"
    assert out["data"]["tools_count"] == 0


# ── CH10-SYSLOG-CLOCK-SKEW-1H-WINDOW ────────────────────────────────────


@pytest.fixture
def parquet_log_dir(tmp_path):
    """Build a Parquet log dir with one record per hour offset listed."""
    import duckdb
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    # Write a parquet with timestamps offset from NOW().
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE syslog (timestamp TIMESTAMP, host VARCHAR, "
        "severity VARCHAR, facility VARCHAR, message VARCHAR)"
    )
    # 1 record 36h ago (outside any plausible <24h window) and 1 record
    # 12h ago (inside 24h fallback, outside 1h). Build the fixture so
    # `hours=1` returns 0 rows but `hours=24` returns 1.
    con.execute(
        "INSERT INTO syslog VALUES "
        "(NOW() - INTERVAL 12 HOUR, 'R1', 'CRITICAL', 'sys', 'BGP neighbor down'),"
        "(NOW() - INTERVAL 36 HOUR, 'R2', 'ERROR', 'sys', 'old message')"
    )
    con.execute(f"COPY syslog TO '{log_dir / 'logs.parquet'}' (FORMAT PARQUET)")
    con.close()
    return log_dir


def test_search_logs_clock_skew_fallback_widens_window(parquet_log_dir, monkeypatch):
    """When `hours=1` returns 0 rows but `hours=24` has matches,
    the fallback widens the window and emits a clock-skew hint."""
    import olav.data.workspace.core.scripts.search_logs as sl
    monkeypatch.setattr(sl, "_get_log_dir", lambda: parquet_log_dir)
    out = sl.search_logs(query="BGP", hours=1)
    assert "BGP neighbor down" in out, f"expected BGP row in fallback; got {out!r}"
    assert "Clock-skew" in out or "clock-skew" in out.lower(), (
        f"expected clock-skew hint; got {out!r}"
    )


def test_search_logs_no_fallback_when_results_found(parquet_log_dir, monkeypatch):
    """When the requested window already returns rows, no fallback
    and no hint."""
    import olav.data.workspace.core.scripts.search_logs as sl
    monkeypatch.setattr(sl, "_get_log_dir", lambda: parquet_log_dir)
    out = sl.search_logs(query="BGP", hours=24)
    assert "BGP neighbor down" in out
    assert "Clock-skew" not in out and "clock-skew" not in out.lower()


def test_search_logs_no_fallback_for_24h_or_wider(parquet_log_dir, monkeypatch):
    """If user explicitly asks for ≥24h and gets 0 rows, NO fallback —
    they already opted into the widest reasonable window. Avoids
    infinite widening loop."""
    import olav.data.workspace.core.scripts.search_logs as sl
    monkeypatch.setattr(sl, "_get_log_dir", lambda: parquet_log_dir)
    out = sl.search_logs(query="nonexistent_pattern_xyz", hours=24)
    assert "No log records found" in out
    assert "Clock-skew" not in out
