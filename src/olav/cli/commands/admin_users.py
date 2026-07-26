"""Admin user management command.

Provides ``olav admin-users`` sub-commands for managing users in
``.olav/databases/users.duckdb``:

    add-user <username> [--role user|admin|readonly]
    list-users
    revoke-token <username>
    rotate-token <username>
"""

from __future__ import annotations

from olav.core.db_write import open_write_connection

import hashlib
import os
import secrets
from datetime import UTC
from pathlib import Path

from olav.cli.commands.base import BaseCommand


def _current_os_user() -> str:
    """Return the invoking OS username (used to decide if the generated
    token should be auto-stored in the local keyring)."""
    return (os.environ.get("USER") or os.environ.get("USERNAME") or "").strip()


def _maybe_save_local(
    token: str,
    username: str,
    users_db: Path,
) -> str:
    """Save *token* to the local keyring when *username* matches the
    invoking OS user, otherwise return a hint for out-of-band delivery.

    The admin's keyring never holds other users' tokens — cross-user
    rotations print the token and expect the target user to import it
    on their own machine.

    Args:
        token: Freshly-generated bearer token.
        username: OLAV username the token authenticates as.
        users_db: Absolute path to ``users.duckdb`` for per-env service
            discrimination.

    Returns:
        Human-readable storage status line to append to the CLI output.
    """
    if username != _current_os_user():
        return (
            "  Not saved locally — deliver this token to "
            f"'{username}' out-of-band; they should store it with "
            "`olav auth login` on their machine."
        )
    from olav.core.auth.keyring_store import save_token

    try:
        where = save_token(token, users_db_path=users_db)
    except Exception as exc:  # noqa: BLE001
        return f"  ⚠ Token not saved locally ({exc}). Store manually."
    if where == "keyring":
        return "  ✓ Stored in OS keyring for this workspace."
    from olav.core.auth.keyring_store import _per_env_token_path

    path = _per_env_token_path(users_db)
    return (
        f"  ⚠ OS keyring unavailable — token written to {path} (chmod 600)."
    )


