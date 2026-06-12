"""Tests for OperationalEventCapturePlugin (L1 of agentic memory growth).

Pins:
  * write-tool detection by name prefix (no @tool metadata required)
  * secret redaction before embed/write
  * idempotent on content hash (re-running same op doesn't duplicate)
  * read-only tools NOT captured
  * failed tool calls (status=error) NOT captured
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from olav.plugins.middleware.operational_event_capture import (
    OperationalEventCapturePlugin,
    _is_write_tool,
    _redact_value,
    _summarize_call,
    _content_hash,
)


# ─────────────────────────────────────────────────────────────────────────
# Helper: fake messages mimicking LangGraph state["messages"]
# ─────────────────────────────────────────────────────────────────────────


class _AIMsg:
    type = "ai"

    def __init__(self, tool_calls):
        self.content = ""
        self.tool_calls = tool_calls


class _ToolMsg:
    type = "tool"

    def __init__(self, name, content, tool_call_id="tcid_1"):
        self.name = name
        self.content = content
        self.tool_call_id = tool_call_id


# ─────────────────────────────────────────────────────────────────────────
# write-tool detection
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    ("register_service", True),
    ("deploy_and_push_lab", True),
    ("push_node_config", True),
    ("save_lab_config", True),
    ("save_profile", True),
    ("destroy_lab", True),
    ("write_workspace_file", True),
    ("tcf_record_lab_run", True),
    ("tcf_emit_from_sim", True),
    ("create_thing", True),
    ("update_x", True),
    ("delete_y", True),
    ("exec_on_node", True),
    ("format_and_export", True),  # demo7 Ch8 surfaced — "export" verb
    ("bulk_ingest", True),         # state change to DB
    ("stop_service", True),        # state change
    # Read-only / non-write — should NOT match
    ("execute_sql", False),
    ("read_file", False),
    ("list_profiles", False),
    ("api_request", False),  # only writes when method in WRITE_METHODS, but capture is at content level not name
    ("olav_recall_memory", False),
    ("database_introspection", False),
    ("test_map_query", False),
    ("", False),
])
def test_is_write_tool_classifies_correctly(name, expected):
    assert _is_write_tool(name) is expected


# ─────────────────────────────────────────────────────────────────────────
# Secret redaction
# ─────────────────────────────────────────────────────────────────────────


def test_redact_value_strips_token_field():
    args = {"endpoint": "http://x", "token": "sk-XXXX"}
    out = _redact_value(args)
    assert out["token"] == "<redacted>"
    assert out["endpoint"] == "http://x"


def test_redact_value_strips_nested_password():
    args = {"auth": {"password": "secret123", "user": "alice"}}
    out = _redact_value(args)
    assert out["auth"]["password"] == "<redacted>"
    assert out["auth"]["user"] == "alice"


def test_redact_value_lists_pass_through():
    args = {"endpoints": [{"api_key": "k"}, {"api_key": "k2"}]}
    out = _redact_value(args)
    assert all(e["api_key"] == "<redacted>" for e in out["endpoints"])


def test_redact_keys_match_substrings_case_insensitive():
    args = {"API_KEY": "x", "Bearer_Token": "y", "credential_blob": "z"}
    out = _redact_value(args)
    assert out["API_KEY"] == "<redacted>"
    assert out["Bearer_Token"] == "<redacted>"
    assert out["credential_blob"] == "<redacted>"


# ─────────────────────────────────────────────────────────────────────────
# Summary shape pinning
# ─────────────────────────────────────────────────────────────────────────


def test_summary_format_includes_tool_args_result():
    s = _summarize_call(
        "register_service",
        {"service": "x", "endpoint": "http://x"},
        {"status": "ok", "id": "svc-1"},
    )
    assert s.startswith("Action: register_service")
    assert "Args:" in s
    assert "Result:" in s
    assert "x" in s


def test_summary_redacts_secrets_in_args():
    s = _summarize_call(
        "register_service",
        {"service": "x", "auth": {"token": "sk-secret123"}},
        {"status": "ok"},
    )
    assert "sk-secret123" not in s
    assert "<redacted>" in s


def test_summary_truncates_long_results():
    huge = ["row"] * 10_000
    s = _summarize_call("save_profile", {"name": "x"}, huge)
    assert "(truncated)" in s
    assert len(s) < 2000


def test_content_hash_stable_for_same_input():
    s = _summarize_call("register_service", {"a": 1}, {"ok": True})
    assert _content_hash(s) == _content_hash(s)


def test_content_hash_changes_on_arg_change():
    s1 = _summarize_call("register_service", {"a": 1}, {"ok": True})
    s2 = _summarize_call("register_service", {"a": 2}, {"ok": True})
    assert _content_hash(s1) != _content_hash(s2)


# ─────────────────────────────────────────────────────────────────────────
# aafter_agent integration — full capture flow
# ─────────────────────────────────────────────────────────────────────────


def _run_aafter(plugin, state):
    return asyncio.run(plugin.aafter_agent(state, runtime=None))


def test_aafter_agent_captures_one_write_tool_call():
    plugin = OperationalEventCapturePlugin(scope="services")

    fake_store = MagicMock()
    fake_table = MagicMock()
    fake_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
    fake_store.get_table.return_value = fake_table
    plugin._store = fake_store

    with patch.object(plugin, "_embed", return_value=[0.0] * 768):
        state = {
            "messages": [
                _AIMsg(tool_calls=[{
                    "id": "tc1",
                    "name": "register_service",
                    "args": {"service": "influx", "kind": "influxdb"},
                }]),
                _ToolMsg("register_service", '{"status": "ok"}', tool_call_id="tc1"),
            ]
        }
        _run_aafter(plugin, state)

    assert fake_store.add_memory.call_count == 1
    call = fake_store.add_memory.call_args
    assert call.kwargs["category"] == "operational_event"
    assert call.kwargs["scope"] == "services"
    assert "register_service" in call.kwargs["text"]


def test_aafter_agent_skips_read_only_tools():
    plugin = OperationalEventCapturePlugin(scope="ops")
    fake_store = MagicMock()
    fake_store.get_table.return_value.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
    plugin._store = fake_store

    with patch.object(plugin, "_embed", return_value=[0.0] * 768):
        state = {
            "messages": [
                _AIMsg(tool_calls=[{
                    "id": "tc1",
                    "name": "execute_sql",
                    "args": {"query": "SELECT 1"},
                }]),
                _ToolMsg("execute_sql", '{"data": []}', tool_call_id="tc1"),
            ]
        }
        _run_aafter(plugin, state)

    fake_store.add_memory.assert_not_called()


def test_aafter_agent_skips_failed_tool_calls():
    plugin = OperationalEventCapturePlugin(scope="services")
    fake_store = MagicMock()
    fake_store.get_table.return_value.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
    plugin._store = fake_store

    with patch.object(plugin, "_embed", return_value=[0.0] * 768):
        state = {
            "messages": [
                _AIMsg(tool_calls=[{
                    "id": "tc1",
                    "name": "register_service",
                    "args": {"service": "x"},
                }]),
                _ToolMsg(
                    "register_service",
                    '{"status": "error", "reason": "name taken"}',
                    tool_call_id="tc1",
                ),
            ]
        }
        _run_aafter(plugin, state)

    fake_store.add_memory.assert_not_called()


def test_aafter_agent_idempotent_on_repeat_call():
    plugin = OperationalEventCapturePlugin(scope="services")

    # Pre-loaded existing hash from prior run
    pre_summary = _summarize_call(
        "register_service",
        {"service": "x", "kind": "influxdb"},
        {"status": "ok"},
    )
    pre_hash = _content_hash(pre_summary)

    fake_store = MagicMock()
    fake_table = MagicMock()
    import json as _json
    fake_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
        {"metadata": _json.dumps({"content_hash": pre_hash, "tool": "register_service"})}
    ]
    fake_store.get_table.return_value = fake_table
    plugin._store = fake_store

    with patch.object(plugin, "_embed", return_value=[0.0] * 768):
        state = {
            "messages": [
                _AIMsg(tool_calls=[{
                    "id": "tc1",
                    "name": "register_service",
                    "args": {"service": "x", "kind": "influxdb"},
                }]),
                _ToolMsg("register_service", '{"status": "ok"}', tool_call_id="tc1"),
            ]
        }
        _run_aafter(plugin, state)

    # Same op hash already in memory → no second write
    fake_store.add_memory.assert_not_called()


def test_aafter_agent_handles_no_messages():
    plugin = OperationalEventCapturePlugin(scope="x")
    plugin._store = MagicMock()
    _run_aafter(plugin, {})
    plugin._store.add_memory.assert_not_called()
