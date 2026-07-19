"""ToolLoopBreakerMiddleware — deterministic circuit breaker for tool-call loops.

ISSUE-NO-TOOL-CALL-CIRCUIT-BREAKER (dev_docs/00, 2026-07-19): a gemma4-31b
tool-call emission got corrupted (channel markup leaked into a glob pattern
arg) and the agent retried the SAME failing call 59 times, snowballing the
error messages into a 16M-token request that killed the run. Nothing at the
agent-graph level guarded against consecutive identical failing calls (the
only circuit breaker in the repo lives inside execute_cli_parallel).

Zero-LLM, two-stage containment:

1. **Short-circuit** (``wrap_tool_call``): after ``max_consecutive_failures``
   identical (tool, args) failures, stop EXECUTING the call — return a small
   instructive error ToolMessage instead. No side effects, no payload growth.
2. **Hard stop** (``before_model``): if the model ignores the breaker and
   keeps repeating past ``hard_abort_after`` attempts, jump the graph to
   ``end`` with an honest partial-result message — a clean bounded failure
   instead of a context-explosion crash.

Counting is per-signature (tool name + canonical args JSON), so failures
interleaved with other successful calls are still caught. State resets at
the start of every agent run (``before_agent``) — compiled agents are
long-lived process objects and a tripped breaker must never poison the
next run.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage

logger = logging.getLogger(__name__)

_BREAKER_MSG = (
    "⛔ circuit breaker: this exact {tool} call has now failed {n} times in a "
    "row and was NOT executed. Do NOT repeat this call. Fix the arguments, use "
    "a different tool, or finish with the results you already have."
)

_ABORT_MSG = (
    "Run stopped by the tool-loop circuit breaker: the agent repeated an "
    "identical failing `{tool}` call {n} times. Results gathered before the "
    "loop are above; treat this answer as partial."
)


class ToolLoopBreakerMiddleware(AgentMiddleware):
    """Break consecutive identical failing tool calls (see module docstring)."""

    def __init__(
        self,
        agent_name: str = "",
        max_consecutive_failures: int = 3,
        hard_abort_after: int = 6,
    ) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.max_consecutive_failures = max_consecutive_failures
        self.hard_abort_after = hard_abort_after
        self._fail_counts: dict[str, int] = {}
        self._tripped_sig: str | None = None

    # ── per-run state hygiene ─────────────────────────────────────────────
    def _reset(self) -> None:
        self._fail_counts.clear()
        self._tripped_sig = None

    def before_agent(self, state: Any, runtime: Any) -> None:  # noqa: ARG002
        self._reset()

    async def abefore_agent(self, state: Any, runtime: Any) -> None:  # noqa: ARG002
        self._reset()

    # ── signature + accounting ────────────────────────────────────────────
    @staticmethod
    def _sig(request: Any) -> str:
        call = request.tool_call
        try:
            args = json.dumps(call.get("args", {}), sort_keys=True, default=str)
        except Exception:  # noqa: BLE001 — unserialisable args still get a key
            args = repr(call.get("args"))
        return f"{call.get('name', '?')}::{args[:2000]}"

    @staticmethod
    def _is_error(result: Any) -> bool:
        if not isinstance(result, ToolMessage):
            return False
        if result.status == "error":
            return True
        # ISSUE-LOOP-BREAKER-ENVELOPE-BLIND: execute_skill_script (and other
        # envelope-returning tools) report failures as SUCCESSFUL ToolMessages
        # whose content is a JSON envelope {"status": "error", ...} — an agent
        # repeating such a call every few seconds was invisible to the breaker.
        # Conservative sniff of the content head only: a leading JSON-ish blob
        # that declares status=error. Plain prose mentioning the word "error"
        # never matches.
        content = result.content
        if isinstance(content, str):
            head = content[:300]
            if '"status": "error"' in head or "'status': 'error'" in head:
                return True
        return False

    def _short_circuit(self, request: Any, sig: str) -> ToolMessage | None:
        """Return the breaker ToolMessage when *sig* is over the limit."""
        n = self._fail_counts.get(sig, 0)
        if n < self.max_consecutive_failures:
            return None
        self._fail_counts[sig] = n + 1
        if n + 1 >= self.hard_abort_after:
            self._tripped_sig = sig
        call = request.tool_call
        tool_name = call.get("name", "?")
        logger.warning(
            "[%s] tool-loop breaker: %s blocked (%d consecutive failures)",
            self.agent_name, tool_name, n + 1,
        )
        return ToolMessage(
            content=_BREAKER_MSG.format(tool=tool_name, n=n + 1),
            tool_call_id=call.get("id", ""),
            name=tool_name,
            status="error",
        )

    def _record(self, sig: str, result: Any) -> None:
        if self._is_error(result):
            self._fail_counts[sig] = self._fail_counts.get(sig, 0) + 1
        else:
            self._fail_counts.pop(sig, None)

    # ── stage 1: short-circuit the tool execution ─────────────────────────
    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        sig = self._sig(request)
        blocked = self._short_circuit(request, sig)
        if blocked is not None:
            return blocked
        result = handler(request)
        self._record(sig, result)
        return result

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        sig = self._sig(request)
        blocked = self._short_circuit(request, sig)
        if blocked is not None:
            return blocked
        result = await handler(request)
        self._record(sig, result)
        return result

    # ── stage 2: hard stop when the model ignores the breaker ────────────
    def _abort_update(self) -> dict[str, Any] | None:
        if self._tripped_sig is None:
            return None
        tool = self._tripped_sig.split("::", 1)[0]
        n = self._fail_counts.get(self._tripped_sig, self.hard_abort_after)
        logger.error(
            "[%s] tool-loop breaker HARD STOP: %s repeated %d times — ending run",
            self.agent_name, tool, n,
        )
        sig = self._tripped_sig
        self._reset()  # never poison a later run sharing this compiled agent
        del sig
        return {
            "messages": [AIMessage(content=_ABORT_MSG.format(tool=tool, n=n))],
            "jump_to": "end",
        }

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        return self._abort_update()

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        return self._abort_update()
