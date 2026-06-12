"""
tests/integration/test_audit_parity_callback_vs_middleware.py
─────────────────────────────────────────────────────────────
P3 cycle 5 — semantic parity between :class:`AuditCallbackPlugin`
(legacy callback path) and :class:`AuditMiddleware` (new middleware
path) for the events they both cover.

Strategy
--------
A full-agent parity test requires LLM credentials and a real
LangGraph ainvoke, so it's deferred to Phase 6's cutover.  Here we
drive both paths with equivalent inputs and assert the recorder
receives equivalent rows — field-by-field, ignoring timestamps and
duration_ms.

Scope for this cycle
--------------------
Tool-call parity (tool_call_started / tool_call_completed /
record_tool_call row / role="tool" message).  Deferred:

* LLM lifecycle events (on_llm_end → ``llm_usage``) — requires a
  LangChain LLMResult construction
* system-prompt capture on first model turn
* cross-turn state on ``_tool_runs`` — not parity-relevant, it's an
  internal bookkeeping implementation detail

The test uses the ``_SpyRecorder`` defined in
:mod:`tests.unit.test_audit_middleware` (imported, not duplicated).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


# ── Test scaffolding ────────────────────────────────────────────────────────


@pytest.fixture
def spy_recorder() -> Any:
    """Return a fresh ``_SpyRecorder``; imported from the unit test
    module so the recording schema stays in one place."""
    from tests.unit.test_audit_middleware import _SpyRecorder

    return _SpyRecorder()


class _FakeRuntime:
    """Matches the subset of ``langgraph.runtime.Runtime`` the
    middleware reads."""

    def __init__(self, context: Any) -> None:
        self.context = context


# ── Helpers to drive each path with the same stimulus ──────────────────────


async def _drive_callback_tool_call(
    cb_plugin: Any,
    *,
    tool_name: str,
    input_str: str,
    output_str: str,
    langchain_run_id: str,
) -> None:
    """Fire the callback plugin's on_tool_start then on_tool_end with
    the shapes LangChain uses in production."""
    import uuid

    await cb_plugin.on_tool_start(
        {"name": tool_name},
        input_str,
        run_id=uuid.UUID(langchain_run_id),
        tool_call_id="call_abc",
    )
    # LangChain hands back the plain string in most cases.
    await cb_plugin.on_tool_end(
        output_str,
        run_id=uuid.UUID(langchain_run_id),
    )


async def _drive_middleware_tool_call(
    mw: Any,
    *,
    tool_name: str,
    input_args: dict,
    output_str: str,
    ctx: Any,
) -> None:
    """Simulate a LangGraph ToolCallRequest flowing through the
    middleware."""

    class _FakeToolRequest:
        def __init__(self) -> None:
            self.tool_call = {
                "id": "call_abc",
                "name": tool_name,
                "args": input_args,
            }
            self.runtime = _FakeRuntime(context=ctx)

    class _FakeToolMessage:
        def __init__(self, content: str) -> None:
            self.content = content
            self.tool_call_id = "call_abc"

    async def _handler(req: Any) -> Any:
        return _FakeToolMessage(output_str)

    req = _FakeToolRequest()
    await mw.awrap_tool_call(req, _handler)


# ── 1. record_tool_call row parity ─────────────────────────────────────────


def test_record_tool_call_row_parity(spy_recorder) -> None:
    """Both paths must write a ``record_tool_call`` row with matching
    (run_id, tool_name, status, input args) — the fields dataset export
    joins on."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    # Callback path
    cb_plugin = AuditCallbackPlugin(recorder=spy_recorder)
    cb_plugin.bind_run("run-parity", spy_recorder)
    asyncio.run(
        _drive_callback_tool_call(
            cb_plugin,
            tool_name="execute_sql",
            input_str="SELECT 1",
            output_str="1",
            langchain_run_id="12345678-1234-5678-1234-567812345678",
        )
    )

    cb_rows = [dict(r) for r in spy_recorder.tool_calls]
    spy_recorder.tool_calls.clear()
    spy_recorder.events.clear()
    spy_recorder.messages.clear()

    # Middleware path
    ctx = OlavRunContext(
        run_id="run-parity", recorder=spy_recorder, agent_id="core"
    )
    mw = AuditMiddleware()
    asyncio.run(
        _drive_middleware_tool_call(
            mw,
            tool_name="execute_sql",
            input_args={"sql": "SELECT 1"},
            output_str="1",
            ctx=ctx,
        )
    )
    mw_rows = [dict(r) for r in spy_recorder.tool_calls]

    # Both recorded exactly one row
    assert len(cb_rows) == 1
    assert len(mw_rows) == 1

    cb_row, mw_row = cb_rows[0], mw_rows[0]

    # Parity fields — must match exactly
    assert cb_row["run_id"] == mw_row["run_id"] == "run-parity"
    assert cb_row["tool_name"] == mw_row["tool_name"] == "execute_sql"
    assert cb_row["status"] == mw_row["status"] == "completed"
    assert cb_row["output"] == mw_row["output"] == "1"

    # Fields that differ by representation (known/documented delta):
    #   callback records input_str (raw string "SELECT 1")
    #   middleware records JSON-serialised dict ('{"sql": "SELECT 1"}')
    # Both are "lossless captures of what the tool received"; the
    # parity is semantic, not byte-equal.
    assert "SELECT 1" in cb_row["input_args"]
    assert "SELECT 1" in mw_row["input_args"]


