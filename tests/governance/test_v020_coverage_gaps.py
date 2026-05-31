"""v0.20 — governance tests for coverage gaps identified in ISSUE-HARNESS-GOVERNANCE-TEST-COVERAGE-GAPS.

Tests:
1. provider-aware prompt caching — should_use_prompt_caching() must be False for non-Anthropic
2. RubricMiddleware opt-in contract — agents with rubric_middleware: true must have it in SKILL.md metadata
3. Orchestrator tool count ceiling — AGENT.md-declared orchestrators must not exceed a max tool count
4. SummarizationMiddleware build path — build_summarization_middleware() with a real BaseChatModel returns non-None
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_WORKSPACE = REPO / ".olav" / "workspace"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_skill_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.index("---", 3)
    return yaml.safe_load(text[3:end]) or {}


def _collect_skill_mds() -> list[tuple[str, Path]]:
    results = []
    for ws_root in (_WORKSPACE, REPO / "olav-netops" / ".olav" / "workspace"):
        if not ws_root.exists():
            continue
        for p in ws_root.rglob("SKILL.md"):
            label = str(p.relative_to(REPO))
            results.append((label, p))
    return results


# ---------------------------------------------------------------------------
# 1. Provider-aware prompt caching
# ---------------------------------------------------------------------------


def test_should_use_prompt_caching_false_for_non_anthropic(monkeypatch):
    """should_use_prompt_caching() must return False when provider != anthropic.

    ISSUE-HARNESS-PROMPT-CACHING-PROVIDER-BLIND: AnthropicPromptCachingMiddleware
    must not be injected for custom/openai/ollama providers.
    """
    from olav.agents._deepagents_bridge import HAS_PROMPT_CACHING
    if not HAS_PROMPT_CACHING:
        pytest.skip("HAS_PROMPT_CACHING is False — middleware not available")

    # Simulate a non-Anthropic provider config
    class _FakeLLMConfig:
        provider = "openai"

    import olav.agents._deepagents_bridge as bridge
    import olav.core.config as config_mod

    monkeypatch.setattr(config_mod, "get_llm_config", lambda: _FakeLLMConfig())

    from olav.agents._deepagents_bridge import should_use_prompt_caching
    assert not should_use_prompt_caching(), (
        "should_use_prompt_caching() returned True for non-Anthropic provider 'openai'.\n"
        "AnthropicPromptCachingMiddleware must NOT be injected outside Anthropic provider."
    )


def test_should_use_prompt_caching_true_for_anthropic(monkeypatch):
    """should_use_prompt_caching() returns True when provider == anthropic and class available."""
    from olav.agents._deepagents_bridge import HAS_PROMPT_CACHING
    if not HAS_PROMPT_CACHING:
        pytest.skip("HAS_PROMPT_CACHING is False — middleware not available")

    class _FakeLLMConfig:
        provider = "anthropic"

    import olav.core.config as config_mod
    monkeypatch.setattr(config_mod, "get_llm_config", lambda: _FakeLLMConfig())

    from olav.agents._deepagents_bridge import should_use_prompt_caching
    assert should_use_prompt_caching(), (
        "should_use_prompt_caching() returned False for Anthropic provider.\n"
        "AnthropicPromptCachingMiddleware should be injected when provider=anthropic."
    )


def test_should_use_prompt_caching_safe_on_config_failure(monkeypatch):
    """should_use_prompt_caching() returns False (not raises) when config read fails."""
    import olav.core.config as config_mod
    monkeypatch.setattr(config_mod, "get_llm_config", lambda: (_ for _ in ()).throw(RuntimeError("no config")))

    from olav.agents._deepagents_bridge import should_use_prompt_caching
    result = should_use_prompt_caching()
    assert result is False, "should_use_prompt_caching() must return False on config failure, not raise"


# ---------------------------------------------------------------------------
# 2. RubricMiddleware opt-in contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_rubric_middleware_opt_in_has_category(label: str, path: Path):
    """Agents with rubric_middleware: true must also declare a category in metadata.

    RubricMiddleware is only meaningful for agents with a defined purpose category
    (e.g. network-autonomous-audit). An opted-in agent without a category suggests
    a misconfiguration (rubric was added without understanding its intent).
    """
    fm = _parse_skill_md(path)
    meta = fm.get("metadata", {}) or {}
    if not meta.get("rubric_middleware"):
        return  # not opted in — skip
    category = meta.get("category", "")
    assert category, (
        f"{label}: has rubric_middleware=true but no metadata.category.\n"
        f"Add a category (e.g. 'network-autonomous-audit') to document what the rubric checks."
    )


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_rubric_middleware_opt_in_has_description(label: str, path: Path):
    """Agents with rubric_middleware: true must have a description field."""
    fm = _parse_skill_md(path)
    meta = fm.get("metadata", {}) or {}
    if not meta.get("rubric_middleware"):
        return
    assert fm.get("description"), (
        f"{label}: has rubric_middleware=true but no description.\n"
        f"Add a description so the grader can understand the agent's intent."
    )


# ---------------------------------------------------------------------------
# 3. SummarizationMiddleware build path with real model
# ---------------------------------------------------------------------------


def test_build_summarization_middleware_with_fake_chat_model():
    """build_summarization_middleware() returns non-None for a real BaseChatModel stub.

    The mock-based approach in test_compiled_subagent_middleware.py bypasses the
    actual build path. This test uses a minimal ChatModel stub to exercise the real chain.
    """
    from olav.agents._deepagents_bridge import HAS_SUMMARIZATION, build_summarization_middleware
    if not HAS_SUMMARIZATION:
        pytest.skip("HAS_SUMMARIZATION is False")

    # Minimal BaseChatModel stub — enough for SummarizationMiddleware init
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import ChatResult, ChatGeneration

    class _StubChatModel(BaseChatModel):
        def _generate(self, messages: list[BaseMessage], **kwargs) -> ChatResult:
            return ChatResult(generations=[ChatGeneration(message=messages[-1])])

        @property
        def _llm_type(self) -> str:
            return "stub"

    model = _StubChatModel()
    result = build_summarization_middleware(model, tier="small")
    assert result is not None, (
        "build_summarization_middleware() returned None for a real BaseChatModel.\n"
        "This means the middleware build path is broken for real models.\n"
        "Check _make_summarization_backend() and _create_summarization_middleware()."
    )


# ---------------------------------------------------------------------------
# 4. Orchestrator tool count ceiling
# ---------------------------------------------------------------------------


def test_orchestrator_tool_count_ceiling():
    """Core AGENT.md orchestrator must not exceed 12 direct tools.

    Orchestrator tool bloat adds token overhead on every invocation (~150-300 tokens/tool)
    and increases tool-selection error rate. This test catches accidental tool additions.
    """
    audit_agent_md = _WORKSPACE / "audit" / "AGENT.md"
    if not audit_agent_md.exists():
        pytest.skip("audit/AGENT.md not found")

    fm = _parse_skill_md(audit_agent_md)
    tools = fm.get("tools", []) or []
    assert len(tools) <= 12, (
        f"audit/AGENT.md has {len(tools)} tools (ceiling: 12).\n"
        f"Current tools: {tools}\n"
        f"Adding orchestrator tools increases per-invocation token cost. "
        f"Consider moving new capabilities to sub-agents."
    )
