"""Tests for the services / api-query api_request tool error paths.

ISSUE-API-REQUEST-PAGE-SIZE-DROPPED: services/api_request was passing
``page_size`` to service_call(), which doesn't accept that kwarg →
every call died with ``TypeError: service_call() got an unexpected
keyword argument 'page_size'``. The 27B agent saw the cryptic error
and gave up with ``[]`` as final response. Demo7 Ch7 step 2 surfaced.

Pin the surface so a future refactor can't re-break it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


REPO = Path(__file__).resolve().parents[2]
# Both services and core api_request now live in core/api-query/scripts/ (post-scripts化)
SERVICES_TOOL = REPO / "src" / "olav" / "data" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py"
CORE_TOOL = REPO / "src" / "olav" / "data" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py"


def _load(path: Path, modname: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def services_api():
    return _load(SERVICES_TOOL, "_test_services_api_request")


@pytest.fixture(scope="module")
def core_api():
    return _load(CORE_TOOL, "_test_core_api_request")


def test_services_api_request_does_not_pass_page_size_to_service_call(services_api):
    """Regression: services/api_request previously forwarded
    ``page_size`` to service_call. service_call doesn't accept it →
    TypeError → agent sees cryptic error → produces ``[]``."""
    captured: dict = {}

    def fake_service_call(service, **kwargs):
        captured.update(kwargs)
        return {"ok": True}

    with patch("olav.platform.services.client.service_call", new=fake_service_call):
        result = services_api.api_request(
            service="test_svc",
            method="GET",
            path="/health",
            page_size=25,  # passed but must NOT propagate to service_call
        )
    assert "page_size" not in captured, (
        f"page_size leaked into service_call kwargs: {captured}. "
        f"service_call signature does not accept it."
    )
    assert result == {"ok": True}


def test_services_api_request_returns_structured_error_on_exception(services_api):
    """When service_call raises, api_request returns
    ``{status: error, reason, service, path}`` — never lets the
    exception leak. Required for small-model NL summarization."""
    def boom(*a, **kw):
        raise ConnectionError("Connection refused: 10.0.0.9:8080")

    with patch("olav.platform.services.client.service_call", new=boom):
        result = services_api.api_request(
            service="some_service",
            method="GET",
            path="/ping",
        )
    assert isinstance(result, dict), "must return dict, not raise"
    assert result.get("status") == "error"
    assert "Connection refused" in result.get("reason", "")
    assert result.get("service") == "some_service"
    assert result.get("path") == "/ping"


def test_core_api_request_does_not_regress_with_page_size(core_api):
    """The core/api-query sister tool already correct — pin it."""
    captured: dict = {}

    def fake_service_call(service, **kwargs):
        captured.update(kwargs)
        return {"ok": True}

    with patch("olav.platform.services.client.service_call", new=fake_service_call):
        core_api.api_request(
            service="test_svc",
            method="GET",
            path="/health",
            page_size=99,
        )
    assert "page_size" not in captured


def test_services_api_request_unknown_service_returns_helpful_error(services_api):
    """KeyError path: returns hint with available service names so the
    agent can correct or suggest the user register the service."""
    def raises(*a, **kw):
        raise KeyError("unknown_svc")

    with patch("olav.platform.services.client.service_call", new=raises):
        result = services_api.api_request(
            service="unknown_svc",
            method="GET",
            path="/x",
        )
    assert result["status"] == "error"
    assert "not registered" in result["reason"]
    assert "Available" in result["hint"]
