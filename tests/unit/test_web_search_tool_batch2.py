from __future__ import annotations

from types import SimpleNamespace

import olav.data.workspace.core.scripts.web_search as ws


def _call_web_search(query):
    if hasattr(ws.web_search, "invoke"):
        return ws.web_search.invoke({"query": query})
    return ws.web_search(query)


def test_web_search_invalid_query_inputs():
    assert _call_web_search("") == "Error: query must be a non-empty string"
    assert _call_web_search(None) == "Error: query must be a non-empty string"
    assert _call_web_search("x") == "Error: query too short (minimum 2 characters)"
    assert _call_web_search("a" * 201) == "Error: query too long (maximum 200 characters)"


def test_web_search_engine_missing_dependency(monkeypatch):
    monkeypatch.setattr(ws, "_search_engine", None)
    monkeypatch.setattr(ws, "DuckDuckGoSearchRun", None)
    out = _call_web_search("bgp troubleshooting")
    assert "LangChain DuckDuckGo integration not available" in out


def test_web_search_empty_results(monkeypatch):
    class _StubEngine:
        def run(self, _query):
            return "   "

    monkeypatch.setattr(ws, "_search_engine", _StubEngine())
    out = _call_web_search("ospf neighbor init")
    assert "No web search results found" in out


def test_web_search_successful_results(monkeypatch):
    class _StubEngine:
        def run(self, _query):
            return "Result title - https://example.com"

    monkeypatch.setattr(ws, "_search_engine", _StubEngine())
    out = _call_web_search("cisco bgp active state")
    assert out == "Result title - https://example.com"


def test_web_search_runtime_and_unexpected_exceptions(monkeypatch):
    monkeypatch.setattr(ws, "_search_engine", None)

    class _CtorRuntimeError:
        def __init__(self):
            raise RuntimeError("init boom")

    monkeypatch.setattr(ws, "DuckDuckGoSearchRun", _CtorRuntimeError)
    out = _call_web_search("arista eos vxlan issue")
    assert out.startswith("Error: Failed to initialize web search")

    monkeypatch.setattr(
        ws,
        "_search_engine",
        SimpleNamespace(run=lambda _q: (_ for _ in ()).throw(ValueError("bad syntax"))),
    )
    out = _call_web_search("bad query")
    assert out == "Error: Invalid query - bad syntax"

    monkeypatch.setattr(
        ws,
        "_search_engine",
        SimpleNamespace(run=lambda _q: (_ for _ in ()).throw(Exception("network down"))),
    )
    out = _call_web_search("juniper ospf stuck")
    assert out.startswith("Web search failed: Exception: network down")
