"""Phase 3-3 TDD: AuditCallbackPlugin — LangChain callback that writes to AuditEventRecorder."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def recorder(tmp_path):
    from olav.core.audit_recorder import AuditEventRecorder

    r = AuditEventRecorder(db_path=tmp_path / "audit.duckdb")
    yield r
    r.close()


def test_audit_callback_plugin_importable():
    from olav.plugins.callbacks.audit import AuditCallbackPlugin  # noqa: F401


def test_audit_callback_plugin_is_callback_plugin():
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from olav.plugins.base import OLAVCallbackPlugin

    assert issubclass(AuditCallbackPlugin, OLAVCallbackPlugin)


@pytest.mark.anyio
async def test_on_tool_start_records_event(tmp_path):
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from olav.core.audit_recorder import AuditEventRecorder
    import duckdb

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    plugin = AuditCallbackPlugin(recorder=recorder)

    run_id = str(uuid.uuid4())
    await plugin.on_tool_start(
        serialized={"name": "show_interfaces"},
        input_str="GigabitEthernet0/0",
        run_id=uuid.UUID(run_id),
    )
    recorder.close()

    conn = duckdb.connect(str(db))
    rows = conn.execute("SELECT event_type FROM audit_events WHERE run_id = ?", [run_id]).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "tool_call_started"


@pytest.mark.anyio
async def test_on_tool_end_records_event(tmp_path):
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from olav.core.audit_recorder import AuditEventRecorder
    import duckdb

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    plugin = AuditCallbackPlugin(recorder=recorder)

    run_id = str(uuid.uuid4())
    await plugin.on_tool_end(
        output="GigabitEthernet0/0 is up",
        run_id=uuid.UUID(run_id),
    )
    recorder.close()

    conn = duckdb.connect(str(db))
    rows = conn.execute("SELECT event_type FROM audit_events WHERE run_id = ?", [run_id]).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "tool_call_completed"


@pytest.mark.anyio
async def test_on_tool_error_records_event(tmp_path):
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from olav.core.audit_recorder import AuditEventRecorder
    import duckdb

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    plugin = AuditCallbackPlugin(recorder=recorder)

    run_id = str(uuid.uuid4())
    await plugin.on_tool_error(
        error=ValueError("connection refused"),
        run_id=uuid.UUID(run_id),
    )
    recorder.close()

    conn = duckdb.connect(str(db))
    rows = conn.execute("SELECT event_type FROM audit_events WHERE run_id = ?", [run_id]).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "tool_call_failed"


@pytest.mark.anyio
async def test_on_tool_end_calls_record_tool_call():
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    mock_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=mock_recorder)

    run_id = uuid.uuid4()

    await plugin.on_tool_start(
        serialized={"name": "show_interfaces"},
        input_str="GigabitEthernet0/0",
        run_id=run_id,
    )

    await plugin.on_tool_end(
        output="GigabitEthernet0/0 is up",
        run_id=run_id,
    )

    mock_recorder.record_tool_call.assert_called_once()
    call_kwargs = mock_recorder.record_tool_call.call_args
    assert call_kwargs.kwargs["tool_name"] == "show_interfaces"
    assert call_kwargs.kwargs["input_args"] == "GigabitEthernet0/0"
    assert call_kwargs.kwargs["output"] == "GigabitEthernet0/0 is up"
    assert call_kwargs.kwargs["status"] == "completed"
    assert call_kwargs.kwargs["run_id"] == str(run_id)
    assert "duration_ms" in call_kwargs.kwargs


@pytest.mark.anyio
async def test_on_tool_error_calls_record_tool_call_with_error():
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    mock_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=mock_recorder)

    run_id = uuid.uuid4()

    await plugin.on_tool_start(
        serialized={"name": "ping_device"},
        input_str="192.168.1.1",
        run_id=run_id,
    )

    err = ValueError("connection refused")
    await plugin.on_tool_error(error=err, run_id=run_id)

    mock_recorder.record_tool_call.assert_called_once()
    call_kwargs = mock_recorder.record_tool_call.call_args
    assert call_kwargs.kwargs["tool_name"] == "ping_device"
    assert call_kwargs.kwargs["input_args"] == "192.168.1.1"
    assert call_kwargs.kwargs["status"] == "error"
    assert call_kwargs.kwargs["error"] == "connection refused"
    assert call_kwargs.kwargs["run_id"] == str(run_id)
    assert "duration_ms" in call_kwargs.kwargs


@pytest.mark.anyio
async def test_duration_ms_is_positive():
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    import asyncio as _asyncio

    mock_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=mock_recorder)

    run_id = uuid.uuid4()

    await plugin.on_tool_start(
        serialized={"name": "slow_tool"},
        input_str="arg",
        run_id=run_id,
    )
    await _asyncio.sleep(0.01)  # ~10ms
    await plugin.on_tool_end(output="done", run_id=run_id)

    call_kwargs = mock_recorder.record_tool_call.call_args
    duration = call_kwargs.kwargs["duration_ms"]
    assert isinstance(duration, float)
    assert duration > 0


@pytest.mark.anyio
async def test_tool_context_cleaned_up_after_end_and_error():
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    mock_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=mock_recorder)

    rid1 = uuid.uuid4()
    await plugin.on_tool_start(serialized={"name": "t1"}, input_str="a", run_id=rid1)
    assert str(rid1) in plugin._tool_runs
    await plugin.on_tool_end(output="ok", run_id=rid1)
    assert str(rid1) not in plugin._tool_runs

    rid2 = uuid.uuid4()
    await plugin.on_tool_start(serialized={"name": "t2"}, input_str="b", run_id=rid2)
    assert str(rid2) in plugin._tool_runs
    await plugin.on_tool_error(error=RuntimeError("boom"), run_id=rid2)
    assert str(rid2) not in plugin._tool_runs


def test_audit_callback_plugin_loaded_by_registry():
    """load_builtin_plugins() must include an AuditCallbackPlugin instance."""
    from olav.plugins.registry import PluginRegistry
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    # load_builtin_plugins scans callbacks/ — import to trigger registration side-effect
    import importlib
    import olav.plugins.callbacks.audit  # noqa: F401

    registry = PluginRegistry()
    plugin = AuditCallbackPlugin()
    registry.register(plugin)

    cbs = registry.get_callback_plugins()
    assert any(isinstance(p, AuditCallbackPlugin) for p in cbs)


# ---------------------------------------------------------------------------
# DATA-1: bind_run → record_tool_call uses bound run_id & recorder
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bind_run_tool_end_uses_bound_run_id():
    """When bind_run() is active, record_tool_call must use the bound run_id."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    default_recorder = MagicMock()
    bound_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=default_recorder)

    bound_run_id = "top-level-run-001"
    plugin.bind_run(bound_run_id, bound_recorder)

    child_run_id = uuid.uuid4()
    await plugin.on_tool_start(
        serialized={"name": "show_route"},
        input_str="0.0.0.0/0",
        run_id=child_run_id,
    )
    await plugin.on_tool_end(output="default via 10.0.0.1", run_id=child_run_id)

    # record_tool_call must be called on the BOUND recorder, not the default
    bound_recorder.record_tool_call.assert_called_once()
    default_recorder.record_tool_call.assert_not_called()
    call_kw = bound_recorder.record_tool_call.call_args.kwargs
    assert call_kw["run_id"] == bound_run_id, (
        f"Expected bound run_id {bound_run_id}, got {call_kw['run_id']}"
    )
    assert call_kw["tool_name"] == "show_route"


