"""Gap-C / Phase 3-4 TDD: CLI must record run_id and user_input_received events."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


async def _empty_stream(*args, **kwargs):
    """Async generator that yields nothing — simulates an agent with no output."""
    return
    yield  # makes it an async generator


@pytest.mark.anyio
async def test_run_single_query_records_run_start(tmp_path):
    """run_single_query() must call record_run_start() before invoking the agent."""
    recorder_calls = []

    class FakeRecorder:
        def record_run_start(self, run_id, **kwargs):
            recorder_calls.append(("run_start", run_id, kwargs))

        def record(self, event_type, run_id=None, **kwargs):
            recorder_calls.append(("record", event_type, run_id, kwargs))

        def record_run_end(self, run_id, **kwargs):
            recorder_calls.append(("run_end", run_id, kwargs))

        def record_message(self, run_id=None, *, role, content, **kwargs):
            recorder_calls.append(("message", role, run_id))

        def close(self):
            pass

    fake_agent = MagicMock()
    fake_agent.plugin_registry = MagicMock()
    fake_agent.plugin_registry.get_callback_plugins.return_value = []
    fake_agent.graph.astream_events = _empty_stream

    with (
        patch("olav.cli.main.create_olav_agent_with_backend", return_value=(fake_agent, "backend")),
        patch("olav.cli.main._get_auth_mode", return_value="none"),
        patch("olav.cli.main.AuditEventRecorder", return_value=FakeRecorder()),
    ):
        from olav.cli.main import run_single_query

        await run_single_query("show bgp summary", assistant_id="ops")

    event_types = [c[0] for c in recorder_calls]
    assert "run_start" in event_types, f"record_run_start not called. Got: {recorder_calls}"


@pytest.mark.anyio
async def test_run_single_query_records_user_input_received(tmp_path):
    """run_single_query() must record event_type='user_input_received'."""
    recorder_calls = []

    class FakeRecorder:
        def record_run_start(self, run_id, **kwargs):
            recorder_calls.append(("run_start", run_id))

        def record(self, event_type, run_id=None, **kwargs):
            recorder_calls.append(("record", event_type))

        def record_run_end(self, run_id, **kwargs):
            pass

        def record_message(self, run_id=None, *, role, content, **kwargs):
            pass

        def close(self):
            pass

    fake_agent = MagicMock()
    fake_agent.plugin_registry = MagicMock()
    fake_agent.plugin_registry.get_callback_plugins.return_value = []
    fake_agent.graph.astream_events = _empty_stream

    with (
        patch("olav.cli.main.create_olav_agent_with_backend", return_value=(fake_agent, "backend")),
        patch("olav.cli.main._get_auth_mode", return_value="none"),
        patch("olav.cli.main.AuditEventRecorder", return_value=FakeRecorder()),
    ):
        from olav.cli.main import run_single_query

        await run_single_query("show bgp summary", assistant_id="ops")

    recorded_events = [c[1] for c in recorder_calls if c[0] == "record"]
    assert "user_input_received" in recorded_events, (
        f"user_input_received event not recorded. Events: {recorded_events}"
    )


@pytest.mark.anyio
async def test_run_single_query_records_user_message(tmp_path):
    recorder_calls = []

    class FakeRecorder:
        def record_run_start(self, run_id, **kwargs):
            pass

        def record(self, event_type, run_id=None, **kwargs):
            pass

        def record_message(self, run_id=None, *, role, content, **kwargs):
            recorder_calls.append(("message", role, content))

        def record_run_end(self, run_id, **kwargs):
            pass

        def close(self):
            pass

    fake_agent = MagicMock()
    fake_agent.plugin_registry = MagicMock()
    fake_agent.plugin_registry.get_callback_plugins.return_value = []
    fake_agent.graph.astream_events = _empty_stream

    with (
        patch(
            "olav.cli.main.create_olav_agent_with_backend",
            return_value=(fake_agent, "backend"),
        ),
        patch("olav.cli.main._get_auth_mode", return_value="none"),
        patch("olav.cli.main.AuditEventRecorder", return_value=FakeRecorder()),
    ):
        from olav.cli.main import run_single_query

        await run_single_query("show bgp summary", assistant_id="ops")

    user_messages = [c for c in recorder_calls if c[1] == "user"]
    assert user_messages, f"record_message(role='user') not called. Got: {recorder_calls}"
    assert user_messages[0][2] == "show bgp summary"
