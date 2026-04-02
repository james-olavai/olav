"""
TDD: CC-01 — CompiledSubAgent 补齐 SummarizationMiddleware + AnthropicPromptCachingMiddleware

验收标准:
  1. SummarizationMiddleware 存在于预编译 subagent 中间件列表
  2. AnthropicPromptCachingMiddleware 在可用时存在（版本门控）
  3. FilesystemMiddleware 不存在（约束）
  4. TodoListMiddleware 仍存在（基础）
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _middleware_types(runnable) -> list[type]:
    """Extract middleware types from a create_agent runnable (call args inspection)."""
    return []  # replaced by inspection of mock calls


def _has_middleware_type(middleware_list, cls) -> bool:
    """Check if any item in middleware_list is an instance of cls (or has __class__ == cls)."""
    for m in middleware_list:
        if isinstance(m, cls) or getattr(m, "__class__", None) is cls:
            return True
    return False


def _make_minimal_agent_build(tmp_path, monkeypatch):
    """
    Create a minimal workspace structure and trigger _build_subagents().
    Returns (agent_instance, captured_middleware_list).
    """
    # Build a fake workspace: one subagent with one tool
    sa_dir = tmp_path / "workspace" / "ops"
    (sa_dir / "tools").mkdir(parents=True)
    skill_md = sa_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: ops\ndescription: test ops agent\n---\nOps agent body.\n"
    )
    # Write a minimal tool file so discover_tools() finds something
    tool_file = sa_dir / "tools" / "dummy_tool.py"
    tool_file.write_text(
        "from langchain_core.tools import tool\n\n@tool\ndef dummy() -> str:\n    '''Dummy tool.'''\n    return 'ok'\n"
    )
    prompt_dir = sa_dir / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "system.md").write_text("You are the ops agent.")

    olav_config = {
        "subagents": [f"ops/SKILL.md"],
    }

    captured: list[list] = []

    # Patch create_agent to capture middleware argument
    # Patch build_summarization_middleware to return a real SummarizationMiddleware-typed mock
    # (factory requires a real BaseChatModel; this tests the wiring, not the factory itself)
    from deepagents.middleware import SummarizationMiddleware

    fake_summ_instance = MagicMock(spec=SummarizationMiddleware)
    fake_summ_instance.__class__ = SummarizationMiddleware

    def fake_create_agent(llm, *, system_prompt, tools, middleware, name, **kwargs):
        captured.append(list(middleware))
        mock = MagicMock()
        mock.name = name
        return mock

    from olav.agents import agent as agent_module

    monkeypatch.setattr(agent_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(agent_module, "_agent_dir_override", str(tmp_path / "workspace"), raising=False)
    monkeypatch.setattr(agent_module, "build_summarization_middleware", lambda llm: fake_summ_instance)

    # Build a minimal OlavAgent-like object without full LLM setup
    obj = object.__new__(agent_module.OLAVAgent)
    obj._agent_dir = tmp_path / "workspace"
    obj.llm = MagicMock()

    obj._build_subagents(olav_config)

    return captured


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCompiledSubAgentMiddleware:
    def test_summarization_middleware_present(self, tmp_path, monkeypatch):
        """CC-01: SummarizationMiddleware must be injected."""
        from deepagents.middleware import SummarizationMiddleware

        captured = _make_minimal_agent_build(tmp_path, monkeypatch)

        assert captured, "create_agent was not called — no tool-bearing subagent found"
        middleware_list = captured[0]
        assert _has_middleware_type(middleware_list, SummarizationMiddleware), (
            f"SummarizationMiddleware missing. Got: {[type(m) for m in middleware_list]}"
        )

    def test_filesystem_middleware_absent(self, tmp_path, monkeypatch):
        """CC-01 constraint: FilesystemMiddleware must NOT be injected."""
        from deepagents.middleware import FilesystemMiddleware

        captured = _make_minimal_agent_build(tmp_path, monkeypatch)

        assert captured, "create_agent was not called"
        middleware_list = captured[0]
        assert not _has_middleware_type(middleware_list, FilesystemMiddleware), (
            "FilesystemMiddleware must never be injected into compiled subagents"
        )

    def test_todo_list_middleware_present(self, tmp_path, monkeypatch):
        """TodoListMiddleware must still be present (baseline)."""
        from langchain.agents.middleware import TodoListMiddleware

        captured = _make_minimal_agent_build(tmp_path, monkeypatch)

        assert captured, "create_agent was not called"
        middleware_list = captured[0]
        assert _has_middleware_type(middleware_list, TodoListMiddleware), (
            f"TodoListMiddleware missing. Got: {[type(m) for m in middleware_list]}"
        )

    def test_prompt_caching_middleware_when_available(self, tmp_path, monkeypatch):
        """CC-01: AnthropicPromptCachingMiddleware injected when bridge reports it available."""
        from olav.agents import _deepagents_bridge as bridge

        if not bridge.HAS_PROMPT_CACHING:
            pytest.skip("AnthropicPromptCachingMiddleware not available in current deepagents")

        from olav.agents._deepagents_bridge import AnthropicPromptCachingMiddleware  # type: ignore[attr-defined]

        captured = _make_minimal_agent_build(tmp_path, monkeypatch)

        assert captured, "create_agent was not called"
        middleware_list = captured[0]
        assert _has_middleware_type(middleware_list, AnthropicPromptCachingMiddleware), (
            f"AnthropicPromptCachingMiddleware missing. Got: {[type(m) for m in middleware_list]}"
        )