@pytest.mark.anyio
async def test_no_bind_run_tool_end_uses_child_run_id():
    """Without bind_run(), record_tool_call must use child run_id on default recorder."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    mock_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=mock_recorder)

    child_run_id = uuid.uuid4()
    await plugin.on_tool_start(
        serialized={"name": "ping_host"},
        input_str="192.168.1.1",
        run_id=child_run_id,
    )
    await plugin.on_tool_end(output="64 bytes", run_id=child_run_id)

    mock_recorder.record_tool_call.assert_called_once()
    call_kw = mock_recorder.record_tool_call.call_args.kwargs
    assert call_kw["run_id"] == str(child_run_id)


@pytest.mark.anyio
async def test_bind_run_tool_error_uses_bound_run_id():
    """When bind_run() is active, on_tool_error must use the bound run_id."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    default_recorder = MagicMock()
    bound_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=default_recorder)

    bound_run_id = "top-level-run-002"
    plugin.bind_run(bound_run_id, bound_recorder)

    child_run_id = uuid.uuid4()
    await plugin.on_tool_start(
        serialized={"name": "ssh_connect"},
        input_str="10.0.0.1",
        run_id=child_run_id,
    )
    await plugin.on_tool_error(error=ConnectionError("refused"), run_id=child_run_id)

    bound_recorder.record_tool_call.assert_called_once()
    default_recorder.record_tool_call.assert_not_called()
    call_kw = bound_recorder.record_tool_call.call_args.kwargs
    assert call_kw["run_id"] == bound_run_id
    assert call_kw["status"] == "error"


