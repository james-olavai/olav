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
        self._recorder.record(
            event_type="tool_call_started",
            run_id=str(run_id),
            payload={"tool": tool_name, "input": input_str},
        )

    async def on_tool_end(
        self,
        output: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        self._recorder.record(
            event_type="tool_call_completed",
            run_id=str(run_id),
            payload={"output": str(output)[:512]},
        )

    async def on_tool_error(
        self,
        error: Exception | KeyboardInterrupt,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        self._recorder.record(
            event_type="tool_call_failed",
            run_id=str(run_id),
            payload={"error": str(error)},
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
        if tokens_in is None and tokens_out is None:
            return
        self._recorder.record(
            event_type="llm_usage",
            run_id=str(run_id),
            payload={
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "model": llm_output.get("model_name"),
            },
        )

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

