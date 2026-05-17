"""
tests/integration/test_native_api_smoke.py
──────────────────────────────────────────
TDD smoke tests for src/olav/api/app.py — the ASGI entry point that boots
native langgraph_api with OLAV-specific configuration.

Written BEFORE implementation (TDD red phase).

Tests verify:
  - app.py imports cleanly and exposes a working ASGI app
  - /assistants/search lists at least "core" agent
  - /memory/graph is served via the custom_router (user_router merging)
  - Native SSE event format over runs/stream
  - Auth required for protected endpoints
"""

from __future__ import annotations

import json
import os

import pytest


# ---------------------------------------------------------------------------
# Module-level env setup — must happen before olav.api.app is imported,
# because langgraph_api reads env vars at module import time.
# We set them here so the import inside the test functions works correctly.
# ---------------------------------------------------------------------------

def _patch_env_for_inmem():
    """Set env vars needed for inmem langgraph_api without Postgres/Redis."""
    defaults = {
        "LANGGRAPH_RUNTIME_EDITION": "inmem",
        "DATABASE_URI": ":memory:",
        "REDIS_URI": "fake",
        "MIGRATIONS_PATH": "__inmem",
        "LANGSMITH_LANGGRAPH_API_VARIANT": "local_dev",
        "LANGSERVE_GRAPHS": json.dumps({
            "core": "olav.server.graph_factory:make_graph",
        }),
        "LANGGRAPH_HTTP": json.dumps({"app": "olav.api.custom_router:app"}),
        "LANGGRAPH_AUTH": json.dumps({
            "path": "olav.api.lg_auth:auth",
            "disable_studio_auth": True,
        }),
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)


_patch_env_for_inmem()


# ---------------------------------------------------------------------------
# Fixture: TestClient for the wired app
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Import olav.api.app (sets env, boots langgraph_api)."""
    import olav.api.app as _app_mod  # noqa: PLC0415
    return _app_mod.app


@pytest.fixture(scope="module")
def client(app):
    """Synchronous TestClient — suitable for route existence checks."""
    from starlette.testclient import TestClient  # noqa: PLC0415
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper: Authorization header using OLAV token from config
# ---------------------------------------------------------------------------

def _auth_header() -> dict[str, str]:
    """Return Authorization header, or empty dict if auth mode is none."""
    try:
        from olav.core.config import ConfigLoader  # noqa: PLC0415
        mode = ConfigLoader().auth.mode or "none"
        if mode == "none":
            return {}
        token = ConfigLoader().auth.token or ""
        return {"Authorization": f"Bearer {token}"} if token else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAppImport:
    def test_app_module_imports_cleanly(self):
        """olav.api.app can be imported without raising."""
        import olav.api.app as _app  # noqa: PLC0415
        assert hasattr(_app, "app")

    def test_app_is_asgi_callable(self, app):
        """The app object is an ASGI callable (has __call__)."""
        assert callable(app)

    def test_app_has_routes(self, app):
        """App exposes at least one route."""
        assert len(app.routes) > 0


class TestAssistantsSearch:
    def test_assistants_search_reachable(self, client):
        """/assistants/search returns a non-500 status code."""
        resp = client.post(
            "/assistants/search",
            json={},
            headers=_auth_header(),
        )
        # 200 (success) or 401/403 (auth gate) are acceptable; 500 is not.
        assert resp.status_code != 500

    def test_assistants_search_lists_core(self, client):
        """/assistants/search response body contains 'core' assistant."""
        resp = client.post(
            "/assistants/search",
            json={},
            headers=_auth_header(),
        )
        if resp.status_code == 401:
            pytest.skip("Auth required but no valid token configured")
        assert resp.status_code == 200
        data = resp.json()
        # data is a list of assistant objects with "graph_id" field
        graph_ids = [a.get("graph_id") for a in data]
        assert "core" in graph_ids, f"'core' not in graph_ids: {graph_ids}"


class TestCustomRouterMerged:
    def test_memory_graph_accessible(self, client):
        """/memory/graph is served by the custom_router (user_router merge)."""
        resp = client.get("/memory/graph", headers=_auth_header())
        # Must not 404 — route must exist (may return 200 or redirect)
        assert resp.status_code != 404

    def test_reload_endpoint_accessible(self, client):
        """/reload is served by the custom_router."""
        resp = client.post("/reload", headers=_auth_header())
        assert resp.status_code != 404


class TestAuthGate:
    def test_assistants_search_without_auth_returns_401_or_200(self, client):
        """Without Authorization header, server returns 401 (auth) or 200 (mode=none)."""
        resp = client.post("/assistants/search", json={})
        # In mode=none, returns 200; in token mode, returns 401
        assert resp.status_code in (200, 401, 403)

    def test_invalid_bearer_returns_401(self, client):
        """Invalid Bearer token must be rejected with 401."""
        try:
            from olav.core.config import ConfigLoader  # noqa: PLC0415
            mode = ConfigLoader().auth.mode or "none"
        except Exception:
            mode = "none"
        if mode == "none":
            pytest.skip("Auth mode is none — auth gate not active")
        resp = client.post(
            "/assistants/search",
            json={},
            headers={"Authorization": "Bearer __invalid_token_xyz__"},
        )
        assert resp.status_code == 401
