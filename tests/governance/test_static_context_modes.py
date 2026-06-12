"""ARCH-17 P1 — static_context mode resolution + should_inject dispatch.

Covers:

* ``resolve_mode`` precedence (env → agent override → tier default → "always")
* ``should_inject`` dispatch for each mode
* ``_inject_static_context`` in ``agent.py`` respects the resolved mode —
  only ``"always"`` bakes refs into the init prompt
* ``get_static_context`` tool exists and resolves known stems
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RESOLVER_PATH = REPO / "src" / "olav" / "agents" / "static_context_resolver.py"
AGENT_PATH = REPO / "src" / "olav" / "agents" / "agent.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


resolver_mod = _load(RESOLVER_PATH, "static_context_resolver_for_test")
_VALID_MODES = resolver_mod._VALID_MODES
resolve_mode = resolver_mod.resolve_mode
should_inject = resolver_mod.should_inject


def _load_agent_module():
    pytest.importorskip("langchain_community")
    return _load(AGENT_PATH, "agent_for_static_context_modes_test")


def _stub_router(monkeypatch, router):
    mod = types.ModuleType("olav.core.router")
    mod.get_router = lambda: router
    monkeypatch.setitem(sys.modules, "olav.core.router", mod)


# ── resolve_mode -------------------------------------------------------------


def test_valid_modes_enumerate_three_values():
    assert _VALID_MODES == {"always", "on_intent", "lazy"}


def test_env_override_wins_over_everything(monkeypatch):
    monkeypatch.setenv("OLAV_STATIC_CONTEXT_MODE", "lazy")
    # Agent says always, env says lazy → env wins.
    assert resolve_mode({"static_context_mode": "always"}) == "lazy"


def test_env_override_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("OLAV_STATIC_CONTEXT_MODE", "nonsense")
    assert resolve_mode({"static_context_mode": "on_intent"}) == "on_intent"


def test_agent_explicit_wins_over_tier(monkeypatch):
    monkeypatch.delenv("OLAV_STATIC_CONTEXT_MODE", raising=False)

    class _Cfg:
        model_tier = "small"  # tier default = on_intent

    monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _Cfg())
    assert resolve_mode({"static_context_mode": "always"}) == "always"


def test_tier_default_used_when_no_explicit(monkeypatch):
    monkeypatch.delenv("OLAV_STATIC_CONTEXT_MODE", raising=False)

    class _Cfg:
        model_tier = "large"  # tier default = always

    monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _Cfg())
    assert resolve_mode({}) == "always"


def test_small_tier_defaults_to_on_intent(monkeypatch):
    monkeypatch.delenv("OLAV_STATIC_CONTEXT_MODE", raising=False)

    class _Cfg:
        model_tier = "small"

    monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _Cfg())
    assert resolve_mode({}) == "on_intent"


def test_config_failure_falls_back_to_always(monkeypatch):
    monkeypatch.delenv("OLAV_STATIC_CONTEXT_MODE", raising=False)

    def boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr("olav.core.config.get_llm_config", boom)
    assert resolve_mode({}) == "always"


def test_metadata_none_is_tolerated(monkeypatch):
    monkeypatch.delenv("OLAV_STATIC_CONTEXT_MODE", raising=False)

    class _Cfg:
        model_tier = "medium"

    monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _Cfg())
    assert resolve_mode(None) == "on_intent"  # medium default


# ── should_inject ------------------------------------------------------------


def test_always_injects_unconditionally():
    assert should_inject("always", None, None) is True
    assert should_inject("always", "anything", "core") is True


def test_lazy_never_injects():
    assert should_inject("lazy", "anything", "core") is False
    assert should_inject("lazy", None, None) is False


def test_unknown_mode_behaves_like_always():
    # Typo defence: never silently drop context.
    assert should_inject("mysterious", "q", "core") is True


def test_on_intent_without_query_fails_open():
    assert should_inject("on_intent", None, "core") is True


def test_on_intent_router_success_matches_agent(monkeypatch):
    class _Router:
        def route(self, query):
            return {"agent": "ops", "confidence": 0.9, "method": "keyword"}

    _stub_router(monkeypatch, _Router())
    # agent match
    assert should_inject("on_intent", "show bgp neighbors", "ops") is True
    # agent mismatch
    assert should_inject("on_intent", "show bgp neighbors", "audit") is False


def test_on_intent_router_low_confidence_skips(monkeypatch):
    class _Router:
        def route(self, query):
            return {"agent": "ops", "confidence": 0.1, "method": "keyword"}

    _stub_router(monkeypatch, _Router())
    assert should_inject("on_intent", "hi", "ops") is False


def test_on_intent_router_failure_fails_open(monkeypatch):
    class _BoomRouter:
        def route(self, query):
            raise RuntimeError("router unavailable")

    _stub_router(monkeypatch, _BoomRouter())
    # Fail-open semantics: rather than blind the agent, inject.
    assert should_inject("on_intent", "anything", "ops") is True


def test_on_intent_no_agent_name_uses_confidence_threshold(monkeypatch):
    class _Router:
        def route(self, query):
            return {"agent": "ops", "confidence": 0.5, "method": "keyword"}

    _stub_router(monkeypatch, _Router())
    assert should_inject("on_intent", "q", None) is True


# ── agent._inject_static_context wiring --------------------------------------


def test_inject_static_context_respects_lazy(tmp_path, monkeypatch):
    """When mode resolves to ``lazy``, init-time bake is skipped but a
    hint listing the available references is appended so the LLM knows
    to call ``get_static_context``."""
    agent_mod = _load_agent_module()

    ref_dir = tmp_path / "references"
    ref_dir.mkdir()
    (ref_dir / "BASELINE_SCHEMA.md").write_text("baseline text", encoding="utf-8")

    monkeypatch.setenv("OLAV_STATIC_CONTEXT_MODE", "lazy")
    prompt = agent_mod._inject_static_context(
        "base prompt",
        skill_dir=tmp_path,
        metadata={"static_context": [{"path": "references/BASELINE_SCHEMA.md"}]},
    )
    assert "baseline text" not in prompt  # bake skipped
    assert "BASELINE_SCHEMA" in prompt  # hint present
    assert "get_static_context" in prompt


def test_inject_static_context_always_bakes(tmp_path, monkeypatch):
    agent_mod = _load_agent_module()

    ref_dir = tmp_path / "references"
    ref_dir.mkdir()
    (ref_dir / "X.md").write_text("payload-X", encoding="utf-8")

    monkeypatch.setenv("OLAV_STATIC_CONTEXT_MODE", "always")
    prompt = agent_mod._inject_static_context(
        "base",
        skill_dir=tmp_path,
        metadata={"static_context": [{"path": "references/X.md"}]},
    )
    assert "payload-X" in prompt


# ── get_static_context tool --------------------------------------------------


def test_get_static_context_tool_exists():
    # v0.11.0: moved from core/admin/tools/ to admin/editor/tools/ (post-R-AGENT-HIERARCHY split)
    tool_path = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts" / "get_static_context.py"
    assert tool_path.exists(), "ARCH-17 P1 lazy-mode pull tool missing"

    # The tool should define get_static_context and export it via @tool.
    spec = importlib.util.spec_from_file_location("get_static_ctx_test", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "get_static_context")


def test_get_static_context_unknown_name_returns_available():
    tool_path = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts" / "get_static_context.py"
    spec = importlib.util.spec_from_file_location("get_static_ctx_test2", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    obj = mod.get_static_context
    result = obj.invoke({"name": "does_not_exist_xyz"}) if hasattr(obj, "invoke") else obj("does_not_exist_xyz")
    assert "error" in result
    assert isinstance(result.get("available"), list)


def test_get_static_context_rejects_empty_name():
    tool_path = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts" / "get_static_context.py"
    spec = importlib.util.spec_from_file_location("get_static_ctx_test3", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    obj = mod.get_static_context
    result = obj.invoke({"name": ""}) if hasattr(obj, "invoke") else obj("")
    assert "error" in result
