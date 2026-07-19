"""ToolLoopBreakerMiddleware — ISSUE-NO-TOOL-CALL-CIRCUIT-BREAKER (2026-07-19).

A corrupted gemma4 tool-call emission retried the same failing glob 59×,
snowballing to a 16M-token request. The breaker must:
  1. short-circuit an identical (tool, args) call after 3 consecutive failures
  2. hard-stop the run (jump_to end) if the model keeps repeating past 6
  3. count per-signature (interleaved successes on OTHER calls don't reset it)
  4. reset all state at the start of each agent run
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from olav.agents.loop_breaker import ToolLoopBreakerMiddleware


def _req(name="glob", args=None, call_id="c1"):
    return SimpleNamespace(tool_call={"name": name, "args": args or {}, "id": call_id})


def _failing_handler(request):
    return ToolMessage(content="boom", tool_call_id=request.tool_call["id"],
                       name=request.tool_call["name"], status="error")


def _ok_handler(request):
    return ToolMessage(content="ok", tool_call_id=request.tool_call["id"],
                       name=request.tool_call["name"])


def test_short_circuits_after_three_identical_failures():
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    executed = {"n": 0}

    def handler(request):
        executed["n"] += 1
        return _failing_handler(request)

    req = _req(args={"pattern": "**/broken<|markup|>"})
    for _ in range(3):
        mw.wrap_tool_call(req, handler)
    assert executed["n"] == 3

    result = mw.wrap_tool_call(req, handler)
    assert executed["n"] == 3, "4th identical failing call must NOT execute"
    assert isinstance(result, ToolMessage) and result.status == "error"
    assert "circuit breaker" in result.content


def test_success_resets_the_signature():
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    req = _req(args={"x": 1})
    mw.wrap_tool_call(req, _failing_handler)
    mw.wrap_tool_call(req, _failing_handler)
    mw.wrap_tool_call(req, _ok_handler)          # success clears the count
    executed = {"n": 0}

    def handler(request):
        executed["n"] += 1
        return _failing_handler(request)

    for _ in range(3):
        mw.wrap_tool_call(req, handler)
    assert executed["n"] == 3, "count must restart after a success"


def test_different_args_are_independent_signatures():
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    for _ in range(3):
        mw.wrap_tool_call(_req(args={"a": 1}), _failing_handler)
    # same tool, different args → still executes
    executed = {"n": 0}

    def handler(request):
        executed["n"] += 1
        return _ok_handler(request)

    mw.wrap_tool_call(_req(args={"a": 2}), handler)
    assert executed["n"] == 1


def test_interleaved_success_on_other_call_does_not_reset():
    """The crash pattern: glob failures interleaved with successful batfish_q."""
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    bad = _req(name="glob", args={"pattern": "junk"})
    good = _req(name="batfish_q", args={"question": "nodes"}, call_id="c2")
    for _ in range(3):
        mw.wrap_tool_call(bad, _failing_handler)
        mw.wrap_tool_call(good, _ok_handler)
    result = mw.wrap_tool_call(bad, _failing_handler)
    assert "circuit breaker" in result.content


def test_hard_stop_jumps_to_end_after_persistent_repeats():
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    req = _req(args={"pattern": "junk"})
    for _ in range(6):  # 3 real failures + 3 blocked attempts
        mw.wrap_tool_call(req, _failing_handler)
    update = mw.before_model(state={}, runtime=None)
    assert update is not None and update["jump_to"] == "end"
    assert isinstance(update["messages"][0], AIMessage)
    assert "partial" in update["messages"][0].content


def test_no_hard_stop_below_threshold():
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    req = _req(args={"pattern": "junk"})
    for _ in range(4):
        mw.wrap_tool_call(req, _failing_handler)
    assert mw.before_model(state={}, runtime=None) is None


def test_before_agent_resets_state_between_runs():
    """Compiled agents are long-lived — a tripped breaker must not poison
    the NEXT run."""
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    req = _req(args={"pattern": "junk"})
    for _ in range(6):
        mw.wrap_tool_call(req, _failing_handler)
    mw.before_agent(state={}, runtime=None)      # new run starts
    assert mw.before_model(state={}, runtime=None) is None
    executed = {"n": 0}

    def handler(request):
        executed["n"] += 1
        return _ok_handler(request)

    mw.wrap_tool_call(req, handler)
    assert executed["n"] == 1


@pytest.mark.asyncio
async def test_async_path_mirrors_sync():
    mw = ToolLoopBreakerMiddleware(agent_name="t")
    req = _req(args={"pattern": "junk"})

    async def failing(request):
        return _failing_handler(request)

    for _ in range(3):
        await mw.awrap_tool_call(req, failing)
    result = await mw.awrap_tool_call(req, failing)
    assert "circuit breaker" in result.content
    for _ in range(2):
        await mw.awrap_tool_call(req, failing)
    update = await mw.abefore_model(state={}, runtime=None)
    assert update is not None and update["jump_to"] == "end"


def test_wired_into_agent_assembly():
    """Wiring proof (CLAUDE.md DoD): agent.py must attach the breaker on the
    orchestrator path, the plain sub-agent path, and the recursive
    deep-agent path."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "src/olav/agents/agent.py").read_text(
        encoding="utf-8"
    )
    assert src.count("ToolLoopBreakerMiddleware(agent_name=") >= 2, (
        "breaker must be constructed for both orchestrator and sub-agents"
    )
    assert "_deep_extra_mw = _deep_extra_mw + [_breaker_mw]" in src, (
        "recursive deep-agents skip _middleware — breaker must be added to "
        "_deep_extra_mw explicitly"
    )
