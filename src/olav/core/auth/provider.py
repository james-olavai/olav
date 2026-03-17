"""AuthProvider Protocol and factory function.

Usage::

    from olav.core.auth.provider import get_auth_provider
    provider = get_auth_provider("none")   # Tier 0 — OS identity
    identity = provider.authenticate()
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from olav.core.auth.identity import UserIdentity


@runtime_checkable
class AuthProvider(Protocol):
    """Minimal interface that all auth providers must implement."""

    def authenticate(self, token: str | None = None) -> UserIdentity:
        """Resolve credentials → UserIdentity. Never raises; falls back gracefully."""
        ...


def get_auth_provider(mode: str | None = None) -> AuthProvider:
    """Return the AuthProvider for *mode* (reads from api.json if omitted).

    If *mode* is None, reads ``auth.mode`` from ConfigLoader (api.json).
    Security: Unknown modes fall back to OSIdentityProvider rather than
    raising, so a misconfigured api.json never locks the system out.
    """
    if mode is None:
        try:
            from olav.core.config import ConfigLoader
            mode = ConfigLoader().auth.mode
        except Exception:
            mode = "none"
    match mode:
        case "none":
            from olav.core.auth.os_identity import OSIdentityProvider
            return OSIdentityProvider()
        case "token":
            from olav.core.auth.token import TokenAuthProvider
            return TokenAuthProvider()
        case "server":
            from olav.core.auth.server_token import ServerTokenProvider
            return ServerTokenProvider()
        case _:
            from olav.core.auth.os_identity import OSIdentityProvider
            return OSIdentityProvider()
