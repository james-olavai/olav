"""ServerTokenProvider — JupyterLab-style server token auth (P3).

Server token flow:
    1. ``olav service start`` generates a server_token and writes its hash to
       ``.olav/run/server.token`` (chmod 600).
    2. The URL is printed as ``http://localhost:8080/?token=olav_srv_xxxx``.
    3. On first browser visit FastAPI reads the ``?token=`` query param,
       validates against the stored hash, and sets an ``olav_session`` cookie.
    4. Subsequent requests use the cookie; Bearer header also accepted.

Token format: ``olav_srv_<hex32>``
Storage:      sha256(token) in ``.olav/run/server.token`` (single line, hex digest)
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from olav.core.auth.identity import UserIdentity


def generate_server_token() -> str:
    """Generate a new server token string.  Does NOT persist it.

    Returns a token of the form ``olav_srv_<64 hex chars>`` (256 bits).
    """
    return "olav_srv_" + secrets.token_hex(32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _default_token_file() -> Path:
    try:
        from olav.core.config import ConfigLoader

        raw = ConfigLoader().auth.server_token_file
        return Path(raw).expanduser()
    except Exception:
        return Path(".olav/run/server.token")


class ServerTokenProvider:
    """Validates the one-time server token written by ``olav service start``.

    If the token file does not exist the provider falls back gracefully to
    OS identity — this mirrors JupyterLab's behaviour when ``--no-browser``
    or auth is disabled.
    """

    def __init__(self, token_file: str | Path | None = None) -> None:
        self._token_file = Path(token_file).expanduser() if token_file else _default_token_file()

    def authenticate(
        self,
        token: str | None = None,
        *,
        source_channel: str = "web",
        source_ip: str | None = None,
    ) -> UserIdentity:
        """Resolve *token* → UserIdentity.

        Returns a ``UserIdentity(username="server", role="user", source="token")``
        on success.  Falls back to OS identity when the token file is absent or
        when *token* is not provided.
        """
        if token and self._token_file.exists():
            stored_hash = self._token_file.read_text(encoding="utf-8").strip()
            if _hash_token(token) == stored_hash:
                return UserIdentity(username="server", role="user", source="token")

        # Graceful fallback
        from olav.core.auth.os_identity import OSIdentityProvider

        return OSIdentityProvider().authenticate()

    # ------------------------------------------------------------------
    # Class-level helpers used by ``olav service start``
    # ------------------------------------------------------------------

    @classmethod
    def create_and_persist(cls, token_file: str | Path | None = None) -> str:
        """Generate a server token, hash it, and write to *token_file*.

        Returns the plaintext token (to be printed once to the console).
        The token file is created with mode 0o600.
        """
        dest = Path(token_file).expanduser() if token_file else _default_token_file()
        dest.parent.mkdir(parents=True, exist_ok=True)

        token = generate_server_token()
        dest.write_text(_hash_token(token), encoding="utf-8")
        dest.chmod(0o600)
        return token
