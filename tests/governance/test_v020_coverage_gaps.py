"""v0.20 — governance tests for coverage gaps identified in ISSUE-HARNESS-GOVERNANCE-TEST-COVERAGE-GAPS.

Tests:
1. provider-aware prompt caching — should_use_prompt_caching() must be False for non-Anthropic
2. RubricMiddleware opt-in contract — agents with rubric_middleware: true must have it in SKILL.md metadata
3. Orchestrator tool count ceiling — AGENT.md-declared orchestrators must not exceed a max tool count
4. SummarizationMiddleware build path — build_summarization_middleware() with a real BaseChatModel returns non-None
5. SKILL.md new-standard compliance — metadata block, version, enable_todo_list+write_todos, name-form scripts
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


# ---------------------------------------------------------------------------
# 5. SKILL.md new-standard compliance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_skill_md_has_metadata_block(label: str, path: Path):
    """Every SKILL.md must have a metadata: block.

    The metadata block is the authoritative carrier of harness opt-in flags
    (rubric_middleware, enable_todo_list), version, category, and type.
    An agent without a metadata block cannot opt into any harness capability
    and cannot be versioned or classified correctly.
    """
    fm = _parse_skill_md(path)
    assert fm.get("metadata") is not None, (
        f"{label}: missing metadata: block.\n"
        f"Add at minimum: metadata:\n  type: agent\n  version: 1.0.0"
    )


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_skill_md_metadata_has_version(label: str, path: Path):
    """Every SKILL.md metadata block must declare a version.

    Version enables change tracking, governance diffs, and compatibility
    checks. Without it, upgrades are invisible.
    """
    fm = _parse_skill_md(path)
    meta = fm.get("metadata") or {}
    assert meta.get("version"), (
        f"{label}: metadata block exists but has no version field.\n"
        f"Add:  version: 1.0.0  (or current version)"
    )


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_enable_todo_list_requires_write_todos_in_tools(label: str, path: Path):
    """enable_todo_list: true requires write_todos in the tools list.

    TodoListMiddleware activates when enable_todo_list is set, but the LLM
    can only call write_todos if it appears in tools:. Without it the harness
    injects the middleware but the agent has no call path to use it —
    the middleware is silently dead weight.
    """
    fm = _parse_skill_md(path)
    meta = fm.get("metadata") or {}
    if not meta.get("enable_todo_list"):
        return
    tools = fm.get("tools") or []
    assert "write_todos" in tools, (
        f"{label}: enable_todo_list=true but write_todos not in tools.\n"
        f"Add write_todos to the tools: list so the LLM can call it."
    )


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_script_entries_are_name_form(label: str, path: Path):
    """All scripts: entries must be name-form dicts, not bare path strings.

    Path-form entries (a bare string like './scripts/foo.py') cannot carry a
    description field, so SkillsMiddleware cannot inject the script's purpose
    into the agent system prompt. The LLM will not know the script exists.

    Canonical form:
        scripts:
          - name: foo
            file: foo.py
            description: "What this script does"
    """
    fm = _parse_skill_md(path)
    scripts = fm.get("scripts") or []
    for entry in scripts:
        assert isinstance(entry, dict), (
            f"{label}: script entry {entry!r} is a bare string (path-form).\n"
            f"Convert to name-form: {{name: ..., file: ..., description: ...}}"
        )


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_script_entries_have_required_fields(label: str, path: Path):
    """Each name-form script entry must have name, file, and description.

    Missing fields degrade SkillsMiddleware injection:
    - name: used by execute_skill_script as the callable identifier
    - file: the Python file to run
    - description: injected into the agent system prompt so the LLM knows
      what the script does and when to call it
    """
    fm = _parse_skill_md(path)
    scripts = fm.get("scripts") or []
    for entry in scripts:
        if not isinstance(entry, dict):
            continue  # caught by test_script_entries_are_name_form
        missing = [k for k in ("name", "file", "description") if not entry.get(k)]
        assert not missing, (
            f"{label}: script {entry.get('name', '?')!r} is missing fields: {missing}.\n"
            f"Every script entry needs name, file, and description."
        )
