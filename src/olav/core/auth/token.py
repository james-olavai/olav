"""TokenAuthProvider — Tier 1 auth using per-user ~/.olav/token files.

Token format: "olav_<hex32>"
Storage: sha256(salt + token) in .olav/databases/users.duckdb

Typical workflow:
    1. `olav onboard` generates the admin token and stores hash in users.duckdb.
    2. Admin creates user tokens via `olav admin add-user`.
    3. Users store their token in ~/.olav/token (chmod 600).
    4. TokenAuthProvider reads ~/.olav/token and verifies against users.duckdb.
    5. login_success / login_failed audit events are written per D8.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from olav.core.auth.identity import UserIdentity

logger = logging.getLogger(__name__)


class TokenAuthProvider:
    """Verifies a bearer token against the users.duckdb token_hash column.

    Skeleton implementation: authenticate() reads the token from the
    provided argument (or falls back to ~/.olav/token), then looks up
    the hash in users.duckdb. If users.duckdb is not yet initialised,
    falls back to OSIdentityProvider behaviour.
    """

    def __init__(self, users_db_path: str | Path | None = None) -> None:
        if users_db_path is None:
            from olav.core.config import DATABASES_DIR

            users_db_path = Path(DATABASES_DIR) / "users.duckdb"
        self._users_db = Path(users_db_path)

    def authenticate(
        self,
        token: str | None = None,
        *,
        source_channel: str = "cli",
        source_ip: str | None = None,
    ) -> UserIdentity:
        """Resolve *token* → UserIdentity.

        Writes ``login_success`` or ``login_failed`` to audit.duckdb per D8.
        Falls back gracefully to OS identity when the database does not
        exist or when *token* is not provided.
        """
        if token is None:
            token = self._read_token_file()

        if token and self._users_db.exists():
            identity = self._verify_token(token)
            if identity is not None:
                self._audit_login(
                    event="login_success",
                    username=identity.username,
                    source_channel=source_channel,
                    source_ip=source_ip,
                )
                return identity
            # Token present but invalid
            self._audit_login(
                event="login_failed",
                username="<token>",
                source_channel=source_channel,
                source_ip=source_ip,
                reason="invalid_token",
            )

        # Graceful fallback — still better than failing hard
        from olav.core.auth.os_identity import OSIdentityProvider

        return OSIdentityProvider().authenticate()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_token_file(self) -> str | None:
        token_file = Path.home() / ".olav" / "token"
        if token_file.exists():
            return token_file.read_text(encoding="utf-8").strip()
        return None

    def _verify_token(self, token: str) -> UserIdentity | None:
        try:
            import duckdb

            with duckdb.connect(str(self._users_db), read_only=True) as conn:
                rows = conn.execute(
                    "SELECT username, role, token_salt, token_hash, expires_at "
                    "FROM users WHERE is_active = true"
                ).fetchall()
        except Exception:  # DB not initialised or schema mismatch
            return None

        for username, role, salt, token_hash, expires_at in rows:
            if salt and self._hash(salt, token) == token_hash:
                identity = UserIdentity(
                    username=username, role=role, source="token", expires_at=expires_at
                )
                if identity.is_expired():
                    return None
                return identity
        return None

    def _hash(self, salt: str, token: str) -> str:
        return hashlib.sha256(f"{salt}{token}".encode()).hexdigest()

    def _audit_login(
        self,
        event: str,
        username: str,
        source_channel: str = "cli",
        source_ip: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Write login_success / login_failed to audit.duckdb (D8).

        Swallows all exceptions — auth must not fail because audit is down.
        """
        try:
            from olav.core.audit_recorder import AuditEventRecorder

            recorder = AuditEventRecorder()
            payload: dict = {
                "username": username,
                "source_channel": source_channel,
            }
            if source_ip:
                payload["source_ip"] = source_ip
            if reason:
                payload["reason"] = reason
            recorder.record(
                event_type=event,
                payload=payload,
            )
            recorder.close()
        except Exception as e:
            # Audit must not block auth, but silent failure masks record loss.
            logger.debug("token auth audit record failed: %s", e)
