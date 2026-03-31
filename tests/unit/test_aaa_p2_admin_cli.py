"""AAA P2 — Admin CLI guard tests.

Covers:
1. AdminUsersCommand exists and is importable
2. add-user creates a user record in users.duckdb
3. list-users returns a table of users
4. revoke-token sets is_active=False
5. rotate-token regenerates token_hash
6. GAP-2: write_audit_manifest() produces a sha256 manifest file
7. GAP-5: ConfigLoader exposes audit_retention_days with default 90
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# 1. AdminUsersCommand importable
# ---------------------------------------------------------------------------


def test_admin_users_command_importable() -> None:
    from olav.cli.commands.admin_users import AdminUsersCommand
    cmd = AdminUsersCommand()
    assert cmd.name == "admin-users"


def test_admin_users_command_is_base_command() -> None:
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.cli.commands.base import BaseCommand
    assert issubclass(AdminUsersCommand, BaseCommand)


# ---------------------------------------------------------------------------
# 2. add-user — creates record in users.duckdb
# ---------------------------------------------------------------------------


def test_add_user_creates_record(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    result = asyncio.run(cmd.execute("add-user alice --role user"))
    assert "alice" in result

    with duckdb.connect(str(db), read_only=True) as conn:
        rows = conn.execute("SELECT username, role, is_active FROM users WHERE username = 'alice'").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "user"
    assert rows[0][2] is True  # is_active


def test_add_user_defaults_role_to_user(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    asyncio.run(cmd.execute("add-user bob"))

    with duckdb.connect(str(db), read_only=True) as conn:
        row = conn.execute("SELECT role FROM users WHERE username = 'bob'").fetchone()
    assert row is not None
    assert row[0] == "user"


def test_add_user_admin_role(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    asyncio.run(cmd.execute("add-user carol --role admin"))

    with duckdb.connect(str(db), read_only=True) as conn:
        row = conn.execute("SELECT role FROM users WHERE username = 'carol'").fetchone()
    assert row[0] == "admin"


# ---------------------------------------------------------------------------
# 3. list-users — tabular output
# ---------------------------------------------------------------------------


def test_list_users_returns_table(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)
        conn.execute("INSERT INTO users (username, role) VALUES ('dave', 'user')")

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    result = asyncio.run(cmd.execute("list-users"))
    assert "dave" in result


def test_list_users_empty_db(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    result = asyncio.run(cmd.execute("list-users"))
    assert "no users" in result.lower() or result.strip() != ""


# ---------------------------------------------------------------------------
# 4. revoke-token — sets is_active=False
# ---------------------------------------------------------------------------


def test_revoke_token_deactivates_user(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)
        conn.execute("INSERT INTO users (username, role, is_active) VALUES ('eve', 'user', true)")

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    result = asyncio.run(cmd.execute("revoke-token eve"))
    assert "eve" in result or "revoked" in result.lower()

    with duckdb.connect(str(db), read_only=True) as conn:
        row = conn.execute("SELECT is_active FROM users WHERE username = 'eve'").fetchone()
    assert row[0] is False


def test_revoke_token_unknown_user_returns_error(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    result = asyncio.run(cmd.execute("revoke-token ghost"))
    assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# 5. rotate-token — regenerates token_hash/salt, returns new token once
# ---------------------------------------------------------------------------


def test_rotate_token_updates_hash(tmp_path) -> None:
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.migrations.v0_12_users import apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)
        conn.execute(
            "INSERT INTO users (username, role, token_hash, token_salt) VALUES ('frank', 'admin', 'oldhash', 'oldsalt')"
        )

    cmd = AdminUsersCommand(users_db=db)
    import asyncio
    result = asyncio.run(cmd.execute("rotate-token frank"))
    # new token should appear in output
    assert "olav_" in result

    with duckdb.connect(str(db), read_only=True) as conn:
        row = conn.execute("SELECT token_hash, token_salt FROM users WHERE username = 'frank'").fetchone()
    assert row[0] != "oldhash"
    assert row[1] != "oldsalt"


# ---------------------------------------------------------------------------
# 6. GAP-2: audit manifest
# ---------------------------------------------------------------------------


def test_write_audit_manifest_creates_file(tmp_path) -> None:
    from olav.core.audit_recorder import write_audit_manifest

    db_path = tmp_path / "audit.duckdb"
    db_path.write_bytes(b"dummy audit content")
    manifest_path = tmp_path / "audit.duckdb.manifest"

    write_audit_manifest(db_path, manifest_path)

    assert manifest_path.exists()
    content = manifest_path.read_text(encoding="utf-8")
    # manifest must contain a date and sha256 hex digest
    import re
    assert re.search(r"[0-9a-f]{64}", content), "manifest must contain a sha256 hex digest"


def test_write_audit_manifest_appends(tmp_path) -> None:
    from olav.core.audit_recorder import write_audit_manifest

    db_path = tmp_path / "audit.duckdb"
    db_path.write_bytes(b"dummy audit content")
    manifest_path = tmp_path / "audit.duckdb.manifest"

    write_audit_manifest(db_path, manifest_path)
    write_audit_manifest(db_path, manifest_path)

    lines = [l for l in manifest_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2, "each call should append a new line"


# ---------------------------------------------------------------------------
# 7. GAP-5: retention policy in config
# ---------------------------------------------------------------------------


def test_config_loader_has_audit_retention_days() -> None:
    from olav.core.config import PathsConfig

    class _MockLoader:
        def _env_override(self, section, key, default):
            return default

    paths = PathsConfig(data={}, loader=_MockLoader())
    # default should be 90 days
    assert paths.audit_retention_days == 90


def test_config_loader_audit_retention_days_from_data() -> None:
    from olav.core.config import PathsConfig

    class _MockLoader:
        def _env_override(self, section, key, default):
            return default

    paths = PathsConfig(data={"audit": {"retention_days": 180}}, loader=_MockLoader())
    assert paths.audit_retention_days == 180
