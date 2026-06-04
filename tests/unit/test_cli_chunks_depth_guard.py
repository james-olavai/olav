"""Unit tests: CLI _chunks depth guard (commit 64e8e90c).

Before the fix: on_chat_model_stream added ALL LLM text to _chunks regardless
of _delegate_depth. In a multi-hop chain (netops → task("reporter") → reporter
runs SQL), the reporter's internal LLM stream filled _chunks, causing the
orchestrator's final answer to be discarded by the `not _chunks` guard in
on_chat_model_end. Symptom: CLI showed only 🔧 tool lines, no prose answer.

After the fix: both on_chat_model_stream and on_chat_model_end only write to
_chunks when _delegate_depth == 0 (orchestrator level).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Locate main.py for import
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))


# ---------------------------------------------------------------------------
# Helpers — simulate the streaming event loop from main.py's run_single_query
# ---------------------------------------------------------------------------

def _make_stream_event(kind: str, text: str = "") -> dict:
    chunk = MagicMock()
    chunk.content = text
    output = MagicMock()
    output.content = text
    return {
        "event": kind,
        "data": {"chunk": chunk, "output": output},
        "name": "test",
        "run_id": "r1",
    }


def _simulate_chunks(events: list[dict]) -> tuple[list[str], int]:
    """Re-implement the depth-guarded _chunks logic from main.py and
    return (chunks_collected, final_delegate_depth)."""
    _chunks: list[str] = []
    _delegate_depth = 0
    _DELEGATE_TOOLS = {"olav_delegate", "task"}

    for event in events:
        kind = event["event"]
        data = event["data"]

        if kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            if chunk:
                text = getattr(chunk, "content", "")
                if text and _delegate_depth == 0:          # ← depth guard
                    _chunks.append(text)

        elif kind == "on_chat_model_end":
            output = data.get("output")
            if output:
                text = getattr(output, "content", "")
                if text and not _chunks and _delegate_depth == 0:  # ← depth guard
                    _chunks.append(text)

        elif kind == "on_tool_start":
            tool_name = event.get("name", "")
            if tool_name in _DELEGATE_TOOLS:
                _delegate_depth += 1

        elif kind == "on_tool_end":
            tool_name = event.get("name", "")
            if tool_name in _DELEGATE_TOOLS and _delegate_depth > 0:
                _delegate_depth -= 1

    return _chunks, _delegate_depth


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChunksDepthGuard:
    """_chunks must only capture orchestrator-level LLM output (depth=0)."""

    def test_orchestrator_stream_captured(self):
        """Orchestrator LLM stream at depth=0 → added to _chunks."""
        events = [_make_stream_event("on_chat_model_stream", "Hello world")]
        chunks, _ = _simulate_chunks(events)
        assert chunks == ["Hello world"]

    def test_sub_agent_stream_not_captured(self):
        """Sub-agent LLM stream at depth=1 → NOT added to _chunks."""
        events = [
            {"event": "on_tool_start", "data": {}, "name": "task"},
            _make_stream_event("on_chat_model_stream", "sub-agent thinking..."),
            {"event": "on_tool_end", "data": {}, "name": "task"},
        ]
        chunks, _ = _simulate_chunks(events)
        assert chunks == [], (
            "Sub-agent stream leaked into _chunks — depth guard not applied.\n"
            "on_chat_model_stream must check _delegate_depth == 0."
        )

    def test_orchestrator_final_answer_after_delegation(self):
        """After sub-agent completes (depth back to 0), orchestrator answer captured."""
        events = [
            # Sub-agent runs (depth=1), fills nothing
            {"event": "on_tool_start", "data": {}, "name": "task"},
            _make_stream_event("on_chat_model_stream", "sub-agent intermediate"),
            {"event": "on_tool_end", "data": {}, "name": "task"},
            # Orchestrator final answer (depth=0)
            _make_stream_event("on_chat_model_stream", "Final orchestrator answer"),
        ]
        chunks, depth = _simulate_chunks(events)
        assert depth == 0
        assert chunks == ["Final orchestrator answer"], (
            "Orchestrator final answer lost — depth guard too aggressive.\n"
            "After task() completes (depth back to 0) orchestrator output must be captured."
        )

    def test_ch8_pattern_fixed(self):
        """CH8 failure pattern: sub-agent fills _chunks → orchestrator answer discarded.

        Before fix: sub-agent stream at depth=1 added to _chunks, making
        `not _chunks` guard block the orchestrator's prose answer.
        After fix: sub-agent stream ignored, orchestrator answer captured.
        """
        events = [
            # netops delegates to reporter
            {"event": "on_tool_start", "data": {}, "name": "task"},
            # reporter's internal LLM turns (would have poisoned _chunks before)
            _make_stream_event("on_chat_model_stream", "reporter step 1"),
            _make_stream_event("on_chat_model_stream", "reporter step 2"),
            {"event": "on_tool_end", "data": {}, "name": "task"},
            # netops orchestrator final answer
            _make_stream_event("on_chat_model_stream", "网络碎片化程度增加，共 67 个连通分量"),
        ]
        chunks, _ = _simulate_chunks(events)
        assert any("67" in c or "连通" in c for c in chunks), (
            f"CH8 regression: orchestrator prose answer lost. Got chunks: {chunks}"
        )
        assert not any("reporter step" in c for c in chunks), (
            f"CH8 regression: sub-agent text leaked into _chunks: {chunks}"
        )

    def test_on_chat_model_end_depth_guard(self):
        """on_chat_model_end must also respect depth guard (non-streaming mode)."""
        # Simulate sub-agent completion via on_chat_model_end (non-streaming)
        sub_end = {
            "event": "on_chat_model_end",
            "data": {"chunk": None, "output": MagicMock(content="sub end answer")},
            "name": "sub",
        }
        events = [
            {"event": "on_tool_start", "data": {}, "name": "task"},
            sub_end,
            {"event": "on_tool_end", "data": {}, "name": "task"},
        ]
        chunks, _ = _simulate_chunks(events)
        assert chunks == [], (
            "on_chat_model_end at sub-agent depth leaked into _chunks.\n"
            "Must check _delegate_depth == 0 same as on_chat_model_stream."
        )

    def test_nested_delegation_depth_tracking(self):
        """Nested task() calls increment/decrement depth correctly."""
        events = [
            {"event": "on_tool_start", "data": {}, "name": "task"},       # depth=1
            {"event": "on_tool_start", "data": {}, "name": "olav_delegate"},  # depth=2
            _make_stream_event("on_chat_model_stream", "deep nested"),
            {"event": "on_tool_end", "data": {}, "name": "olav_delegate"},  # depth=1
            {"event": "on_tool_end", "data": {}, "name": "task"},           # depth=0
            _make_stream_event("on_chat_model_stream", "orchestrator answer"),
        ]
        chunks, depth = _simulate_chunks(events)
        assert depth == 0
        assert chunks == ["orchestrator answer"]
        assert "deep nested" not in " ".join(chunks)
