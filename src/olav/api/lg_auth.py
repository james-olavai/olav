"""LANGGRAPH_AUTH adapter — bridges OLAV auth into native langgraph_api.

Configure via env var (set by olav.api.app before importing langgraph_api.server):

    LANGGRAPH_AUTH = '{"path": "olav.api.lg_auth:auth", "disable_studio_auth": true}'

The ``authenticate`` coroutine is registered with the ``Auth`` instance and
called by langgraph_api's ``CustomAuthBackend`` on every request.  It accepts
the ``authorization`` header value and the raw ``request`` object (both are
in langgraph_api's SUPPORTED_PARAMETERS list).

Auth flow:
  1. Bearer token  → ``Authorization: Bearer <token>``
  2. Session cookie → ``Cookie: olav_session=<token>``  (SPA browser navigation)
  3. Neither present and mode != "none"  → 401
  4. mode == "none"  → "anonymous" (no validation)
"""

from __future__ import annotations

from langgraph_sdk import Auth
from starlette.requests import Request

from olav.core.auth import get_auth_provider

auth = Auth()


def _get_auth_mode() -> str:
    """Read auth mode from OLAV config.  Isolated for easy mocking in tests."""
    try:
        from olav.core.config import ConfigLoader  # noqa: PLC0415

        return ConfigLoader().auth.mode or "none"
    except Exception:
        return "none"


@auth.authenticate
async def authenticate(
    authorization: str | None,
    request: Request,
) -> str:
    """Validate the incoming request and return the OLAV user identity string.

    Returns a string user_id which langgraph_api wraps in ``SimpleUser(username)``.
    Raises ``Auth.exceptions.HTTPException(401)`` for any authentication failure.

    Public paths bypass LANGGRAPH_AUTH entirely; custom_router handles its own
    auth at the route handler level for those paths.
    """
    path = request.url.path
    # These paths are served by custom_router which gates auth itself.
    # Static assets must be public so the login page JS loads before any auth.
    if path in ("/", "/login") or path.startswith("/_next/") or path.startswith("/login/"):
        return "anonymous"

    mode = _get_auth_mode()

    if mode == "none":
        return "anonymous"

    # Prefer Bearer token; fall back to session cookie for SPA navigation.
    token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    else:
        token = request.cookies.get("olav_session")

    if not token:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")

    try:
        provider = get_auth_provider(mode)
        identity = provider.authenticate(token=token, source_channel="api_bearer")
        # Reject OS-identity fallback: that only happens when the token is invalid
        # or the DB doesn't exist.  A token auth mode must produce source="token".
        if identity.source not in ("token", "server_token"):
            raise Auth.exceptions.HTTPException(status_code=401, detail="Invalid token")
        return identity.username
    except Auth.exceptions.HTTPException:
        raise
    except Exception as exc:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail=f"Authentication failed: {exc}"
        ) from exc
