"""TD-2/3/5 — Audit tamper protection, admin token expiry, audit retention.

TD-2: verify_audit_integrity() + close() auto-manifest
TD-3: --expires flag on add-user + _verify_token() expiry check
TD-5: audit_retention() deletes old records
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# TD-2: Audit tamper protection
# ---------------------------------------------------------------------------


def test_close_writes_manifest(tmp_path):
    """close() must call write_audit_manifest() automatically."""
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    recorder.record(event_type="test_event", run_id=str(uuid.uuid4()))
    recorder.close()

    manifest = db.with_suffix(db.suffix + ".manifest")
    assert manifest.exists(), ".manifest file must be created on close()"
    content = manifest.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, "manifest must not be empty"


def test_verify_integrity_passes_on_valid_db(tmp_path):
    """A freshly created+closed DB passes integrity check."""
    from olav.core.audit_recorder import AuditEventRecorder, verify_audit_integrity

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    recorder.record(event_type="test_event", run_id=str(uuid.uuid4()))
    recorder.close()

    assert verify_audit_integrity(db) is True


def test_verify_integrity_warns_on_tampered_db(tmp_path):
    """If the DB is modified after manifest write, verify returns False."""
    from olav.core.audit_recorder import AuditEventRecorder, verify_audit_integrity

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    recorder.record(event_type="test_event", run_id=str(uuid.uuid4()))
    recorder.close()

    # Tamper with the DB after close (append junk bytes)
    with db.open("ab") as f:
        f.write(b"TAMPERED")

    assert verify_audit_integrity(db) is False


def test_verify_integrity_skips_when_no_manifest(tmp_path):
    """If no manifest file exists, verification silently passes (returns True)."""
    from olav.core.audit_recorder import verify_audit_integrity

    db = tmp_path / "audit.duckdb"
    db.write_bytes(b"some db content")

    # No manifest file exists
    assert verify_audit_integrity(db) is True


# ---------------------------------------------------------------------------
# TD-3: Admin token expiry
# ---------------------------------------------------------------------------


def test_add_user_with_expires_flag(tmp_path):
    """add-user testuser --expires 2026-12-31 stores expires_at in DB."""
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand

    db = tmp_path / "users.duckdb"
    cmd = AdminUsersCommand(users_db=db)
    result = asyncio.run(cmd.execute("add-user testuser --expires 2026-12-31"))
    assert "testuser" in result

    with duckdb.connect(str(db), read_only=True) as conn:
        row = conn.execute("SELECT expires_at FROM users WHERE username = 'testuser'").fetchone()

    assert row is not None
    assert row[0] is not None, "expires_at must be set"
    # The date should be 2026-12-31
    expires = row[0]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    assert expires.year == 2026
    assert expires.month == 12
    assert expires.day == 31


def test_add_user_without_expires_has_null(tmp_path):
    """Default add-user has expires_at = NULL."""
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand

    db = tmp_path / "users.duckdb"
    cmd = AdminUsersCommand(users_db=db)
    asyncio.run(cmd.execute("add-user noexpiry"))

    with duckdb.connect(str(db), read_only=True) as conn:
        row = conn.execute("SELECT expires_at FROM users WHERE username = 'noexpiry'").fetchone()

    assert row is not None
    assert row[0] is None, "expires_at must be NULL when --expires not given"


def test_verify_token_rejects_expired_user(tmp_path):
    """A user with expires_at in the past is NOT authenticated (returns None)."""
    import duckdb
    from olav.core.auth.token import TokenAuthProvider
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    # Create user with a known token
    token = "olav_testtoken123"
    salt = "abcdef0123456789"
    token_hash = hashlib.sha256((salt + token).encode()).hexdigest()
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)

    with duckdb.connect(str(db)) as conn:
        conn.execute(
            """
            INSERT INTO users (username, role, token_hash, token_salt, is_active, expires_at)
            VALUES (?, ?, ?, ?, true, ?)
            """,
            ["expired_user", "user", token_hash, salt, past],
        )

    provider = TokenAuthProvider(users_db_path=db)
    identity = provider._verify_token(token)
    assert identity is None, "Expired user must not be authenticated"


def test_verify_token_accepts_non_expired_user(tmp_path):
    """A user with future expires_at IS authenticated."""
    import duckdb
    from olav.core.auth.token import TokenAuthProvider
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    token = "olav_validtoken456"
    salt = "fedcba9876543210"
    token_hash = hashlib.sha256((salt + token).encode()).hexdigest()
    future = datetime(2099, 12, 31, tzinfo=timezone.utc)

    with duckdb.connect(str(db)) as conn:
        conn.execute(
            """
            INSERT INTO users (username, role, token_hash, token_salt, is_active, expires_at)
            VALUES (?, ?, ?, ?, true, ?)
            """,
            ["valid_user", "user", token_hash, salt, future],
        )

    provider = TokenAuthProvider(users_db_path=db)
    identity = provider._verify_token(token)
    assert identity is not None, "Non-expired user must be authenticated"
    assert identity.username == "valid_user"
    assert identity.expires_at is not None


# ---------------------------------------------------------------------------
# TD-5: Audit retention/archive policy
# ---------------------------------------------------------------------------


def test_audit_retention_deletes_old_records(tmp_path):
    """Records older than threshold are deleted."""
    import duckdb
    from olav.core.audit_recorder import AuditEventRecorder, audit_retention

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)

    # Insert old record (200 days ago) via public API or direct duckdb
    old_ts = datetime.now(timezone.utc) - timedelta(days=200)
    run_id = str(uuid.uuid4())
    with duckdb.connect(str(db)) as _c:
        _c.execute(
            "INSERT INTO audit_runs (run_id, start_time, status) VALUES (?, ?, ?)",
            [run_id, old_ts, "completed"],
        )
        _c.execute(
            "INSERT INTO audit_events (event_id, event_type, timestamp, run_id) VALUES (?, ?, ?, ?)",
            [str(uuid.uuid4()), "old_event", old_ts, run_id],
        )
    recorder.close()

    deleted = audit_retention(db, max_age_days=90)
    assert deleted >= 2, f"Expected at least 2 deleted rows, got {deleted}"

    # Verify records are gone
    with duckdb.connect(str(db), read_only=True) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM audit_runs").fetchone()[0]
    assert remaining == 0


def test_audit_retention_keeps_recent_records(tmp_path):
    """Records newer than threshold are kept."""
    from olav.core.audit_recorder import AuditEventRecorder, audit_retention

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    run_id = str(uuid.uuid4())
    recorder.record_run_start(run_id=run_id, agent_id="test")
    recorder.record(event_type="recent_event", run_id=run_id)
    recorder.close()

    deleted = audit_retention(db, max_age_days=90)
    assert deleted == 0, "Recent records should not be deleted"

    import duckdb

    with duckdb.connect(str(db), read_only=True) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM audit_runs").fetchone()[0]
    assert remaining == 1


def test_audit_retention_returns_count(tmp_path):
    """Returns the number of deleted records."""
    import duckdb
    from olav.core.audit_recorder import AuditEventRecorder, audit_retention

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    recorder.close()  # ensure schema created

    old_ts = datetime.now(timezone.utc) - timedelta(days=200)
    # Insert 3 old records directly
    with duckdb.connect(str(db)) as _c:
        for i in range(3):
            _c.execute(
                "INSERT INTO audit_events (event_id, event_type, timestamp) VALUES (?, ?, ?)",
                [str(uuid.uuid4()), f"old_{i}", old_ts],
            )

    deleted = audit_retention(db, max_age_days=90)
    assert deleted == 3, f"Expected 3 deleted rows, got {deleted}"
