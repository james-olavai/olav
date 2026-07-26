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

    Security:
      * A genuinely unknown / typo'd mode falls back to OSIdentityProvider
        rather than raising, so a misconfigured api.json never locks the
        system out.
      * But modes that config scaffolding *advertises* yet no provider
        implements (``oidc``, ``ad``) fail fast — silently downgrading an
        intended SSO login to local OS identity would be a security surprise,
        not a safe default.
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
        case "ldap":
            from olav.core.auth.ldap_provider import LDAPAuthProvider
            try:
                from olav.core.config import ConfigLoader
                cfg = ConfigLoader().auth.ldap
                return LDAPAuthProvider(
                    host=cfg.get("host", "localhost"),
                    port=int(cfg.get("port", 389)),
                    base_dn=cfg.get("base_dn", "dc=example,dc=com"),
                    tls=bool(cfg.get("tls", False)),
                )
            except Exception:
                return LDAPAuthProvider()
        case "oidc" | "ad":
            # Advertised in config scaffolding (config.oidc, the auth.mode
            # docstring, the identity source enum) but there is NO provider.
            # Fail fast instead of silently handing out OS identity under the
            # guise of SSO.
            raise NotImplementedError(
                f"auth.mode={mode!r} is advertised in config but has no provider "
                "implementation. Refusing to fall back to OS identity, which "
                "would grant local-user access under the guise of SSO. "
                "Supported modes: none, token, server, ldap."
            )
        case _:
            from olav.core.auth.os_identity import OSIdentityProvider
            return OSIdentityProvider()
