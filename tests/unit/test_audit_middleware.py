"""
tests/unit/test_audit_middleware.py
───────────────────────────────────
Unit coverage for src/olav/plugins/middleware/audit.py (P3 cycle 3).

AuditMiddleware converts :class:`AuditCallbackPlugin`'s observer-
style hooks into LangGraph ``AgentMiddleware`` hooks.  The test
surface here is the **smallest parity matrix** — covering:

1. ``abefore_agent`` records ``run_start`` with run_id/agent_id
   lifted from ``runtime.context`` (OlavRunContext).
2. ``aafter_agent`` records ``run_end`` and clears per-run buffers.
3. ``awrap_tool_call`` records ``tool_call_started`` before the
   handler runs and ``tool_call_completed`` after.
4. Missing context (``runtime.context = None``) is silently skipped —
   middleware must never crash just because no caller-supplied run
   metadata was attached.
5. Recorder errors are swallowed — audit must never block execution
   (parity with the original callback's try/except policy).

Full callback→middleware feature parity (system prompt capture,
injection scan, hooks.fire_hook) is deferred to later cycles; this
suite only guards the critical run-level + tool-level events so
``test_audit_parity_callback_vs_middleware.py`` has something to
compare against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


# ── Test doubles ───────────────────────────────────────────────────────────


@dataclass
class _FakeRuntime:
    """Matches the subset of ``langgraph.runtime.Runtime`` the
    middleware reads."""

    context: Any = None


class _SpyRecorder:
    """Captures every call the middleware makes; lets tests assert
    on event sequence + payload contents without touching DuckDB."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.fail_on_next_record: bool = False

    def record(self, *, event_type: str, run_id: str | None = None, payload: dict | None = None) -> None:
        if self.fail_on_next_record:
            self.fail_on_next_record = False
            raise RuntimeError("simulated audit backend failure")
        self.events.append(
            {
                "event_type": event_type,
                "run_id": run_id,
                "payload": dict(payload or {}),
            }
        )

    def record_tool_call(
        self,
        *,
        run_id: str,
        tool_name: str,
        input_args: str = "",
        output: str = "",
        status: str = "completed",
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> str:
        call_id = f"call-{len(self.tool_calls)}"
        self.tool_calls.append(
            {
                "call_id": call_id,
                "run_id": run_id,
                "tool_name": tool_name,
                "input_args": input_args,
                "output": output,
                "status": status,
                "error": error,
                "duration_ms": duration_ms,
            }
        )
        return call_id

    def record_message(self, *, run_id: str, role: str, content: str, tool_call_id: str | None = None) -> None:
        self.messages.append(
            {
                "run_id": run_id,
                "role": role,
                "content": content,
                "tool_call_id": tool_call_id,
            }
        )


# ── 1. Importable ──────────────────────────────────────────────────────────


def test_module_importable() -> None:
    from olav.plugins.middleware import audit as audit_mw

    assert hasattr(audit_mw, "AuditMiddleware")


def test_instance_has_plugin_metadata() -> None:
    """Subclasses of OLAVMiddlewarePlugin must carry name/version/
    description so load_builtin_plugins finds them."""
    from olav.plugins.middleware.audit import AuditMiddleware

    mw = AuditMiddleware()
    assert mw.name == "audit_middleware"
    assert mw.version
    assert mw.description


# ── 2. before_agent → run_start ────────────────────────────────────────────


def test_before_agent_records_run_start() -> None:
    import asyncio

    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    recorder = _SpyRecorder()
    ctx = OlavRunContext(
        run_id="run-1",
        recorder=recorder,
        agent_id="core",
        user_id="alice",
        source_channel="cli_interactive",
    )
    runtime = _FakeRuntime(context=ctx)
    mw = AuditMiddleware()

    asyncio.run(mw.abefore_agent({"messages": []}, runtime))

    assert len(recorder.events) == 1
    evt = recorder.events[0]
    assert evt["event_type"] == "run_start"
    assert evt["run_id"] == "run-1"
    assert evt["payload"].get("agent_id") == "core"
    assert evt["payload"].get("user_id") == "alice"
    assert evt["payload"].get("source_channel") == "cli_interactive"


# ── 3. after_agent → run_end ───────────────────────────────────────────────


def test_after_agent_records_run_end() -> None:
    import asyncio

    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    recorder = _SpyRecorder()
    ctx = OlavRunContext(run_id="run-2", recorder=recorder, agent_id="ops")
    runtime = _FakeRuntime(context=ctx)
    mw = AuditMiddleware()

    asyncio.run(mw.aafter_agent({"messages": []}, runtime))

    assert len(recorder.events) == 1
    assert recorder.events[0]["event_type"] == "run_end"
    assert recorder.events[0]["run_id"] == "run-2"


# ── 4. wrap_tool_call records start + completed ────────────────────────────


def test_wrap_tool_call_records_started_and_completed() -> None:
    import asyncio

    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    recorder = _SpyRecorder()
    ctx = OlavRunContext(run_id="run-3", recorder=recorder, agent_id="core")
    mw = AuditMiddleware()

    # Simulate a LangGraph ToolCallRequest with the attributes
    # middleware actually reads (tool name + arguments).  Duck-typed.
    class _FakeToolRequest:
        def __init__(self) -> None:
            self.tool_call = {
                "id": "call_abc",
                "name": "execute_sql",
                "args": {"sql": "SELECT 1"},
            }
            self.runtime = _FakeRuntime(context=ctx)

    class _FakeToolMessage:
        def __init__(self, content: str) -> None:
            self.content = content
            self.tool_call_id = "call_abc"

    async def _handler(req: Any) -> Any:
        return _FakeToolMessage("1")

    req = _FakeToolRequest()
    result = asyncio.run(mw.awrap_tool_call(req, _handler))

    assert result.content == "1"
    # One "started" + one "completed"
    event_types = [e["event_type"] for e in recorder.events]
    assert event_types == ["tool_call_started", "tool_call_completed"]
    # record_tool_call row written
    assert len(recorder.tool_calls) == 1
    tc = recorder.tool_calls[0]
    assert tc["run_id"] == "run-3"
    assert tc["tool_name"] == "execute_sql"
    assert tc["status"] == "completed"
    assert tc["duration_ms"] is not None


def test_wrap_tool_call_records_failure_on_handler_exception() -> None:
    import asyncio

    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    recorder = _SpyRecorder()
    ctx = OlavRunContext(run_id="run-4", recorder=recorder)
    mw = AuditMiddleware()

    class _FakeToolRequest:
        def __init__(self) -> None:
            self.tool_call = {"id": "call_1", "name": "x", "args": {}}
            self.runtime = _FakeRuntime(context=ctx)

    async def _handler(req: Any) -> Any:
        raise RuntimeError("kaboom")

    req = _FakeToolRequest()
    with pytest.raises(RuntimeError, match="kaboom"):
        asyncio.run(mw.awrap_tool_call(req, _handler))

    event_types = [e["event_type"] for e in recorder.events]
    assert "tool_call_started" in event_types
    assert "tool_call_failed" in event_types
    # tool_call row records the failure
    assert recorder.tool_calls[0]["status"] == "error"
    assert "kaboom" in (recorder.tool_calls[0]["error"] or "")


# ── 5. Missing context is silently skipped ─────────────────────────────────


def test_missing_context_silently_skips() -> None:
    import asyncio

    from olav.plugins.middleware.audit import AuditMiddleware

    # runtime.context is None → no caller set OlavRunContext
    runtime = _FakeRuntime(context=None)
    mw = AuditMiddleware()

    # Must not raise
    asyncio.run(mw.abefore_agent({"messages": []}, runtime))
    asyncio.run(mw.aafter_agent({"messages": []}, runtime))


def test_context_without_recorder_silently_skips() -> None:
    import asyncio

    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    # OlavRunContext exists but recorder is None
    ctx = OlavRunContext(run_id="r", recorder=None)
    runtime = _FakeRuntime(context=ctx)
    mw = AuditMiddleware()

    asyncio.run(mw.abefore_agent({"messages": []}, runtime))
    # Nothing observable happens — no crash, no events
    # (we can't assert on a real recorder because there is none)


# ── 6. Recorder errors must not bubble ─────────────────────────────────────


def test_recorder_exception_is_swallowed() -> None:
    import asyncio

    from olav.plugins.middleware._context import OlavRunContext
    from olav.plugins.middleware.audit import AuditMiddleware

    recorder = _SpyRecorder()
    recorder.fail_on_next_record = True
    ctx = OlavRunContext(run_id="r", recorder=recorder)
    runtime = _FakeRuntime(context=ctx)
    mw = AuditMiddleware()

    # Must not raise — parity with AuditCallbackPlugin's "audit must never
    # block execution" policy.
    asyncio.run(mw.abefore_agent({"messages": []}, runtime))
