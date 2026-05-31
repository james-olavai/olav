"""Round 42 — ARCH-19 SummarizationMiddleware tier threshold governance tests.

These tests pin invariants, not stale literals:
- each tier exposes ``summarization_trigger_pct``
- ordering remains sensible across tiers
- ``compute_summarization_trigger`` resolves from tier config and returns
  absolute token tuples

The bridge is loaded by file path (not ``olav.agents`` package import) to
avoid pulling optional runtime deps during governance test collection.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import inspect
import logging
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BRIDGE_PY = REPO / "src" / "olav" / "agents" / "_deepagents_bridge.py"
AGENT_PY = REPO / "src" / "olav" / "agents" / "agent.py"


def _load(py: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _install_stub_modules(monkeypatch) -> None:
    """Install minimal dependency stubs so bridge can load in lean test envs."""

    def _fake_version(pkg: str) -> str:
        if pkg == "deepagents":
            return "0.6.7"
        return importlib.metadata.version(pkg)

    monkeypatch.setattr(importlib.metadata, "version", _fake_version)

    deepagents = types.ModuleType("deepagents")
    deepagents.__path__ = []
    deepagents.create_deep_agent = lambda **kwargs: kwargs

    deepagents_backends = types.ModuleType("deepagents.backends")

    class _StateBackend:
        pass

    class _LocalShellBackend:
        pass

    deepagents_backends.StateBackend = _StateBackend
    deepagents_backends.LocalShellBackend = _LocalShellBackend

    deepagents_mw = types.ModuleType("deepagents.middleware")
    deepagents_mw.__path__ = []

    class _SummarizationMiddleware:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    deepagents_mw.SummarizationMiddleware = _SummarizationMiddleware

    deepagents_mw_sum = types.ModuleType("deepagents.middleware.summarization")

    class _SummarizationToolMiddleware:
        pass

    deepagents_mw_sum.SummarizationToolMiddleware = _SummarizationToolMiddleware
    deepagents_mw_sum.create_summarization_middleware = lambda model, backend: {
        "model": model,
        "backend": backend,
    }
    deepagents_mw_sum.create_summarization_tool_middleware = lambda *a, **k: object()

    deepagents_mw_async = types.ModuleType("deepagents.middleware.async_subagents")

    class _AsyncSubAgent:
        pass

    class _AsyncSubAgentMiddleware:
        pass

    deepagents_mw_async.AsyncSubAgent = _AsyncSubAgent
    deepagents_mw_async.AsyncSubAgentMiddleware = _AsyncSubAgentMiddleware

    deepagents_mw_sub = types.ModuleType("deepagents.middleware.subagents")

    class _CompiledSubAgent:
        pass

    class _SubAgent:
        pass

    class _TaskTool:
        def __init__(self):
            self.return_direct = False

    deepagents_mw_sub.CompiledSubAgent = _CompiledSubAgent
    deepagents_mw_sub.SubAgent = _SubAgent
    deepagents_mw_sub._build_task_tool = lambda *a, **k: _TaskTool()
    deepagents_mw_sub._EXCLUDED_STATE_KEYS = set()

    langchain_anthropic = types.ModuleType("langchain_anthropic")
    langchain_anthropic.__path__ = []
    langchain_anthropic_mw = types.ModuleType("langchain_anthropic.middleware")

    class _AnthropicPromptCachingMiddleware:
        pass

    langchain_anthropic_mw.AnthropicPromptCachingMiddleware = _AnthropicPromptCachingMiddleware

    # 0.6.x stubs
    deepagents_mw_rubric = types.ModuleType("deepagents.middleware.rubric")

    class _RubricMiddleware:
        pass

    deepagents_mw_rubric.RubricMiddleware = _RubricMiddleware

    deepagents_mw_skills = types.ModuleType("deepagents.middleware.skills")

    class _SkillsMiddleware:
        pass

    deepagents_mw_skills.SkillsMiddleware = _SkillsMiddleware

    deepagents_graph = types.ModuleType("deepagents.graph")

    class _DeepAgentState:
        pass

    deepagents_graph.DeepAgentState = _DeepAgentState

    deepagents_backends_ctx = types.ModuleType("deepagents.backends.context_hub")

    class _ContextHubBackend:
        pass

    deepagents_backends_ctx.ContextHubBackend = _ContextHubBackend
    deepagents_backends.FilesystemBackend = object  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "deepagents", deepagents)
    monkeypatch.setitem(sys.modules, "deepagents.backends", deepagents_backends)
    monkeypatch.setitem(sys.modules, "deepagents.backends.context_hub", deepagents_backends_ctx)
    monkeypatch.setitem(sys.modules, "deepagents.middleware", deepagents_mw)
    monkeypatch.setitem(sys.modules, "deepagents.middleware.summarization", deepagents_mw_sum)
    monkeypatch.setitem(sys.modules, "deepagents.middleware.async_subagents", deepagents_mw_async)
    monkeypatch.setitem(sys.modules, "deepagents.middleware.subagents", deepagents_mw_sub)
    monkeypatch.setitem(sys.modules, "deepagents.middleware.rubric", deepagents_mw_rubric)
    monkeypatch.setitem(sys.modules, "deepagents.middleware.skills", deepagents_mw_skills)
    monkeypatch.setitem(sys.modules, "deepagents.graph", deepagents_graph)
    monkeypatch.setitem(sys.modules, "langchain_anthropic", langchain_anthropic)
    monkeypatch.setitem(sys.modules, "langchain_anthropic.middleware", langchain_anthropic_mw)


def _load_bridge(monkeypatch, alias: str):
    _install_stub_modules(monkeypatch)
    return _load(BRIDGE_PY, alias)


# ── TIER_DEFAULTS key/invariant pins ──────────────────────────────────────────


def test_tier_defaults_has_summarization_trigger_pct():
    from olav.core.config import TIER_DEFAULTS

    for tier in ("small", "medium", "large"):
        assert "summarization_trigger_pct" in TIER_DEFAULTS[tier], (
            f"tier {tier} missing summarization_trigger_pct"
        )
        pct = TIER_DEFAULTS[tier]["summarization_trigger_pct"]
        assert isinstance(pct, (int, float)), (
            f"tier {tier} summarization_trigger_pct must be numeric"
        )
        assert 0.0 < float(pct) < 1.0, (
            f"tier {tier} summarization_trigger_pct must be in (0, 1); got {pct}"
        )


def test_summarization_pct_ordering_constraints():
    """Architecture guard: large tier should not summarize earlier than smaller tiers."""
    from olav.core.config import TIER_DEFAULTS

    small = float(TIER_DEFAULTS["small"]["summarization_trigger_pct"])
    medium = float(TIER_DEFAULTS["medium"]["summarization_trigger_pct"])
    large = float(TIER_DEFAULTS["large"]["summarization_trigger_pct"])

    assert small <= large, f"expected small <= large, got {small} > {large}"
    assert medium <= large, f"expected medium <= large, got {medium} > {large}"
    assert len({small, medium, large}) >= 2, "tiers should not collapse to one identical threshold"


# ── compute_summarization_trigger helper ──────────────────────────────────────


def test_compute_summarization_trigger_exported(monkeypatch):
    bridge = _load_bridge(monkeypatch, "_bridge_r42_export")
    assert callable(getattr(bridge, "compute_summarization_trigger", None))


def test_compute_summarization_trigger_uses_tier_defaults(monkeypatch):
    from olav.core.config import TIER_DEFAULTS

    bridge = _load_bridge(monkeypatch, "_bridge_r42_compute")

    for tier in ("small", "medium", "large"):
        budget = int(TIER_DEFAULTS[tier]["context_budget"])
        pct = float(TIER_DEFAULTS[tier]["summarization_trigger_pct"])
        monkeypatch.setenv("OLAV_LLM_CONTEXT_BUDGET", str(budget))
        expected = ("tokens", int(budget * pct))

        got = bridge.compute_summarization_trigger(tier)
        assert isinstance(got, tuple) and len(got) == 2, (
            f"{tier}: expected ('tokens', N) tuple, got {got!r}"
        )
        assert got[0] == "tokens", f"{tier}: trigger mode must be 'tokens', got {got!r}"
        assert got == expected, (
            f"{tier}: compute_summarization_trigger must resolve from tier config; "
            f"expected {expected}, got {got}"
        )


def test_compute_summarization_trigger_unknown_returns_none(monkeypatch):
    bridge = _load_bridge(monkeypatch, "_bridge_r42_unknown")
    assert bridge.compute_summarization_trigger("xlarge") is None
    assert bridge.compute_summarization_trigger(None) is None
    assert bridge.compute_summarization_trigger("") is None


# ── build_summarization_middleware signature/wiring ───────────────────────────


def test_build_summarization_middleware_accepts_tier(monkeypatch):
    bridge = _load_bridge(monkeypatch, "_bridge_r42_sig")
    sig = inspect.signature(bridge.build_summarization_middleware)
    assert "tier" in sig.parameters, (
        f"build_summarization_middleware no longer accepts tier=; got {list(sig.parameters)}"
    )


def test_build_summarization_middleware_uses_compute_trigger():
    src = BRIDGE_PY.read_text(encoding="utf-8")
    assert "compute_summarization_trigger(tier)" in src, (
        "build_summarization_middleware no longer calls compute_summarization_trigger; "
        "tier awareness regressed."
    )


def test_agent_passes_tier_to_build_summarization():
    src = AGENT_PY.read_text(encoding="utf-8")
    assert "build_summarization_middleware(self.llm, tier=" in src, (
        "agent.py no longer passes tier= to build_summarization_middleware; "
        "wiring regressed."
    )


# ── OLAV_DEBUG_SUMMARIZATION env var ──────────────────────────────────────────


def test_debug_env_var_name_pinned(monkeypatch):
    bridge = _load_bridge(monkeypatch, "_bridge_r42_envname")
    assert bridge._SUMMARIZATION_DEBUG_ENV == "OLAV_DEBUG_SUMMARIZATION"


def test_debug_env_helper_respects_truthy_set(monkeypatch):
    bridge = _load_bridge(monkeypatch, "_bridge_r42_truthy")
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("OLAV_DEBUG_SUMMARIZATION", truthy)
        assert bridge._summarization_debug_enabled() is True, f"{truthy!r} should be truthy"
    for falsy in ("", "0", "false", "no", "off", "foo"):
        monkeypatch.setenv("OLAV_DEBUG_SUMMARIZATION", falsy)
        assert bridge._summarization_debug_enabled() is False, f"{falsy!r} should be falsy"


def test_debug_env_unset_is_false(monkeypatch):
    bridge = _load_bridge(monkeypatch, "_bridge_r42_unset")
    monkeypatch.delenv("OLAV_DEBUG_SUMMARIZATION", raising=False)
    assert bridge._summarization_debug_enabled() is False


def test_build_summarization_logs_when_debug_enabled(monkeypatch, caplog):
    """With OLAV_DEBUG_SUMMARIZATION=1, bridge logs tier + resolved trigger."""
    from olav.core.config import TIER_DEFAULTS

    bridge = _load_bridge(monkeypatch, "_bridge_r42_log")
    if not bridge.HAS_SUMMARIZATION or bridge.SummarizationMiddleware is None:
        import pytest

        pytest.skip("SummarizationMiddleware unavailable in this env")

    monkeypatch.setenv(
        "OLAV_LLM_CONTEXT_BUDGET",
        str(int(TIER_DEFAULTS["small"]["context_budget"])),
    )
    monkeypatch.setenv("OLAV_DEBUG_SUMMARIZATION", "1")

    class _FakeBackend:
        pass

    monkeypatch.setattr(bridge, "_StateBackend", _FakeBackend)
    called = {}

    def _fake_mw(*, model, backend, trigger, keep):
        called["trigger"] = trigger
        called["keep"] = keep
        return object()

    monkeypatch.setattr(bridge, "SummarizationMiddleware", _fake_mw)

    caplog.set_level(logging.INFO, logger=bridge.__name__)
    out = bridge.build_summarization_middleware(object(), tier="small")

    expected_trigger = (
        "tokens",
        int(
            float(TIER_DEFAULTS["small"]["summarization_trigger_pct"])
            * int(TIER_DEFAULTS["small"]["context_budget"])
        ),
    )

    assert out is not None, "build_summarization_middleware returned None unexpectedly"
    assert called["trigger"] == expected_trigger

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "OLAV_DEBUG_SUMMARIZATION" in log_text
    assert "tier=small" in log_text
    assert str(expected_trigger[1]) in log_text
