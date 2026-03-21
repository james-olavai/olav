"""AuditCallbackPlugin — LangChain AsyncCallbackHandler that audits tool events.

Writes to AuditEventRecorder without blocking the main agent execution path.

Covered hooks:
    Tool lifecycle:
        on_tool_start  → tool_call_started
        on_tool_end    → tool_call_completed
        on_tool_error  → tool_call_failed

    LLM / chat-model lifecycle:
        on_chat_model_start → llm_request_started
        on_llm_new_token    → model_stream_delta   (text tokens only)
        on_llm_end          → llm_usage            (tokens_in / tokens_out)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Union

from langchain_core.outputs import LLMResult

from olav.plugins.base import OLAVCallbackPlugin


class AuditCallbackPlugin(OLAVCallbackPlugin):
    """Callback plugin that records tool and LLM lifecycle events to the audit DB.

    Args:
        recorder: Optional ``AuditEventRecorder`` instance. Defaults to a
            new recorder backed by ``AUDIT_DB_PATH``.
    """

    name = "audit"
    description = "Audits tool call and LLM events to DuckDB"
    tags = ["builtin", "audit"]

    def __init__(self, recorder=None) -> None:
        super().__init__()
        if recorder is None:
            from olav.core.audit_recorder import AuditEventRecorder

            recorder = AuditEventRecorder()
        self._recorder = recorder
        self._tool_runs: dict[str, dict[str, Any]] = {}
        # Bound context set by CLI/API before each task execution
        self._bound_run_id: str | None = None
        self._bound_recorder = None
        # Track whether the system prompt has been recorded for the current run
        self._system_prompt_recorded: bool = False

    def bind_run(self, run_id: str, recorder) -> None:
        """Bind a top-level run_id and recorder before task execution.

        This ensures tool events and LLM responses are recorded under the
        same run_id used by the CLI/API, enabling dataset export joins.
        """
        self._bound_run_id = run_id
        self._bound_recorder = recorder
        self._system_prompt_recorded = False  # reset for each new run

    def unbind_run(self) -> None:
        """Clear the bound context after task execution completes."""
        self._bound_run_id = None
        self._bound_recorder = None
        self._system_prompt_recorded = False

    # ------------------------------------------------------------------
    # Tool hooks
    # ------------------------------------------------------------------

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "unknown")
        run_id_str = str(run_id)
        # `tool_call_id` is the LLM-assigned ID (e.g. "call_xxxxx") passed via
        # kwargs in LangChain ≥0.2 when the tool was triggered by a tool_calls
        # LLM response. Capturing it lets us link role="tool" messages back to
        # the correct assistant tool_calls entry by ID (OpenAI format).
        llm_tool_call_id: str | None = kwargs.get("tool_call_id")
        self._tool_runs[run_id_str] = {
            "tool_name": tool_name,
            "input_args": input_str,
            "start_time": time.monotonic(),
            "llm_tool_call_id": llm_tool_call_id,
        }
        self._recorder.record(
            event_type="tool_call_started",
            run_id=run_id_str,
            payload={"tool": tool_name, "input": input_str},
        )

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        # Newer LangChain versions may pass a ToolMessage object instead of a str.
        output_text: str = (
            output.content if hasattr(output, "content") else str(output)
        )
        run_id_str = str(run_id)
        self._recorder.record(
            event_type="tool_call_completed",
            run_id=run_id_str,
            payload={"output": output_text[:512]},
        )
        ctx = self._tool_runs.pop(run_id_str, None)
        if ctx:
            duration_ms = (time.monotonic() - ctx["start_time"]) * 1000
            # Use the bound top-level run_id (from CLI/API) when available
            # so tool records join the main audit run for dataset export.
            effective_run_id = self._bound_run_id or run_id_str
            effective_recorder = self._bound_recorder or self._recorder
            call_id = effective_recorder.record_tool_call(
                run_id=effective_run_id,
                tool_name=ctx["tool_name"],
                input_args=ctx["input_args"],
                output=output_text,
                status="completed",
                duration_ms=duration_ms,
            )
            # Also write role="tool" message so the full conversation
            # turn (assistant tool-call → tool result) appears in audit_messages
            # for SFT/trajectory dataset export.
            # Use the LLM-assigned call ID (OpenAI "call_xxxxx") as the
            # tool_call_id so it matches the id in the assistant's tool_calls
            # array — required for valid OpenAI-format SFT data.
            msg_tool_call_id = ctx.get("llm_tool_call_id") or call_id
            try:
                effective_recorder.record_message(
                    run_id=effective_run_id,
                    role="tool",
                    content=output_text,
                    tool_call_id=msg_tool_call_id,
                )
            except Exception:
                pass  # audit must never block execution

    async def on_tool_error(
        self,
        error: Exception | KeyboardInterrupt,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        run_id_str = str(run_id)
        self._recorder.record(
            event_type="tool_call_failed",
            run_id=run_id_str,
            payload={"error": str(error)},
        )
        ctx = self._tool_runs.pop(run_id_str, None)
        if ctx:
            duration_ms = (time.monotonic() - ctx["start_time"]) * 1000
            effective_run_id = self._bound_run_id or run_id_str
            effective_recorder = self._bound_recorder or self._recorder
            effective_recorder.record_tool_call(
                run_id=effective_run_id,
                tool_name=ctx["tool_name"],
                input_args=ctx["input_args"],
                status="error",
                error=str(error),
                duration_ms=duration_ms,
            )

    # ------------------------------------------------------------------
    # LLM / chat-model hooks
    # ------------------------------------------------------------------

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        model_name = serialized.get("name") or serialized.get("id", ["unknown"])[-1]
        self._recorder.record(
            event_type="llm_request_started",
            run_id=str(run_id),
            payload={"model": model_name},
        )
        # Capture the system prompt on the first LLM call of each bound run.
        # messages is list[list[BaseMessage]] (one list per batch input).
        if (
            self._bound_run_id
            and self._bound_recorder
            and not self._system_prompt_recorded
            and messages
            and messages[0]
        ):
            try:
                first_msg = messages[0][0]
                # LangChain message types: SystemMessage, HumanMessage, ...
                type_name = type(first_msg).__name__.lower()
                if "system" in type_name:
                    content = getattr(first_msg, "content", "") or ""
                    if content:
                        self._bound_recorder.record_message(
                            run_id=self._bound_run_id,
                            role="system",
                            content=str(content),
                        )
                        self._system_prompt_recorded = True
            except Exception:
                pass  # audit must never block execution

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        llm_output = response.llm_output or {}
        usage = llm_output.get("usage_metadata") or llm_output.get("token_usage") or {}
        tokens_in = usage.get("input_tokens") or usage.get("prompt_tokens")
        tokens_out = usage.get("output_tokens") or usage.get("completion_tokens")
        if tokens_in is not None or tokens_out is not None:
            self._recorder.record(
                event_type="llm_usage",
                run_id=str(run_id),
                payload={
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "model": llm_output.get("model_name"),
                },
            )

        # Record assistant message under the bound top-level run_id so the
        # response is captured in audit_messages for dataset export.
        if self._bound_run_id and self._bound_recorder:
            try:
                gen = (
                    response.generations[0][0]
                    if response.generations and response.generations[0]
                    else None
                )
                if gen is not None:
                    text = getattr(gen, "text", "") or ""
                    # Check for tool-call decisions on the underlying AIMessage.
                    # When the LLM replies with tool_calls, gen.text is empty.
                    msg_obj = getattr(gen, "message", None)
                    raw_tool_calls = getattr(msg_obj, "tool_calls", None) or []
                    if raw_tool_calls:
                        serialized_calls = json.dumps([
                            {
                                "id": tc.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": tc.get("name", ""),
                                    "arguments": json.dumps(tc.get("args", {})),
                                },
                            }
                            for tc in raw_tool_calls
                        ])
                        self._bound_recorder.record_message(
                            run_id=self._bound_run_id,
                            role="assistant",
                            content="",
                            tool_calls=serialized_calls,
                        )
                    elif text.strip():
                        # Pure text response (no tool calls)
                        self._bound_recorder.record_message(
                            run_id=self._bound_run_id,
                            role="assistant",
                            content=text,
                        )
            except Exception:
                pass  # audit must never block agent execution

    async def on_llm_new_token(
        self,
        token: str,
        *,
        chunk: Any = None,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        # Check if a reasoning/thinking chunk is attached (Anthropic extended thinking)
        is_reasoning = False
        if chunk is not None:
            content = getattr(chunk, "content", None)
            if isinstance(content, list):
                is_reasoning = any(
                    isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")
                    for b in content
                )
            elif isinstance(content, dict):
                is_reasoning = content.get("type") in ("thinking", "redacted_thinking")

        event_type = "reasoning_block" if is_reasoning else "model_stream_delta"
        if token:
            self._recorder.record(
                event_type=event_type,
                run_id=str(run_id),
                payload={"token": token},
            )