class AdminUsersCommand(BaseCommand):
    """Manage OLAV platform users (add, list, revoke, rotate)."""

    def __init__(self, users_db: str | Path | None = None) -> None:
        super().__init__(name="admin-users", description="Manage platform users")
        if users_db is None:
            from olav.core.config import DATABASES_DIR

            users_db = Path(DATABASES_DIR) / "users.duckdb"
        self._users_db = Path(users_db)

    async def execute(self, args: str = "") -> str:
        from olav.cli.commands._argparse import parse_subcommand_args

        parts = parse_subcommand_args(args)
        if not parts:
            return self._usage()
        action = parts[0]
        if action == "add-user":
            return self._add_user(parts[1:])
        if action == "list-users":
            return self._list_users()
        if action == "revoke-token":
            return self._revoke_token(parts[1:])
        if action == "rotate-token":
            return self._rotate_token(parts[1:])
        return f"unknown admin-users action: {action}\n{self._usage()}"

    # ------------------------------------------------------------------
    # Sub-commands
    # ------------------------------------------------------------------

    def _add_user(self, parts: list[str]) -> str:
        if not parts:
            return "add-user requires <username>"
        username = parts[0]
        role = "user"
        if "--role" in parts:
            idx = parts.index("--role")
            if idx + 1 < len(parts):
                role = parts[idx + 1]
        valid_roles = {"admin", "user", "readonly"}
        if role not in valid_roles:
            return f"invalid role '{role}'. Choose from: {', '.join(sorted(valid_roles))}"

        # Linux user validation (skip with --no-verify or in container envs)
        if "--no-verify" not in parts and not _is_container_env():
            import pwd
            try:
                pwd.getpwnam(username)
            except KeyError:
                return (
                    f"error: Linux user '{username}' not found. "
                    f"Create with: sudo useradd {username}\n"
                    f"(Use --no-verify to skip this check)"
                )

        expires_at = None
        if "--expires" in parts:
            idx = parts.index("--expires")
            if idx + 1 < len(parts):
                from datetime import datetime

                try:
                    expires_at = datetime.strptime(parts[idx + 1], "%Y-%m-%d").replace(
                        tzinfo=UTC
                    )
                except ValueError:
                    return f"invalid --expires date '{parts[idx + 1]}'. Use YYYY-MM-DD format."

        token, token_hash, salt = _generate_token()

        self._ensure_db()
        import duckdb

        with open_write_connection(str(self._users_db)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO users (username, role, token_hash, token_salt, is_active, expires_at)
                VALUES (?, ?, ?, ?, true, ?)
                """,
                [username, role, token_hash, salt, expires_at],
            )

        storage_line = _maybe_save_local(token, username, self._users_db)
        return (
            f"user '{username}' created with role='{role}'.\n"
            f"Token (shown once — save immediately):\n  {token}\n"
            f"{storage_line}"
        )

    def _list_users(self) -> str:
        self._ensure_db()
        import duckdb

        with duckdb.connect(str(self._users_db), read_only=True) as conn:
            rows = conn.execute(
                "SELECT username, role, is_active, CAST(created_at AS VARCHAR) FROM users ORDER BY created_at"
            ).fetchall()

        if not rows:
            return "No users found."

        lines = [f"{'USERNAME':<20} {'ROLE':<12} {'ACTIVE':<8} CREATED_AT"]
        lines.append("-" * 60)
        for username, role, is_active, created_at in rows:
            active_str = "yes" if is_active else "no"
            created_str = str(created_at)[:19] if created_at else "-"
            lines.append(f"{username:<20} {role:<12} {active_str:<8} {created_str}")
        return "\n".join(lines)

    def _revoke_token(self, parts: list[str]) -> str:
        if not parts:
            return "revoke-token requires <username>"
        username = parts[0]

        self._ensure_db()
        import duckdb

        with open_write_connection(str(self._users_db)) as conn:
            affected = conn.execute(
                "SELECT COUNT(*) FROM users WHERE username = ?", [username]
            ).fetchone()[0]
            if not affected:
                return f"error: user '{username}' not found"
            conn.execute(
                "UPDATE users SET is_active = false, token_hash = NULL, token_salt = NULL WHERE username = ?",
                [username],
            )

        return f"token revoked for user '{username}'. They can no longer authenticate."

    def _rotate_token(self, parts: list[str]) -> str:
        if not parts:
            return "rotate-token requires <username>"
        username = parts[0]

        self._ensure_db()
        import duckdb

        with open_write_connection(str(self._users_db)) as conn:
            affected = conn.execute(
                "SELECT COUNT(*) FROM users WHERE username = ?", [username]
            ).fetchone()[0]
            if not affected:
                return f"error: user '{username}' not found"
            token, token_hash, salt = _generate_token()
            conn.execute(
                "UPDATE users SET token_hash = ?, token_salt = ?, is_active = true WHERE username = ?",
                [token_hash, salt, username],
            )

        storage_line = _maybe_save_local(token, username, self._users_db)
        return (
            f"token rotated for user '{username}'.\n"
            f"New token (shown once — save immediately):\n  {token}\n"
            f"{storage_line}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_db(self) -> None:
        """Create users table if it doesn't exist yet."""
        import duckdb

        from olav.core.auth.schema import apply_baseline

        self._users_db.parent.mkdir(parents=True, exist_ok=True)
        with open_write_connection(str(self._users_db)) as conn:
            apply_baseline(conn)

    @staticmethod
    def _usage() -> str:
        return (
            "usage: admin-users <action> [args]\n"
            "  add-user <username> [--role user|admin|readonly]\n"
            "  list-users\n"
            "  revoke-token <username>\n"
            "  rotate-token <username>"
        )


# ---------------------------------------------------------------------------
# Token generation (module-level helper, reusable by onboard command)
# ---------------------------------------------------------------------------


def _is_container_env() -> bool:
    """Return True if running inside a container (Docker/LXC/k8s)."""
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8")
        return any(k in cgroup for k in ("docker", "lxc", "containerd", "kubepods"))
    except OSError:
        return False


def _generate_token() -> tuple[str, str, str]:
    """Return ``(token, token_hash, salt)`` using sha256+salt.

    Token format: ``olav_<hex32>``
    Hash: ``sha256(salt_bytes + token_bytes)`` stored as hex string.
    """
    raw = secrets.token_hex(32)
    token = f"olav_{raw}"
    salt = secrets.token_hex(16)
    token_hash = hashlib.sha256((salt + token).encode()).hexdigest()
    return token, token_hash, salt
