"""Tests for the grounded-result check (dev_docs/97 ISSUE-LE-GRADER-SYNTHESIS-ONLY).

The deterministic grader's synthesis floor ("prose present") passed answers that
were prose-but-fabricated — e.g. a confident result built on top of tool calls
that all failed. The opt-in ``require_grounded`` criterion fails exactly that
case (all tools failed + the answer does not acknowledge the failure), while
staying pass-biased everywhere else.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from olav.agents.deterministic_grader import (
    DeterministicSynthesisMiddleware,
    _acknowledges_failure,
    _tool_failure_stats,
)


def _state(ai_text, tool_msgs=()):
    msgs = [HumanMessage(content="q"), *tool_msgs, AIMessage(content=ai_text)]
    return {"messages": msgs}


def _failed_tool(name="execute_skill_script"):
    # framework sets status="error" when a tool raises
    return ToolMessage(content='{"status": "error", "error": "boom"}', tool_call_id="t", name=name, status="error")


def _ok_tool(name="execute_skill_script"):
    return ToolMessage(content='{"status": "ok", "data": [{"n": 348}]}', tool_call_id="t", name=name)


# --- _tool_failure_stats ---

def test_stats_counts_failures():
    msgs = [_ok_tool(), _failed_tool(), _failed_tool()]
    assert _tool_failure_stats(msgs) == (3, 2)


def test_stats_detects_error_envelope_without_status_field():
    # content-only failure marker (tool returned error dict without raising)
    tm = ToolMessage(content='{"status": "error", "message": "x"}', tool_call_id="t", name="x")
    assert _tool_failure_stats([tm]) == (1, 1)


def test_acknowledges_failure_en_and_cn():
    assert _acknowledges_failure("I could not reach the service.")
    assert _acknowledges_failure("抱歉，我无法连接数据库。")
    assert not _acknowledges_failure("NetBox is reachable, version 4.5.5.")


# --- grounded criterion (require_grounded=True) ---

def _mw(grounded=True):
    return DeterministicSynthesisMiddleware(agent_name="api-query", require_grounded=grounded)


def test_grounded_fails_positive_answer_on_all_failed_tools():
    mw = _mw()
    r = mw._evaluate(_state("✅ NetBox 可达，版本 4.5.5。", [_failed_tool(), _failed_tool()]))
    assert (r or {}).get("jump_to") == "model", "fabricated success on all-failed tools must loop back"


def test_grounded_passes_when_failure_acknowledged():
    mw = _mw()
    r = mw._evaluate(_state("抱歉，所有工具调用都失败了，我无法确认 NetBox 状态。", [_failed_tool()]))
    assert r is None, "honest failure must pass"


def test_grounded_passes_when_a_tool_succeeded():
    mw = _mw()
    r = mw._evaluate(_state("NetBox 可达，版本 4.5.5。", [_failed_tool(), _ok_tool()]))
    assert r is None, "any successful tool grounds the answer"


def test_grounded_passes_when_no_tools_called():
    mw = _mw()
    r = mw._evaluate(_state("Here is a plain answer with no tool calls."))
    assert r is None


def test_grounded_opt_out_passes_fabricated_answer():
    mw = _mw(grounded=False)
    # proper prose so the synthesis floor passes, isolating the grounded opt-out
    r = mw._evaluate(_state("NetBox 服务现在可达，版本是 4.5.5。", [_failed_tool()]))
    assert r is None, "require_grounded=False keeps the old synthesis-only behaviour"


def test_grounded_bounded_no_infinite_loop():
    mw = _mw()
    # already at the iteration budget → must not jump again (proper prose so the
    # prose floor passes; the grounded criterion is what would otherwise fire)
    msgs = [HumanMessage(content="q"), _failed_tool(),
            AIMessage(content="NetBox 服务现在可达，版本是 4.5.5。")]
    r = mw._evaluate({"messages": msgs, "_det_synth_iters": 1})
    assert (r or {}).get("jump_to") is None


def test_no_prose_still_fails_first():
    # prose floor is checked before grounded; pure table → needs_revision
    mw = _mw()
    r = mw._evaluate(_state("| a | b |\n|---|---|\n| 1 | 2 |", [_ok_tool()]))
    assert (r or {}).get("jump_to") == "model"
