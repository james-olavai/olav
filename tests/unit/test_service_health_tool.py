from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO / "src" / "olav" / "data" / "workspace" / "core" / "api-query" / "scripts" / "service_health.py"


class _Svc:
    def __init__(self, name: str, endpoint: str):
        self.name = name
        self.endpoint = endpoint


class _Registry:
    def __init__(self, services: list[_Svc]):
        self._services = {s.name: s for s in services}

    def get(self, name: str):
        if name not in self._services:
            raise KeyError(name)
        return self._services[name]

    def list(self):
        return list(self._services.values())


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _load_module(modname: str):
    spec = importlib.util.spec_from_file_location(modname, TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tool_mod():
    return _load_module("_test_service_health_tool")


def test_service_health_no_services_returns_no_services(tool_mod, monkeypatch):
    from olav.platform.services.registry import ServiceRegistry

    monkeypatch.setattr(ServiceRegistry, "get_instance", lambda: _Registry([]))

    out = tool_mod.service_health()
    assert out["status"] == "no_services"
    assert "No services registered" in out["message"]


def test_service_health_unknown_service_returns_available(tool_mod, monkeypatch):
    from olav.platform.services.registry import ServiceRegistry

    registry = _Registry([
        _Svc("netbox", "http://netbox.local"),
        _Svc("prom", "http://prom.local"),
    ])
    monkeypatch.setattr(ServiceRegistry, "get_instance", lambda: registry)

    out = tool_mod.service_health(service="missing")
    assert out["status"] == "error"
    assert "not registered" in out["reason"]
    assert out["available"] == ["netbox", "prom"]


def test_service_health_success_fallback_and_unreachable(tool_mod, monkeypatch):
    from olav.platform.services.registry import ServiceRegistry

    services = [
        _Svc("ok", "http://ok.local"),
        _Svc("fallback", "http://fallback.local"),
        _Svc("down", "http://down.local"),
    ]
    monkeypatch.setattr(ServiceRegistry, "get_instance", lambda: _Registry(services))

    def fake_get(url: str, timeout: int, follow_redirects: bool):
        assert timeout == 5
        assert follow_redirects is True
        if url == "http://ok.local/health":
            return _Response(200)
        if url == "http://fallback.local/health":
            raise RuntimeError("health endpoint missing")
        if url == "http://fallback.local":
            return _Response(200)
        if url == "http://down.local/health":
            raise OSError("connection timeout")
        if url == "http://down.local":
            raise OSError("still down")
        raise AssertionError(f"unexpected URL: {url}")

    class _Httpx:
        @staticmethod
        def get(url, timeout, follow_redirects):
            return fake_get(url, timeout, follow_redirects)

    monkeypatch.setitem(sys.modules, "httpx", _Httpx)

    out = tool_mod.service_health()
    assert out["total"] == 3
    assert out["healthy"] == 2

    by_name = {item["name"]: item for item in out["services"]}
    assert by_name["ok"]["status"] == "healthy"
    assert by_name["ok"]["http_status"] == 200

    assert by_name["fallback"]["status"] == "reachable"
    assert by_name["fallback"]["http_status"] == 200

    assert by_name["down"]["status"] == "unreachable"
    assert "connection timeout" in by_name["down"]["error"]