@pytest.mark.anyio
async def test_unbind_run_reverts_to_child_run_id():
    """After unbind_run(), tool calls should go back to child run_id."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    default_recorder = MagicMock()
    bound_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=default_recorder)

    plugin.bind_run("top-level-run-003", bound_recorder)
    plugin.unbind_run()

    child_run_id = uuid.uuid4()
    await plugin.on_tool_start(
        serialized={"name": "show_version"},
        input_str="",
        run_id=child_run_id,
    )
    await plugin.on_tool_end(output="IOS-XE 17.3", run_id=child_run_id)

    default_recorder.record_tool_call.assert_called_once()
    bound_recorder.record_tool_call.assert_not_called()
    call_kw = default_recorder.record_tool_call.call_args.kwargs
    assert call_kw["run_id"] == str(child_run_id)


# ---------------------------------------------------------------------------
# AUDIT-3: on_llm_end records assistant message when bound
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_on_llm_end_records_assistant_message_when_bound():
    """When bind_run is active, on_llm_end must call record_message(role='assistant')."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from langchain_core.outputs import LLMResult, Generation

    default_recorder = MagicMock()
    bound_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=default_recorder)

    bound_run_id = "top-level-run-004"
    plugin.bind_run(bound_run_id, bound_recorder)

    response = LLMResult(
        generations=[[Generation(text="The BGP session is established.")]],
        llm_output={
            "model_name": "gpt-4o",
            "usage_metadata": {"input_tokens": 50, "output_tokens": 12},
        },
    )
    await plugin.on_llm_end(response=response, run_id=uuid.uuid4())

    bound_recorder.record_message.assert_called_once()
    call_kw = bound_recorder.record_message.call_args.kwargs
    assert call_kw["run_id"] == bound_run_id
    assert call_kw["role"] == "assistant"
    assert "BGP session" in call_kw["content"]


@pytest.mark.anyio
async def test_on_llm_end_no_message_when_not_bound():
    """Without bind_run, on_llm_end must NOT call record_message."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from langchain_core.outputs import LLMResult, Generation

    mock_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=mock_recorder)

    response = LLMResult(
        generations=[[Generation(text="Some output")]],
        llm_output={
            "model_name": "gpt-4o",
            "usage_metadata": {"input_tokens": 10, "output_tokens": 5},
        },
    )
    await plugin.on_llm_end(response=response, run_id=uuid.uuid4())

    mock_recorder.record_message.assert_not_called()


@pytest.mark.anyio
async def test_on_llm_end_skips_empty_text_message():
    """When LLM returns empty text (tool-call-only), no message should be recorded."""
    from olav.plugins.callbacks.audit import AuditCallbackPlugin
    from langchain_core.outputs import LLMResult, Generation

    bound_recorder = MagicMock()
    plugin = AuditCallbackPlugin(recorder=MagicMock())
    plugin.bind_run("run-005", bound_recorder)

    response = LLMResult(
        generations=[[Generation(text="")]],
        llm_output={
            "usage_metadata": {"input_tokens": 10, "output_tokens": 0},
        },
    )
    await plugin.on_llm_end(response=response, run_id=uuid.uuid4())

    bound_recorder.record_message.assert_not_called()
