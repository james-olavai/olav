"""AAA P1 — Auth skeleton guard tests.

Covers:
1. UserIdentity dataclass structure
2. OSIdentityProvider.authenticate() returns UserIdentity from os.environ
3. get_auth_provider() factory returns correct provider types
4. TokenAuthProvider exists and is importable
5. users.duckdb migration v0_12 creates correct schema
6. GAP-1: audit_recorder.record_message() redacts network credentials
"""

import os
import re
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# 1. UserIdentity
# ---------------------------------------------------------------------------

def test_user_identity_dataclass_fields() -> None:
    from olav.core.auth.identity import UserIdentity
    identity = UserIdentity(username="alice", role="user", source="os")
    assert identity.username == "alice"
    assert identity.role == "user"
    assert identity.source == "os"
    assert identity.expires_at is None


def test_user_identity_role_validation() -> None:
    from olav.core.auth.identity import UserIdentity
    for role in ("admin", "user", "readonly"):
        identity = UserIdentity(username="bob", role=role, source="local")
        assert identity.role == role


# ---------------------------------------------------------------------------
# 2. OSIdentityProvider
# ---------------------------------------------------------------------------

def test_os_identity_provider_returns_user_identity(monkeypatch) -> None:
    monkeypatch.setenv("USER", "testuser")
    from olav.core.auth.os_identity import OSIdentityProvider
    provider = OSIdentityProvider()
    identity = provider.authenticate()
    assert identity.username == "testuser"
    assert identity.role == "user"
    assert identity.source == "os"


def test_os_identity_provider_falls_back_to_anonymous(monkeypatch) -> None:
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    from olav.core.auth.os_identity import OSIdentityProvider
    provider = OSIdentityProvider()
    identity = provider.authenticate()
    assert identity.username == "anonymous"


# ---------------------------------------------------------------------------
# 3. Factory function
# ---------------------------------------------------------------------------

def test_get_auth_provider_none_returns_os_identity_provider() -> None:
    from olav.core.auth.provider import get_auth_provider
    from olav.core.auth.os_identity import OSIdentityProvider
    provider = get_auth_provider("none")
    assert isinstance(provider, OSIdentityProvider)


def test_get_auth_provider_token_returns_token_auth_provider() -> None:
    from olav.core.auth.provider import get_auth_provider
    from olav.core.auth.token import TokenAuthProvider
    provider = get_auth_provider("token")
    assert isinstance(provider, TokenAuthProvider)


def test_get_auth_provider_unknown_falls_back_to_os_identity() -> None:
    from olav.core.auth.provider import get_auth_provider
    from olav.core.auth.os_identity import OSIdentityProvider
    provider = get_auth_provider("nonexistent_mode")
    assert isinstance(provider, OSIdentityProvider)


# ---------------------------------------------------------------------------
# 4. TokenAuthProvider importable
# ---------------------------------------------------------------------------

def test_token_auth_provider_is_importable() -> None:
    from olav.core.auth.token import TokenAuthProvider  # noqa: F401
    assert TokenAuthProvider is not None


def test_token_auth_provider_has_authenticate_method() -> None:
    from olav.core.auth.token import TokenAuthProvider
    assert hasattr(TokenAuthProvider, "authenticate")


# ---------------------------------------------------------------------------
# 5. users.duckdb migration
# ---------------------------------------------------------------------------

def test_v0_12_migration_creates_users_table() -> None:
    import duckdb
    from olav.core.migrations.v0_12_users import apply_migration

    with tempfile.TemporaryDirectory() as tmp:
        conn = duckdb.connect(str(Path(tmp) / "users.duckdb"))
        apply_migration(conn)

        # Table should exist
        tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        assert "users" in tables

        # Required columns
        cols = {row[0] for row in conn.execute("DESCRIBE users").fetchall()}
        for required in ("username", "role", "token_hash", "token_salt",
                         "is_active", "source", "created_at"):
            assert required in cols, f"Missing column: {required}"

        conn.close()


def test_v0_12_migration_is_idempotent() -> None:
    import duckdb
    from olav.core.migrations.v0_12_users import apply_migration

    with tempfile.TemporaryDirectory() as tmp:
        conn = duckdb.connect(str(Path(tmp) / "users.duckdb"))
        apply_migration(conn)
        apply_migration(conn)  # second call must not raise
        conn.close()


# ---------------------------------------------------------------------------
# 6. GAP-1: audit recorder redaction
# ---------------------------------------------------------------------------

def test_audit_recorder_redacts_password_in_messages() -> None:
    import duckdb
    from olav.core.audit_recorder import AuditEventRecorder

    with tempfile.TemporaryDirectory() as tmp:
        recorder = AuditEventRecorder(db_path=str(Path(tmp) / "audit.duckdb"))
        recorder.record_message(role="assistant", content="neighbor 10.0.0.1 password Sekr3t!")
        row = duckdb.connect(str(recorder._db_path)).execute(
            "SELECT content FROM audit_messages LIMIT 1"
        ).fetchone()
        assert row is not None
        assert "Sekr3t!" not in row[0], f"Password leaked in audit: {row[0]}"
        assert "[REDACTED]" in row[0]
        recorder.close()


def test_audit_recorder_redacts_snmp_community() -> None:
    import duckdb
    from olav.core.audit_recorder import AuditEventRecorder

    with tempfile.TemporaryDirectory() as tmp:
        recorder = AuditEventRecorder(db_path=str(Path(tmp) / "audit.duckdb"))
        recorder.record_message(role="assistant", content="snmp-server community public123 RO")
        row = duckdb.connect(str(recorder._db_path)).execute(
            "SELECT content FROM audit_messages LIMIT 1"
        ).fetchone()
        assert row is not None
        assert "public123" not in row[0], f"Community leaked in audit: {row[0]}"
        recorder.close()


def test_audit_recorder_redacts_secret() -> None:
    import duckdb
    from olav.core.audit_recorder import AuditEventRecorder

    with tempfile.TemporaryDirectory() as tmp:
        recorder = AuditEventRecorder(db_path=str(Path(tmp) / "audit.duckdb"))
        recorder.record_message(role="assistant", content="enable secret 5 $1$abc$xyz")
        row = duckdb.connect(str(recorder._db_path)).execute(
            "SELECT content FROM audit_messages LIMIT 1"
        ).fetchone()
        assert row is not None
        assert "$1$abc$xyz" not in row[0]
        recorder.close()


# ---------------------------------------------------------------------------
# 7. auth __init__ exports
# ---------------------------------------------------------------------------

def test_auth_init_exports_core_symbols() -> None:
    from olav.core.auth import UserIdentity, get_auth_provider  # noqa: F401
    assert UserIdentity is not None
    assert get_auth_provider is not None
