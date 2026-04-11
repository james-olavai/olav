"""Sessions management command.

Lists conversation sessions for the current user across all interfaces.

Usage:
    olav sessions                  # list current user's active sessions
    olav sessions --all            # include inactive sessions
    olav sessions --user <name>    # admin: list sessions for a specific user
"""

from __future__ import annotations

import os
from pathlib import Path

from olav.cli.commands.base import BaseCommand


def _get_audit_db_path() -> Path:
    """Resolve the audit.duckdb path (patchable for tests)."""
    try:
        from olav.core.config import AUDIT_DB_PATH
        return Path(AUDIT_DB_PATH)
    except Exception:
        return Path(".olav/databases/audit.duckdb")


class SessionsCommand(BaseCommand):
    """List conversation sessions across CLI/TUI/Web interfaces."""

    def __init__(self) -> None:
        super().__init__(name="sessions", description="List conversation sessions")

    async def execute(self, args: str = "") -> str:
        import shlex

        parts = shlex.split(args.strip()) if args.strip() else []

        show_all = "--all" in parts
        target_user: str | None = None
        if "--user" in parts:
            idx = parts.index("--user")
            if idx + 1 < len(parts):
                target_user = parts[idx + 1]

        current_user = target_user or os.environ.get("USER", "")

        db_path = _get_audit_db_path()
        if not db_path.exists():
            return "No sessions found (audit.duckdb does not exist)."

        try:
            import duckdb

            with duckdb.connect(str(db_path), read_only=True) as conn:
                tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
                if "sessions" not in tables:
                    return "No sessions found."

                where = "WHERE user_id = ?"
                params = [current_user]
                if not show_all:
                    where += " AND is_active = true"

                rows = conn.execute(
                    f"""
                    SELECT thread_id, title, interface,
                           CAST(last_active AS VARCHAR), message_count
                    FROM sessions
                    {where}
                    ORDER BY last_active DESC
                    LIMIT 50
                    """,
                    params,
                ).fetchall()

        except Exception as exc:  # noqa: BLE001
            return f"error reading sessions: {exc}"

        if not rows:
            qualifier = "active " if not show_all else ""
            return f"No {qualifier}sessions found for user '{current_user}'."

        lines = [
            f"{'THREAD_ID':<36} {'TITLE':<30} {'IFACE':<6} {'LAST_ACTIVE':<20} MSGS"
        ]
        lines.append("-" * 100)
        for thread_id, title, interface, last_active, msg_count in rows:
            short_title = (title or "")[:28]
            short_iface = (interface or "-")[:6]
            short_last = str(last_active or "")[:19]
            lines.append(
                f"{thread_id:<36} {short_title:<30} {short_iface:<6} {short_last:<20} {msg_count or 0}"
            )

        return "\n".join(lines)