# ── 2. role=tool message parity (for SFT/trajectory dataset export) ───────


def test_role_tool_message_parity(spy_recorder) -> None:
    """Both paths emit a role='tool' audit_messages row so dataset
    export can reconstruct the OpenAI tool-call turn."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    # Callback
    cb_plugin = AuditCallbackPlugin(recorder=spy_recorder)
    cb_plugin.bind_run("run-msg", spy_recorder)
    asyncio.run(
        _drive_callback_tool_call(
            cb_plugin,
            tool_name="x",
            input_str="a",
            output_str="result-X",
            langchain_run_id="00000000-0000-0000-0000-000000000001",
        )
    )
    cb_msgs = [m for m in spy_recorder.messages if m["role"] == "tool"]
    spy_recorder.messages.clear()
    spy_recorder.tool_calls.clear()
    spy_recorder.events.clear()

    # Middleware
    ctx = OlavRunContext(run_id="run-msg", recorder=spy_recorder)
    mw = AuditMiddleware()
    asyncio.run(
        _drive_middleware_tool_call(
            mw,
            tool_name="x",
            input_args={"a": "a"},
            output_str="result-X",
            ctx=ctx,
        )
    )
    mw_msgs = [m for m in spy_recorder.messages if m["role"] == "tool"]

    assert len(cb_msgs) == 1, f"callback wrote {len(cb_msgs)} tool msgs"
    assert len(mw_msgs) == 1, f"middleware wrote {len(mw_msgs)} tool msgs"

    # Parity: both capture the output text + link via tool_call_id
    assert cb_msgs[0]["run_id"] == mw_msgs[0]["run_id"] == "run-msg"
    assert cb_msgs[0]["role"] == mw_msgs[0]["role"] == "tool"
    assert cb_msgs[0]["content"] == mw_msgs[0]["content"] == "result-X"
    # The LLM-assigned tool_call_id (OpenAI "call_xxx" format) flows
    # through both paths — enables valid SFT dataset assembly.
    assert cb_msgs[0]["tool_call_id"] == mw_msgs[0]["tool_call_id"] == "call_abc"


# ── 3. Event-type sequence parity ──────────────────────────────────────────


def test_event_type_sequence_parity(spy_recorder) -> None:
    """Both paths should produce the same semantic event sequence
    for a single tool call: started → completed."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    # Callback
    cb_plugin = AuditCallbackPlugin(recorder=spy_recorder)
    cb_plugin.bind_run("run-seq", spy_recorder)
    asyncio.run(
        _drive_callback_tool_call(
            cb_plugin,
            tool_name="x",
            input_str="a",
            output_str="y",
            langchain_run_id="00000000-0000-0000-0000-000000000002",
        )
    )
    cb_events = [e["event_type"] for e in spy_recorder.events]
    spy_recorder.events.clear()
    spy_recorder.tool_calls.clear()
    spy_recorder.messages.clear()

    # Middleware
    ctx = OlavRunContext(run_id="run-seq", recorder=spy_recorder)
    mw = AuditMiddleware()
    asyncio.run(
        _drive_middleware_tool_call(
            mw,
            tool_name="x",
            input_args={"a": "a"},
            output_str="y",
            ctx=ctx,
        )
    )
    mw_events = [e["event_type"] for e in spy_recorder.events]

    # Strip any events outside the tool lifecycle (e.g. llm_* stuff the
    # callback fires and middleware doesn't, not parity-relevant here).
    tool_events_cb = [e for e in cb_events if e.startswith("tool_call_")]
    tool_events_mw = [e for e in mw_events if e.startswith("tool_call_")]

    assert tool_events_cb == tool_events_mw == [
        "tool_call_started",
        "tool_call_completed",
    ]
