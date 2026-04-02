"""Phase 4-3: Web/API server audit injection tests.

Verifies that stream_run() records audit events in audit.duckdb via
AuditEventRecorder with source_channel='api'.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def audit_db(tmp_path):
    return tmp_path / "server_audit.duckdb"


def _async_gen(items):
    """Helper: return an async generator from a list."""
    async def _gen():
        for item in items:
            yield item
    return _gen()


def test_stream_run_records_audit_events(audit_db, monkeypatch):
    """stream_run() must record run_start + user_input_received + run_end."""
    import asyncio

    from olav.core.audit_recorder import AuditEventRecorder

    original_init = AuditEventRecorder.__init__

    def patched_init(self, db_path=None, **kw):
        original_init(self, db_path=str(audit_db), **kw)

    monkeypatch.setattr(AuditEventRecorder, "__init__", patched_init)

    fake_events = [
        {"event": "on_chain_start", "data": {}},
        {"event": "on_chain_end", "data": {}},
    ]

    mock_graph = MagicMock()
    mock_graph.astream_events = MagicMock(return_value=_async_gen(fake_events))

    mock_agent = MagicMock()
    mock_agent.graph = mock_graph
    mock_agent.plugin_registry = MagicMock()
    mock_agent.plugin_registry.get_callback_plugins.return_value = []

    with patch("olav.api.server.get_agent", new_callable=AsyncMock, return_value=mock_agent):
        from olav.api.server import RunStreamRequest, stream_run

        body = RunStreamRequest(
            assistant_id="quick",
            input={"messages": [{"role": "human", "content": "show devices"}]},
        )

        async def _run():
            response = await stream_run("test-thread-id", body)
            # Drain the generator
            if hasattr(response, "body_iterator"):
                async for _ in response.body_iterator:
                    pass

        asyncio.run(_run())

    recorder = AuditEventRecorder()
    import duckdb
    with duckdb.connect(str(recorder._db_path)) as _c:
        runs = _c.execute("SELECT source_channel, status FROM audit_runs").fetchall()
    assert runs, "audit_runs must have at least one row after stream_run()"
    channels = {r[0] for r in runs}
    assert "api" in channels, f"source_channel 'api' not found; got {channels}"

    with duckdb.connect(str(recorder._db_path)) as _c:
        events = _c.execute("SELECT event_type FROM audit_events").fetchall()
    event_types = {r[0] for r in events}
    assert "user_input_received" in event_types, (
        f"'user_input_received' missing; found: {event_types}"
    )


def test_stream_run_injects_callbacks(audit_db, monkeypatch):
    """stream_run() must pass callbacks from plugin_registry into astream_events config."""
    import asyncio

    from olav.core.audit_recorder import AuditEventRecorder

    _orig_init = AuditEventRecorder.__init__

    def patched_init(self, db_path=None, **kw):
        _orig_init(self, db_path=str(audit_db), **kw)

    monkeypatch.setattr(AuditEventRecorder, "__init__", patched_init)

    captured_config = {}
    fake_cb = MagicMock()

    async def fake_astream_events(input_data, config, **kwargs):
        captured_config.update(config)
        return
        yield  # make it an async generator

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    mock_agent = MagicMock()
    mock_agent.graph = mock_graph
    mock_agent.plugin_registry = MagicMock()
    mock_agent.plugin_registry.get_callback_plugins.return_value = [fake_cb]

    with patch("olav.api.server.get_agent", new_callable=AsyncMock, return_value=mock_agent):
        from olav.api.server import RunStreamRequest, stream_run

        body = RunStreamRequest(
            assistant_id="quick",
            input={"messages": [{"role": "human", "content": "test"}]},
        )

        async def _run():
            response = await stream_run("thread-cb", body)
            if hasattr(response, "body_iterator"):
                async for _ in response.body_iterator:
                    pass

        asyncio.run(_run())

    assert "callbacks" in captured_config, (
        f"stream_run must inject 'callbacks' into astream_events config; got keys: "
        f"{list(captured_config.keys())}"
    )
    assert fake_cb in captured_config["callbacks"], (
        "Callback from plugin_registry must appear in config['callbacks']"
    )
