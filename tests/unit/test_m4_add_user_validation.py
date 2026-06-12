"""TDD: ISSUE-M4-ADD-USER-LINUX-VALIDATION.

add-user should verify username exists as Linux user via pwd.getpwnam().
Skipped in container envs; bypassed with --no-verify flag.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


def test_add_user_rejects_nonexistent_linux_user(tmp_path) -> None:
    """add-user <definitely_not_a_user> should return an error message."""
    from olav.cli.commands.admin_users import AdminUsersCommand

    cmd = AdminUsersCommand(users_db=tmp_path / "users.duckdb")
    result = asyncio.run(cmd.execute("add-user _olav_nonexistent_user_xyz123"))
    assert "not found" in result.lower() or "error" in result.lower(), (
        f"Expected error for non-existent linux user, got: {result}"
    )


def test_add_user_no_verify_bypasses_linux_check(tmp_path) -> None:
    """--no-verify flag should skip Linux user check."""
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.auth.schema import apply_baseline as apply_migration

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    cmd = AdminUsersCommand(users_db=db)
    result = asyncio.run(cmd.execute("add-user _olav_nonexistent_user_xyz123 --no-verify"))
    # Should succeed: user created despite not being a real Linux user
    assert "created" in result.lower() or "token" in result.lower(), (
        f"--no-verify should bypass Linux check, got: {result}"
    )


def test_add_user_accepts_real_user(tmp_path) -> None:
    """Real Linux user (e.g. root) should be accepted."""
    import pwd
    import duckdb
    from olav.cli.commands.admin_users import AdminUsersCommand
    from olav.core.auth.schema import apply_baseline as apply_migration

    # Find the first real user
    try:
        real_user = pwd.getpwall()[0].pw_name  # first entry (usually root or first system user)
    except (IndexError, KeyError):
        import pytest
        pytest.skip("No users in /etc/passwd")

    db = tmp_path / "users.duckdb"
    with duckdb.connect(str(db)) as conn:
        apply_migration(conn)

    cmd = AdminUsersCommand(users_db=db)
    result = asyncio.run(cmd.execute(f"add-user {real_user}"))
    assert "error" not in result.lower() or "created" in result.lower(), (
        f"Real Linux user should be accepted, got: {result}"
    )
