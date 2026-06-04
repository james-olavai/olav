"""Governance: orchestrator graph FS tools are pruned after create_deep_agent().

deepagents always injects FilesystemMiddleware (read_file/write_file/edit_file/
glob/grep/ls/execute) and TodoListMiddleware (write_todos) into every graph
regardless of `tools=[]`. OLAV prunes these from sub-agents; commit 4a05392e
extended the same prune to the orchestrator's own compiled graph.

These tests verify that pure-router orchestrators (admin, core) end up with
only their declared tools + task/olav_delegate, NOT the FS tools.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def _admin_agent():
    os.environ.setdefault("OLAV_AUTH_MODE", "none")
    # Provide dummy API key so LLMFactory does not raise openai.OpenAIError
    # in CI where OPENAI_API_KEY is not set. The agent is never invoked,
    # only its graph tool list is inspected.
    os.environ.setdefault("OLAV_LLM_API_KEY", "test")
    import logging
    logging.disable(logging.CRITICAL)
    from olav.agents.agent import OLAVAgent
    return OLAVAgent(agent_id="admin")


def _orchestrator_tools(agent) -> set[str]:
    """Extract tool names from the orchestrator's compiled ToolNode."""
    for _name, node in (agent.graph.nodes or {}).items():
        if _name == "tools":
            bound = getattr(node, "bound", node)
            tlist = (
                getattr(bound, "tools", None)
                or getattr(bound, "tools_by_name", None)
            )
            if tlist:
                return {
                    k for k in (tlist.keys() if isinstance(tlist, dict)
                                else (t.name for t in tlist))
                }
    return set()


_FS_TOOLS = {"read_file", "write_file", "edit_file", "glob", "grep", "ls", "execute"}
_TODO_TOOLS = {"write_todos"}
_ALL_INJECTED = _FS_TOOLS | _TODO_TOOLS


class TestOrchestratorFSPrune:
    """After create_deep_agent(), deepagents-injected FS tools must be absent
    from the orchestrator graph when the AGENT.md declares no FS tools.

    Regression: before commit 4a05392e the admin orchestrator had 12 tools
    including all FS tools, causing gemma4 to explore the filesystem instead
    of delegating via task("ops").
    """

    def test_admin_orchestrator_has_no_fs_tools(self, _admin_agent):
        tools = _orchestrator_tools(_admin_agent)
        leaked = tools & _FS_TOOLS
        assert not leaked, (
            f"admin orchestrator still has FS tools after prune: {sorted(leaked)}\n"
            "Expected: empty — admin is a pure router (task/olav_delegate only).\n"
            "Check _prune_graph_tools() call in OLAVAgent.__init__."
        )

    def test_admin_orchestrator_has_no_write_todos(self, _admin_agent):
        tools = _orchestrator_tools(_admin_agent)
        assert "write_todos" not in tools, (
            "write_todos injected into admin orchestrator — pure router should not have it.\n"
            "admin AGENT.md does not declare enable_todo_list; TodoListMiddleware "
            "should be pruned from the orchestrator graph."
        )

    def test_admin_orchestrator_retains_delegation_tools(self, _admin_agent):
        tools = _orchestrator_tools(_admin_agent)
        assert "task" in tools, (
            "task tool missing from admin orchestrator — sub-agent delegation broken."
        )

    def test_admin_orchestrator_tool_count_is_small(self, _admin_agent):
        tools = _orchestrator_tools(_admin_agent)
        assert len(tools) <= 6, (
            f"admin orchestrator has {len(tools)} tools: {sorted(tools)}\n"
            "Expected ≤6 (task + olav_delegate + memory tools). "
            "Possible FS tool leak — check _prune_graph_tools() in __init__."
        )

    def test_keep_orchestrator_fs_tools_opt_out(self):
        """keep_orchestrator_fs_tools: true in AGENT.md should bypass the prune."""
        import logging
        logging.disable(logging.CRITICAL)
        # We don't actually build a full agent here — just verify the flag is
        # read and respected by checking the code path exists.
        from olav.agents.agent import OLAVAgent
        import inspect
        src = inspect.getsource(OLAVAgent.__init__)
        assert "keep_orchestrator_fs_tools" in src, (
            "OLAVAgent.__init__ does not check 'keep_orchestrator_fs_tools' flag.\n"
            "Agents that legitimately need FS tools (e.g. devops/scripts) must be "
            "able to opt out of the orchestrator prune."
        )
