"""AuditMiddleware — LangGraph ``AgentMiddleware`` audit observer.

The middleware-mode counterpart to
:class:`olav.plugins.callbacks.audit.AuditCallbackPlugin`.  Activated
when ``OLAV_MIDDLEWARE_MODE=middleware`` (P3 cycle 4); v0.20.1 keeps
the callback version as the default so users see no behaviour change.

Why AgentMiddleware instead of callback
---------------------------------------
Once the TUI switches to ``server_kwargs=...`` mode (Phase 6), the
LangGraph subprocess owns the graph.  The subprocess cannot reach
OLAV's in-process plugin_registry to run callback observers, but it
*can* load any :class:`AgentMiddleware` that was baked into the graph
at build time.  Middleware is the only path forward.

Context propagation
-------------------
The old callback carried per-turn state via a mutable
``bind_run(run_id)`` on the plugin instance.  That's impossible here
because the middleware instance is shared across concurrent turns.
Instead, the CLI/API entry point attaches an :class:`OlavRunContext`
to the LangGraph call via ``ainvoke(..., context=ctx)``; every
middleware hook reads ``runtime.context`` to get ``run_id`` /
``recorder`` / ``agent_id``.

Audit-never-blocks policy
-------------------------
All recorder calls are wrapped in try/except.  If the audit backend
fails, the event is lost — but the agent loop is never interrupted.
Parity with the original callback's behaviour.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from olav.plugins.base import OLAVMiddlewarePlugin

if TYPE_CHECKING:
    from olav.plugins.middleware._context import OlavRunContext

logger = logging.getLogger("olav.audit")


class AuditMiddleware(OLAVMiddlewarePlugin):
    """Records run/tool/model lifecycle events to ``audit.duckdb``.

    Covers the minimum-viable parity set for P3 cycle 3:

    * ``abefore_agent`` → ``run_start``
    * ``aafter_agent``  → ``run_end``
    * ``awrap_tool_call`` → ``tool_call_started`` / ``tool_call_completed``
      / ``tool_call_failed`` + ``record_tool_call`` row

    Full feature parity (system-prompt capture on first LLM call,
    injection-scan, ``hooks.fire_hook`` integration, ``llm_usage``
    token counting) is deferred to later cycles; parity tests will
    extend this surface incrementally.
    """

    name = "audit_middleware"
    version = "1.0.0"
    description = "Writes run/tool/model lifecycle events to audit.duckdb"
    tags = ["builtin", "audit"]

    def __init__(self) -> None:
        super().__init__()
        # Per-call bookkeeping so after_tool can compute duration.
        # Keyed by a deterministic id derived from the request — we
        # don't get the LangChain run_id like the callback did.
        self._tool_starts: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_context(runtime: Any) -> OlavRunContext | None:
        """Return ``runtime.context`` if it's an :class:`OlavRunContext`."""
        ctx = getattr(runtime, "context", None)
        if ctx is None:
            return None
        # Duck-type check — we don't strictly import the class to avoid
        # a circular during tests that inject their own mock, but the
        # attribute surface must match.
        if not hasattr(ctx, "run_id") or not hasattr(ctx, "recorder"):
            return None
        return ctx  # type: ignore[return-value]

    @staticmethod
    def _safe_record(recorder: Any, **kwargs: Any) -> None:
        """Call ``recorder.record(**kwargs)`` with all exceptions logged
        at debug level.  Audit failures must never propagate."""
        try:
            recorder.record(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("audit record failed: %s", exc)

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    async def abefore_agent(
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Emit ``run_start`` on the first entry to an agent loop."""
        ctx = self._get_context(runtime)
        if ctx is None or ctx.recorder is None or ctx.run_id is None:
            return None
        self._safe_record(
            ctx.recorder,
            event_type="run_start",
            run_id=ctx.run_id,
            payload=ctx.as_dict(),
        )
        return None

    async def aafter_agent(
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Emit ``run_end`` after the agent loop resolves."""
        ctx = self._get_context(runtime)
        if ctx is None or ctx.recorder is None or ctx.run_id is None:
            return None
        self._safe_record(
            ctx.recorder,
            event_type="run_end",
            run_id=ctx.run_id,
            payload=ctx.as_dict(),
        )
        # Clear any leaked per-turn state — defensive; normally
        # aafter_tool_call handles cleanup.
        self._tool_starts.clear()
        return None

    # ------------------------------------------------------------------
    # Tool wrapper
    # ------------------------------------------------------------------

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Any,
    ) -> Any:
        """Wrap a single tool invocation with start/complete/fail audit.

        The LangGraph ``ToolCallRequest`` exposes:

        * ``request.tool_call`` → dict with ``id`` / ``name`` / ``args``
        * ``request.runtime``   → the same ``Runtime`` we saw in
          ``before_model`` et al; pulls ``context`` from there

        On failure we re-raise so the agent loop sees the exception —
        dropping it would silently corrupt the conversation.
        """
        # Extract tool metadata — be defensive about schema drift
        # between LangGraph versions.
        tool_call = getattr(request, "tool_call", None) or {}
        call_id = str(tool_call.get("id") or id(request))
        tool_name = str(tool_call.get("name") or "unknown")
        input_args = tool_call.get("args") or tool_call.get("arguments") or {}

        runtime = getattr(request, "runtime", None)
        ctx = self._get_context(runtime) if runtime is not None else None
        recorder = ctx.recorder if ctx is not None else None
        run_id = ctx.run_id if ctx is not None else None

        if recorder is not None and run_id is not None:
            self._safe_record(
                recorder,
                event_type="tool_call_started",
                run_id=run_id,
                payload={"tool": tool_name, "input": _summarise(input_args)},
            )
            self._tool_starts[call_id] = time.monotonic()

        try:
            result = await handler(request)
        except Exception as exc:
            duration_ms = self._elapsed_ms(call_id)
            if recorder is not None and run_id is not None:
                self._safe_record(
                    recorder,
                    event_type="tool_call_failed",
                    run_id=run_id,
                    payload={"tool": tool_name, "error": str(exc)},
                )
                try:
                    recorder.record_tool_call(
                        run_id=run_id,
                        tool_name=tool_name,
                        input_args=_summarise(input_args),
                        status="error",
                        error=str(exc),
                        duration_ms=duration_ms,
                    )
                except Exception as audit_exc:  # noqa: BLE001
                    logger.debug("record_tool_call (error path) failed: %s", audit_exc)
            raise

        duration_ms = self._elapsed_ms(call_id)
        if recorder is not None and run_id is not None:
            output_text = (
                getattr(result, "content", None)
                if result is not None
                else None
            ) or str(result)
            self._safe_record(
                recorder,
                event_type="tool_call_completed",
                run_id=run_id,
                payload={"tool": tool_name, "output": output_text[:512]},
            )
            try:
                call_row_id = recorder.record_tool_call(
                    run_id=run_id,
                    tool_name=tool_name,
                    input_args=_summarise(input_args),
                    output=output_text,
                    status="completed",
                    duration_ms=duration_ms,
                )
                # Write role="tool" message for SFT/trajectory export
                # (parity with AuditCallbackPlugin.on_tool_end).
                try:
                    recorder.record_message(
                        run_id=run_id,
                        role="tool",
                        content=output_text,
                        tool_call_id=tool_call.get("id") or call_row_id,
                    )
                except Exception as msg_exc:  # noqa: BLE001
                    logger.debug("record_message (tool) failed: %s", msg_exc)
            except Exception as audit_exc:  # noqa: BLE001
                logger.debug("record_tool_call failed: %s", audit_exc)

        return result

    def _elapsed_ms(self, call_id: str) -> float | None:
        started = self._tool_starts.pop(call_id, None)
        if started is None:
            return None
        return (time.monotonic() - started) * 1000


def _summarise(value: Any, limit: int = 1024) -> str:
    """Truncate tool input for audit storage.

    The old callback recorded ``input_str`` raw.  With dict args we
    need a consistent serialisation that doesn't explode on
    non-JSON-serialisable objects.
    """
    if isinstance(value, str):
        text = value
    else:
        try:
            import json

            text = json.dumps(value, default=str, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            text = str(value)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


__all__ = ["AuditMiddleware"]
