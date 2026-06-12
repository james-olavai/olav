"""TDD: olav sessions CLI command (ISSUE-M4-SESSION-SYNC-ACROSS-INTERFACES).

`olav sessions` lists the current user's active sessions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch


def _seed_sessions(db_path: Path, rows: list[dict]) -> None:
    import duckdb
    from olav.core.audit_recorder import AuditEventRecorder

    AuditEventRecorder(db_path=str(db_path))  # creates tables
    with duckdb.connect(str(db_path)) as conn:
        for r in rows:
            conn.execute(
                """
                INSERT INTO sessions (thread_id, user_id, agent_id, title, interface)
                VALUES (?, ?, ?, ?, ?)
                """,
                [r["thread_id"], r["user_id"], r.get("agent_id", "core"),
                 r.get("title", ""), r.get("interface", "cli")],
            )


def _run_sessions(db_path: Path, args: str = "") -> str:
    """Run SessionsCommand with overridden db path."""
    import olav.cli.commands.sessions as _mod
    with patch.object(_mod, "_get_audit_db_path", return_value=db_path):
        from olav.cli.commands.sessions import SessionsCommand
        cmd = SessionsCommand()
        return asyncio.run(cmd.execute(args))


def test_sessions_command_importable() -> None:
    from olav.cli.commands.sessions import SessionsCommand
    cmd = SessionsCommand()
    assert cmd.name == "sessions"


def test_sessions_command_lists_sessions(tmp_path, monkeypatch) -> None:
    """sessions command should return session rows for current user."""
    monkeypatch.setenv("USER", "alice")

    db_path = tmp_path / ".olav" / "databases" / "audit.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _seed_sessions(
        db_path,
        [
            {"thread_id": "t-1", "user_id": "alice", "title": "BGP query", "interface": "cli"},
            {"thread_id": "t-2", "user_id": "alice", "title": "R2 status", "interface": "web"},
            {"thread_id": "t-3", "user_id": "bob",   "title": "Bob private", "interface": "cli"},
        ],
    )

    result = _run_sessions(db_path)

    assert "t-1" in result, f"Alice's thread t-1 should appear, got: {result}"
    assert "t-2" in result, f"Alice's thread t-2 should appear, got: {result}"
    assert "t-3" not in result, f"Bob's thread should not appear, got: {result}"


def test_sessions_command_empty_db(tmp_path, monkeypatch) -> None:
    """sessions command should return friendly message when no sessions."""
    from olav.core.audit_recorder import AuditEventRecorder

    monkeypatch.setenv("USER", "alice")

    db_path = tmp_path / ".olav" / "databases" / "audit.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    AuditEventRecorder(db_path=str(db_path))  # ensure tables exist

    result = _run_sessions(db_path)
    assert result.strip(), f"Empty sessions should return some message, got: {result!r}"
