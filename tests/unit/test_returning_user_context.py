"""§7.3 returning-user session continuity (dev_docs/99).

``_check_returning_user_context()`` queues a deterministic "last time we
were working on X" line (most recent recorded user query + humanized age,
no LLM) for the TUI welcome screen. Covers:
1. recent user message → context queued with snippet + age
2. no audit DB (true first run) → silent
3. last activity older than 7 days → silent (stale context is noise)
4. user scoping — another user's messages don't leak into my greeting
5. long queries truncated for display
6. corrupt/unreadable DB → silent, never raises
7. wiring: _ensure_bootstrapped calls it on every launch
8. footer rendering: context line coexists with a finding (not either/or)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import duckdb

import olav.cli.main as main_mod
import olav.cli.tui_overlay as overlay
import olav.core.config as config_mod


def _make_audit_db(path, messages) -> None:
    """messages: list of (user_id, role, content, timestamp)."""
    with duckdb.connect(str(path)) as conn:
        conn.execute("CREATE TABLE audit_runs (run_id VARCHAR, user_id VARCHAR)")
        conn.execute(
            "CREATE TABLE audit_messages "
            "(run_id VARCHAR, role VARCHAR, content VARCHAR, timestamp TIMESTAMP)"
        )
        for i, (user_id, role, content, ts) in enumerate(messages):
            run_id = f"run-{i}"
            conn.execute("INSERT INTO audit_runs VALUES (?, ?)", [run_id, user_id])
            conn.execute(
                "INSERT INTO audit_messages VALUES (?, ?, ?, ?)",
                [run_id, role, content, ts],
            )


def test_recent_message_queues_context(tmp_path, monkeypatch) -> None:
    overlay.consume_welcome_context()
    db = tmp_path / "audit.duckdb"
    _make_audit_db(db, [("alice", "user", "why is R1's BGP flapping?", datetime.now() - timedelta(hours=2))])
    monkeypatch.setattr(config_mod, "AUDIT_DB_PATH", db)
    monkeypatch.setenv("USER", "alice")

    main_mod._check_returning_user_context()

    context = overlay.consume_welcome_context()
    assert context is not None
    assert "why is R1's BGP flapping?" in context
    assert "2h ago" in context


def test_no_audit_db_is_silent(tmp_path, monkeypatch) -> None:
    overlay.consume_welcome_context()
    monkeypatch.setattr(config_mod, "AUDIT_DB_PATH", tmp_path / "missing.duckdb")

    main_mod._check_returning_user_context()

    assert overlay.consume_welcome_context() is None


def test_stale_history_is_silent(tmp_path, monkeypatch) -> None:
    overlay.consume_welcome_context()
    db = tmp_path / "audit.duckdb"
    _make_audit_db(db, [("alice", "user", "old question", datetime.now() - timedelta(days=30))])
    monkeypatch.setattr(config_mod, "AUDIT_DB_PATH", db)
    monkeypatch.setenv("USER", "alice")

    main_mod._check_returning_user_context()

    assert overlay.consume_welcome_context() is None


def test_other_users_messages_do_not_leak(tmp_path, monkeypatch) -> None:
    overlay.consume_welcome_context()
    db = tmp_path / "audit.duckdb"
    _make_audit_db(db, [("bob", "user", "bob's secret investigation", datetime.now() - timedelta(hours=1))])
    monkeypatch.setattr(config_mod, "AUDIT_DB_PATH", db)
    monkeypatch.setenv("USER", "alice")

    main_mod._check_returning_user_context()

    assert overlay.consume_welcome_context() is None


def test_long_query_truncated(tmp_path, monkeypatch) -> None:
    overlay.consume_welcome_context()
    db = tmp_path / "audit.duckdb"
    long_q = "please analyze " + "the BGP neighbours on every router " * 10
    _make_audit_db(db, [("alice", "user", long_q, datetime.now() - timedelta(minutes=10))])
    monkeypatch.setattr(config_mod, "AUDIT_DB_PATH", db)
    monkeypatch.setenv("USER", "alice")

    main_mod._check_returning_user_context()

    context = overlay.consume_welcome_context()
    assert context is not None
    assert "…" in context
    assert len(context) < 160


def test_corrupt_db_never_raises(tmp_path, monkeypatch) -> None:
    overlay.consume_welcome_context()
    corrupt = tmp_path / "audit.duckdb"
    corrupt.write_text("not a duckdb file", encoding="utf-8")
    monkeypatch.setattr(config_mod, "AUDIT_DB_PATH", corrupt)

    main_mod._check_returning_user_context()  # must not raise

    assert overlay.consume_welcome_context() is None


def test_bootstrap_wiring_calls_context_check(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": "sk-existing"}}), encoding="utf-8"
    )
    called = {"ctx": False}
    monkeypatch.setattr(
        main_mod, "_check_returning_user_context", lambda: called.__setitem__("ctx", True)
    )
    monkeypatch.setattr(main_mod, "_run_extension_first_run_checks", lambda: None)

    assert asyncio.run(main_mod._ensure_bootstrapped()) is True
    assert called["ctx"] is True


def test_footer_renders_context_alongside_finding() -> None:
    overlay.consume_welcome_context()
    overlay.consume_first_run_finding()
    overlay.set_welcome_context("Welcome back — last time (2h ago): “BGP flap”")
    overlay.add_first_run_finding("embedding degraded")

    # Simulate what the patched footer assembles (slot semantics, not Textual)
    context = overlay.consume_welcome_context()
    finding = overlay.consume_first_run_finding()
    assert context is not None and "Welcome back" in context
    assert finding is not None and "embedding degraded" in finding
    # consumed exactly once
    assert overlay.consume_welcome_context() is None
