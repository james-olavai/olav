"""TDD (dev_docs/73 §2.6.2): sub-agents that declare their own `subagents:`
field in SKILL.md must be built via `create_deep_agent` (not
`create_agent`), so deepagents `SubAgentMiddleware` auto-injects a
`task(description, subagent_type)` tool for cross-domain delegation.

This is the enabling change for the analyzer→sim delegation pattern.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _setup_workspace(root: Path, sub_with_subagents: bool):
    """Build a tmp workspace with one sub-agent. If sub_with_subagents=True,
    the sub-agent declares its own subagents pointing at a grandchild."""
    # Parent workspace AGENT.md declaring `subagent_parent` as sub-agent
    (root / "AGENT.md").write_text(
        "---\n"
        "name: orchestrator\n"
        "description: test\n"
        "subagents:\n"
        "  - path: ./subagent_parent/SKILL.md\n"
        "---\n\n"
        "# orchestrator prompt.\n"
    )

    # The sub-agent we care about
    sa_dir = root / "subagent_parent"
    sa_dir.mkdir()
    subagents_block = (
        "subagents:\n"
        "  - path: ../grandchild/SKILL.md\n"
    ) if sub_with_subagents else ""
    (sa_dir / "SKILL.md").write_text(
        "---\n"
        "name: subagent_parent\n"
        "description: test\n"
        f"{subagents_block}"
        "---\n\n"
        "# subagent_parent prompt.\n"
    )
    (sa_dir / "prompts").mkdir()
    (sa_dir / "prompts" / "system.md").write_text("Parent sub-agent prompt.")

    # Grandchild (only used when sub_with_subagents=True)
    gc_dir = root / "grandchild"
    gc_dir.mkdir()
    (gc_dir / "SKILL.md").write_text(
        "---\n"
        "name: grandchild\n"
        "description: leaf\n"
        "---\n\n"
        "# grandchild prompt.\n"
    )
    (gc_dir / "prompts").mkdir()
    (gc_dir / "prompts" / "system.md").write_text("Grandchild prompt.")


def _build_subagents_only(workspace_root: Path):
    """Invoke OLAVAgent._build_subagents in isolation (no real LLM)."""
    from olav.agents.agent import OLAVAgent

    bare = object.__new__(OLAVAgent)
    bare._agent_dir = workspace_root
    bare.llm = MagicMock(name="mock_llm")
    bare.model_name = "test-model"
    bare.temperature = 0.0
    bare._preloaded_olav_config = {}
    # olav_base_path attribute is read by _build_subagents to find
    # workspace/core/SKILL.md — point at a non-existent dir so the
    # core-tool injection branch is skipped.
    bare.olav_base_path = workspace_root / "_no_core"

    olav_config = {"subagents": [{"path": "./subagent_parent/SKILL.md"}]}
    return bare._build_subagents(olav_config)


def test_subagent_without_subagents_field_uses_create_agent(tmp_path):
    """Baseline: sub-agent with no `subagents:` field → create_agent path."""
    _setup_workspace(tmp_path, sub_with_subagents=False)

    with (
        patch("olav.agents.agent.create_agent") as mock_create_agent,
        patch("olav.agents.agent.create_deep_agent") as mock_create_deep,
    ):
        mock_create_agent.return_value = MagicMock(name="leaf_runnable")
        _build_subagents_only(tmp_path)

    assert mock_create_agent.called, \
        "Sub-agent without subagents: must be built via create_agent"
    assert not mock_create_deep.called, \
        "Sub-agent without subagents: must NOT be built via create_deep_agent"


def test_subagent_with_subagents_field_uses_create_deep_agent(tmp_path):
    """Phase 1 target: sub-agent declaring `subagents:` → create_deep_agent
    so SubAgentMiddleware auto-injects the `task` tool.
    """
    _setup_workspace(tmp_path, sub_with_subagents=True)

    with (
        patch("olav.agents.agent.create_agent") as mock_create_agent,
        patch("olav.agents.agent.create_deep_agent") as mock_create_deep,
    ):
        mock_create_deep.return_value = MagicMock(name="parent_with_task_runnable")
        # The grandchild build still goes through create_agent (leaf)
        mock_create_agent.return_value = MagicMock(name="grandchild_runnable")

        _build_subagents_only(tmp_path)

    assert mock_create_deep.called, (
        "Sub-agent with subagents: declared MUST be built via "
        "create_deep_agent so SubAgentMiddleware injects task()"
    )
    # The grandchild (leaf) should still be built via create_agent
    assert mock_create_agent.called, (
        "Grandchild (leaf, no subagents:) must be built via create_agent"
    )

    # Verify create_deep_agent received the grandchild in its subagents= kwarg
    kwargs = mock_create_deep.call_args.kwargs
    assert "subagents" in kwargs, (
        "create_deep_agent must be called with subagents= for the children"
    )
    assert kwargs["subagents"], (
        "subagents= must be non-empty (the grandchild was declared)"
    )
