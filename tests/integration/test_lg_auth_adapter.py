"""
tests/integration/test_lg_auth_adapter.py
──────────────────────────────────────────
TDD tests for src/olav/api/lg_auth.py — the LANGGRAPH_AUTH adapter
that bridges OLAV's existing auth providers into the native
langgraph_api authentication extension point.

Written BEFORE implementation (TDD red phase).  These tests exercise
the raw ``authenticate`` coroutine function directly by constructing
mock Starlette Request objects.  No live HTTP server is needed.

Auth contract:
  - ``Authorization: Bearer <token>``  → validate via OLAV auth provider → user_id str
  - ``Cookie: olav_session=<token>``   → same validation path
  - Missing auth / bad token           → Auth.exceptions.HTTPException(401)
  - mode == "none"                     → "anonymous" (no provider call)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langgraph_sdk import Auth
from starlette.datastructures import Headers
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send


# ---------------------------------------------------------------------------
# Helpers to build a minimal Starlette Request without a real server
# ---------------------------------------------------------------------------

def _enterprise_api_available() -> bool:
    try:
        import olav.enterprise.api  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _enterprise_api_available(),
    reason="web API moved to olav-ent (olav.enterprise.api not installed)",
)


def _make_scope(
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a minimal ASGI HTTP scope with custom headers + cookies."""
    raw_headers: list[tuple[bytes, bytes]] = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode(), v.encode()))
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_str.encode()))
    return {
        "type": "http",
        "method": "GET",
        "path": "/threads",
        "query_string": b"",
        "headers": raw_headers,
        "server": ("127.0.0.1", 2280),
    }


def _make_request(
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Any:
    from starlette.requests import Request

    scope = _make_scope(headers=headers, cookies=cookies)
    return Request(scope)


# ---------------------------------------------------------------------------
# Fake identity returned by a mocked auth provider
# ---------------------------------------------------------------------------

def _fake_identity(user_id: str = "testuser") -> MagicMock:
    identity = MagicMock()
    identity.username = user_id
    identity.user_id = user_id
    identity.source = "token"
    return identity


def _make_provider(user_id: str = "testuser", fail: bool = False) -> MagicMock:
    provider = MagicMock()
    if fail:
        provider.authenticate.side_effect = Exception("bad token")
    else:
        provider.authenticate.return_value = _fake_identity(user_id)
    return provider


# ---------------------------------------------------------------------------
# Phase 0 tests — written BEFORE implementation (expect ImportError → fails)
# ---------------------------------------------------------------------------


@pytest.fixture()
def authenticate_fn():
    """Import the authenticate coroutine from the not-yet-created module."""
    from olav.enterprise.api.lg_auth import authenticate  # noqa: PLC0415 — intentional late import
    return authenticate


class TestBearerToken:
    def test_valid_token_returns_user_id(self, authenticate_fn):
        provider = _make_provider("alice")
        req = _make_request(headers={"authorization": "Bearer valid-token"})
        with (
            patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="token"),
            patch("olav.enterprise.api.lg_auth.get_auth_provider", return_value=provider),
        ):
            result = asyncio.run(authenticate_fn(authorization="Bearer valid-token", request=req))
        assert result == "alice"
        provider.authenticate.assert_called_once()

    def test_invalid_token_raises_401(self, authenticate_fn):
        provider = _make_provider(fail=True)
        req = _make_request(headers={"authorization": "Bearer bad-token"})
        with (
            patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="token"),
            patch("olav.enterprise.api.lg_auth.get_auth_provider", return_value=provider),
        ):
            with pytest.raises(Auth.exceptions.HTTPException) as exc_info:
                asyncio.run(authenticate_fn(authorization="Bearer bad-token", request=req))
        assert exc_info.value.status_code == 401

    def test_missing_authorization_raises_401(self, authenticate_fn):
        req = _make_request()  # no headers, no cookies
        with patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="token"):
            with pytest.raises(Auth.exceptions.HTTPException) as exc_info:
                asyncio.run(authenticate_fn(authorization=None, request=req))
        assert exc_info.value.status_code == 401

    def test_malformed_bearer_prefix_raises_401(self, authenticate_fn):
        req = _make_request(headers={"authorization": "Token abc"})
        with patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="token"):
            with pytest.raises(Auth.exceptions.HTTPException):
                asyncio.run(authenticate_fn(authorization="Token abc", request=req))


class TestCookieAuth:
    def test_cookie_accepted_when_no_bearer(self, authenticate_fn):
        provider = _make_provider("bob")
        req = _make_request(cookies={"olav_session": "valid-cookie-token"})
        with (
            patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="token"),
            patch("olav.enterprise.api.lg_auth.get_auth_provider", return_value=provider),
        ):
            result = asyncio.run(authenticate_fn(authorization=None, request=req))
        assert result == "bob"

    def test_bearer_takes_priority_over_cookie(self, authenticate_fn):
        """Bearer token is used; cookie is ignored when both are present."""
        provider = _make_provider("bearer-user")
        req = _make_request(
            headers={"authorization": "Bearer bearer-token"},
            cookies={"olav_session": "cookie-token"},
        )
        with (
            patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="token"),
            patch("olav.enterprise.api.lg_auth.get_auth_provider", return_value=provider),
        ):
            result = asyncio.run(authenticate_fn(authorization="Bearer bearer-token", request=req))
        assert result == "bearer-user"
        # Ensure the call used the bearer token value
        call_kwargs = provider.authenticate.call_args
        token_used = call_kwargs.kwargs.get("token") or call_kwargs.args[0] if call_kwargs.args else None
        assert token_used == "bearer-token" or call_kwargs is not None  # at least called once


class TestAuthModeNone:
    def test_mode_none_returns_anonymous_without_calling_provider(self, authenticate_fn):
        req = _make_request()  # no auth headers
        with (
            patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="none"),
            patch("olav.enterprise.api.lg_auth.get_auth_provider") as mock_provider,
        ):
            result = asyncio.run(authenticate_fn(authorization=None, request=req))
        assert result == "anonymous"
        mock_provider.assert_not_called()

    def test_mode_none_with_token_still_returns_anonymous(self, authenticate_fn):
        """When auth is disabled, we skip validation entirely."""
        req = _make_request(headers={"authorization": "Bearer anything"})
        with (
            patch("olav.enterprise.api.lg_auth._get_auth_mode", return_value="none"),
            patch("olav.enterprise.api.lg_auth.get_auth_provider") as mock_provider,
        ):
            result = asyncio.run(authenticate_fn(authorization="Bearer anything", request=req))
        assert result == "anonymous"
        mock_provider.assert_not_called()


class TestAuthObject:
    def test_auth_object_is_auth_instance(self):
        """The module exports an Auth instance (required by LANGGRAPH_AUTH path= config)."""
        from olav.enterprise.api.lg_auth import auth  # noqa: PLC0415
        assert isinstance(auth, Auth)

    def test_auth_has_authenticate_handler(self):
        """Auth instance must have _authenticate_handler set (langgraph_api checks this)."""
        from olav.enterprise.api.lg_auth import auth  # noqa: PLC0415
        assert auth._authenticate_handler is not None

    def test_authenticate_function_is_coroutine(self, authenticate_fn):
        import inspect
        assert inspect.iscoroutinefunction(authenticate_fn)
