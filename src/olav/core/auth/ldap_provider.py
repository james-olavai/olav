"""LDAPAuthProvider — Authenticate users against an LDAP server (e.g. lldap).

Token format accepted by ``authenticate(token=...)``:
    "username:password"   — plain credentials (used by CLI / API callers)

LDAP bind DN is constructed as: uid=<username>,ou=people,<base_dn>

Config (api.json auth.ldap):
    host     — LDAP server hostname (default: localhost)
    port     — LDAP port (default: 389 or 636 for TLS)
    base_dn  — Base DN, e.g. dc=example,dc=com
    tls      — Use LDAPS (default: False)
"""

from __future__ import annotations

import logging

from olav.core.auth.identity import UserIdentity

log = logging.getLogger(__name__)


class LDAPAuthProvider:
    """Authenticate users against an LDAP directory via bind."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 389,
        base_dn: str = "dc=example,dc=com",
        tls: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.base_dn = base_dn
        self.tls = tls

    # ------------------------------------------------------------------
    # AuthProvider protocol
    # ------------------------------------------------------------------

    def authenticate(
        self,
        token: str | None = None,
        *,
        source_channel: str = "cli",
        source_ip: str | None = None,
    ) -> UserIdentity:
        """Resolve ``username:password`` token → UserIdentity via LDAP bind.

        Falls back to OS identity gracefully on any error.
        """
        if not token or ":" not in token:
            log.debug("LDAPAuthProvider: no credentials provided, falling back to OS")
            return self._os_fallback()

        username, _, password = token.partition(":")

        try:
            bound = self._ldap_bind(username, password)
        except Exception as exc:
            log.warning("LDAPAuthProvider: bind error for %s: %s", username, exc)
            self._audit("login_failed", username, source_channel, source_ip, reason=str(exc))
            return self._os_fallback()

        if bound:
            identity = UserIdentity(username=username, role="user", source="token")
            self._audit("login_success", username, source_channel, source_ip)
            return identity

        self._audit("login_failed", username, source_channel, source_ip, reason="invalidCredentials")
        return self._os_fallback()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ldap_bind(self, username: str, password: str) -> bool:
        """Attempt LDAP simple bind. Returns True on success."""
        try:
            from ldap3 import Connection, Server
            from ldap3.core.exceptions import LDAPBindError
        except ImportError as exc:
            raise ImportError("ldap3 is required for LDAP auth: pip install ldap3") from exc

        user_dn = f"uid={username},ou=people,{self.base_dn}"
        server = Server(self.host, port=self.port)
        try:
            conn = Connection(server, user=user_dn, password=password, auto_bind=True)
            conn.unbind()
            return True
        except LDAPBindError:
            return False

    def _os_fallback(self) -> UserIdentity:
        from olav.core.auth.os_identity import OSIdentityProvider
        return OSIdentityProvider().authenticate()

    def _audit(
        self,
        event: str,
        username: str,
        source_channel: str,
        source_ip: str | None,
        reason: str | None = None,
    ) -> None:
        try:
            from olav.core.audit_recorder import AuditEventRecorder
            payload: dict = {"username": username, "source_channel": source_channel}
            if source_ip:
                payload["source_ip"] = source_ip
            if reason:
                payload["reason"] = reason
            recorder = AuditEventRecorder()
            recorder.record(event_type=event, payload=payload)
            recorder.close()
        except Exception as e:
            log.debug("ldap audit event record failed: %s", e)
