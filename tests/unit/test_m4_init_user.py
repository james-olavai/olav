"""TDD: ISSUE-M4-INIT-AUTO-CREATE-USER.

olav init should:
1. Create an admin user with the $USER username in users.duckdb
2. Persist the token via the keyring_store layer (v0.20.0+):
   - preferred: OS keyring under a per-workspace service name
   - fallback: per-env file at <users_db>/.auth_token (chmod 600)
   - legacy:   ~/.olav/token (still READ for back-compat, never
               written by new installs)
3. Set api.json auth.mode = "token"
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from unittest.mock import patch


def _run_init(tmp_path: Path, fake_user: str = "testuser") -> str:
    """Run InitCommand in tmp_path with a fake $USER env var."""
    from olav.cli.commands.init import InitCommand

    # Override home to tmp_path so token writes go there
    fake_home = tmp_path / "home" / fake_user
    fake_home.mkdir(parents=True, exist_ok=True)

    with (
        patch.dict(os.environ, {"USER": fake_user}),
        patch("olav.cli.commands.init.Path.home", return_value=fake_home),
        patch("olav.cli.commands.init.pwd") as mock_pwd,
    ):
        # Simulate Linux user exists
        import pwd as real_pwd
        mock_pwd.getpwnam.return_value = real_pwd.struct_passwd(
            (fake_user, "x", 1000, 1000, "", str(fake_home), "/bin/bash")
        )
        result = asyncio.run(InitCommand().execute())

    return result, fake_home


def test_init_creates_admin_user_record(tmp_path, monkeypatch) -> None:
    """init should create a user record in users.duckdb."""
    import duckdb

    monkeypatch.chdir(tmp_path)
    result, _ = _run_init(tmp_path)

    db_path = tmp_path / ".olav" / "databases" / "users.duckdb"
    assert db_path.exists(), "users.duckdb should be created by init"

    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            "SELECT username, role FROM users WHERE username = 'testuser'"
        ).fetchall()
    assert len(rows) == 1, f"Expected 1 testuser row, found: {rows}"
    assert rows[0][1] == "admin", f"Init user should have role=admin, got: {rows[0][1]}"


def test_init_persists_token(tmp_path, monkeypatch) -> None:
    """init must persist the admin token via the keyring_store layer.

    v0.20.0+: the token no longer lands at ``~/.olav/token`` — it goes
    to the OS keyring when available, otherwise to the per-env
    ``<users_db_dir>/.auth_token`` file (chmod 600).  This test runs
    under a headless venv without a keyring daemon, so we expect the
    per-env file fallback to fire.
    """
    monkeypatch.chdir(tmp_path)
    # Force file fallback — keyring would otherwise succeed on dev
    # boxes with a gnome-keyring daemon and the per-env file would
    # be absent.
    monkeypatch.setenv("OLAV_DISABLE_KEYRING", "1")

    result, _ = _run_init(tmp_path)

    # v0.20.0+ writes to <users_db_dir>/.auth_token when keyring is off
    per_env_path = tmp_path / ".olav" / "databases" / ".auth_token"
    assert per_env_path.exists(), (
        f"Per-env token file should exist at {per_env_path}; init result:\n{result}"
    )

    token_content = per_env_path.read_text(encoding="utf-8").strip()
    assert token_content.startswith("olav_"), (
        f"Token should start with 'olav_', got: {token_content}"
    )

    file_mode = stat.S_IMODE(per_env_path.stat().st_mode)
    assert file_mode == 0o600, (
        f"Token file should be chmod 600, got: {oct(file_mode)}"
    )


def test_init_does_not_write_legacy_user_global_token(tmp_path, monkeypatch) -> None:
    """Regression guard: v0.20.0+ must not write the user-global
    ``~/.olav/token`` on fresh installs — that was the dev/demo env
    collision bug keyring_store was built to fix.  Reading the legacy
    path for back-compat is fine; writing it on a fresh install is
    forbidden.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OLAV_DISABLE_KEYRING", "1")

    _, fake_home = _run_init(tmp_path)

    legacy_path = fake_home / ".olav" / "token"
    assert not legacy_path.exists(), (
        f"init must not write the legacy user-global token at {legacy_path}"
    )


def test_init_sets_auth_mode_token(tmp_path, monkeypatch) -> None:
    """init should set api.json auth.mode = 'token'."""
    monkeypatch.chdir(tmp_path)
    _run_init(tmp_path)

    api_json_path = tmp_path / ".olav" / "config" / "api.json"
    assert api_json_path.exists()
    data = json.loads(api_json_path.read_text(encoding="utf-8"))
    assert data.get("auth", {}).get("mode") == "token", (
        f"api.json auth.mode should be 'token', got: {data.get('auth')}"
    )


def test_init_output_mentions_user_and_token(tmp_path, monkeypatch) -> None:
    """init output should mention the created user and token path."""
    monkeypatch.chdir(tmp_path)
    result, _ = _run_init(tmp_path)

    assert "testuser" in result or "admin" in result.lower(), (
        f"Init output should mention username, got: {result}"
    )
    assert "token" in result.lower(), (
        f"Init output should mention token, got: {result}"
    )


def test_init_skips_user_when_no_user_env(tmp_path, monkeypatch) -> None:
    """init should skip user creation gracefully when USER env is unset."""
    import asyncio
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    env_without_user = {k: v for k, v in os.environ.items() if k != "USER"}

    with patch.dict(os.environ, env_without_user, clear=True):
        result = asyncio.run(InitCommand().execute())

    assert "platform ready" in result, (
        f"init should still succeed without USER env, got: {result}"
    )


def test_init_idempotent_for_user(tmp_path, monkeypatch) -> None:
    """Running init twice should not fail (user already exists = OK)."""
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    fake_home = tmp_path / "home" / "testuser"
    fake_home.mkdir(parents=True, exist_ok=True)

    import pwd as real_pwd
    with (
        patch.dict(os.environ, {"USER": "testuser"}),
        patch("olav.cli.commands.init.Path.home", return_value=fake_home),
        patch("olav.cli.commands.init.pwd") as mock_pwd,
    ):
        mock_pwd.getpwnam.return_value = real_pwd.struct_passwd(
            ("testuser", "x", 1000, 1000, "", str(fake_home), "/bin/bash")
        )
        asyncio.run(InitCommand().execute())
        # Second run
        result2 = asyncio.run(InitCommand().execute())

    assert "platform ready" in result2, (
        f"Second init should succeed, got: {result2}"
    )
