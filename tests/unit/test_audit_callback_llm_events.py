"""Phase 2 — LLM event coverage tests for AuditCallbackPlugin.

Verifies the three missing event types from log_rector.md §5.3:
  - ``llm_request_started``  (on_chat_model_start hook)
  - ``model_stream_delta``   (on_llm_new_token hook, plain text token)
  - ``reasoning_block``      (on_llm_new_token hook, thinking chunk)

Also verifies renamed tool events:
  - ``tool_call_completed``  (was tool_call_finished)
  - ``tool_call_failed``     (was tool_call_error)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from langchain_core.outputs import LLMResult


@pytest.fixture()
def audit_db(tmp_path: Path):
    return tmp_path / "llm_audit.duckdb"


def _make_recorder(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder
    return AuditEventRecorder(db_path=db_path)


def _make_plugin(db_path: Path):
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    recorder = _make_recorder(db_path)
    return AuditCallbackPlugin(recorder=recorder), recorder


# ---------------------------------------------------------------------------
# llm_request_started
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_chat_model_start_emits_llm_request_started(audit_db: Path):
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    await plugin.on_chat_model_start(
        serialized={"name": "gpt-4o", "id": ["openai", "gpt-4o"]},
        messages=[[]],
        run_id=run_id,
    )

    rows = recorder._conn.execute(
        "SELECT event_type, payload FROM audit_events"
    ).fetchall()
    assert rows, "No event written"
    event_type, payload_str = rows[0]
    assert event_type == "llm_request_started", f"Got {event_type}"
    payload = json.loads(payload_str)
    assert payload.get("model"), f"model missing in payload: {payload}"


# ---------------------------------------------------------------------------
# model_stream_delta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_llm_new_token_plain_emits_stream_delta(audit_db: Path):
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    await plugin.on_llm_new_token(token="Hello", run_id=run_id)

    rows = recorder._conn.execute(
        "SELECT event_type, payload FROM audit_events"
    ).fetchall()
    assert rows, "No event written"
    event_type, payload_str = rows[0]
    assert event_type == "model_stream_delta", f"Got {event_type}"
    payload = json.loads(payload_str)
    assert payload["token"] == "Hello"


@pytest.mark.asyncio
async def test_on_llm_new_token_empty_not_written(audit_db: Path):
    """Empty tokens (streaming gaps) must not produce event rows."""
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    await plugin.on_llm_new_token(token="", run_id=run_id)

    count = recorder._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 0, "Empty token should not produce an audit row"


# ---------------------------------------------------------------------------
# reasoning_block (Anthropic extended thinking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_llm_new_token_thinking_chunk_emits_reasoning_block(audit_db: Path):
    """When the chunk contains a 'thinking' type block the event must be
    ``reasoning_block``, not ``model_stream_delta``."""
    from unittest.mock import MagicMock

    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    # Simulate an Anthropic thinking chunk
    chunk = MagicMock()
    chunk.content = [{"type": "thinking", "thinking": "Let me analyze..."}]

    await plugin.on_llm_new_token(
        token="Let me analyze...",
        chunk=chunk,
        run_id=run_id,
    )

    rows = recorder._conn.execute(
        "SELECT event_type FROM audit_events"
    ).fetchall()
    assert rows, "No event written"
    assert rows[0][0] == "reasoning_block", f"Expected reasoning_block; got {rows[0][0]}"


# ---------------------------------------------------------------------------
# Renamed tool events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_tool_end_emits_tool_call_completed(audit_db: Path):
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    await plugin.on_tool_end(output="Interface up", run_id=run_id)

    rows = recorder._conn.execute(
        "SELECT event_type FROM audit_events"
    ).fetchall()
    assert rows[0][0] == "tool_call_completed", f"Got {rows[0][0]}"


@pytest.mark.asyncio
async def test_on_tool_error_emits_tool_call_failed(audit_db: Path):
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    await plugin.on_tool_error(error=RuntimeError("timeout"), run_id=run_id)

    rows = recorder._conn.execute(
        "SELECT event_type FROM audit_events"
    ).fetchall()
    assert rows[0][0] == "tool_call_failed", f"Got {rows[0][0]}"


# ---------------------------------------------------------------------------
# on_llm_end — llm_usage event (token accounting)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_llm_end_emits_llm_usage_openai_format(audit_db: Path):
    """OpenAI-style token_usage keys → llm_usage payload."""
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    response = LLMResult(
        generations=[[]],
        llm_output={
            "model_name": "gpt-4o",
            "token_usage": {
                "prompt_tokens": 42,
                "completion_tokens": 17,
            },
        },
    )

    await plugin.on_llm_end(response=response, run_id=run_id)

    rows = recorder._conn.execute(
        "SELECT event_type, payload FROM audit_events"
    ).fetchall()
    assert rows, "No event written"
    event_type, payload_str = rows[0]
    assert event_type == "llm_usage", f"Got {event_type}"
    payload = json.loads(payload_str)
    assert payload["tokens_in"] == 42, f"tokens_in wrong: {payload}"
    assert payload["tokens_out"] == 17, f"tokens_out wrong: {payload}"
    assert payload["model"] == "gpt-4o", f"model wrong: {payload}"


@pytest.mark.asyncio
async def test_on_llm_end_emits_llm_usage_anthropic_format(audit_db: Path):
    """Anthropic usage_metadata keys → llm_usage payload."""
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    response = LLMResult(
        generations=[[]],
        llm_output={
            "model_name": "claude-3-5-sonnet",
            "usage_metadata": {
                "input_tokens": 100,
                "output_tokens": 55,
            },
        },
    )

    await plugin.on_llm_end(response=response, run_id=run_id)

    rows = recorder._conn.execute(
        "SELECT event_type, payload FROM audit_events"
    ).fetchall()
    assert rows, "No event written"
    event_type, payload_str = rows[0]
    assert event_type == "llm_usage"
    payload = json.loads(payload_str)
    assert payload["tokens_in"] == 100
    assert payload["tokens_out"] == 55


@pytest.mark.asyncio
async def test_on_llm_end_no_usage_writes_no_event(audit_db: Path):
    """When llm_output has no usage data, no event should be recorded."""
    plugin, recorder = _make_plugin(audit_db)
    run_id = uuid.uuid4()

    response = LLMResult(generations=[[]], llm_output={"model_name": "mock"})

    await plugin.on_llm_end(response=response, run_id=run_id)

    count = recorder._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 0, "No usage data → no event expected"
