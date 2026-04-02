"""Tests for OLAVSafetyMiddleware — conditional HITL gate."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from olav.plugins.middleware.safety import (
    OLAVSafetyMiddleware,
    _PROJECT_ROOT,
    _check_execute,
    _check_write_file,
)


# ---------------------------------------------------------------------------
# Unit: classification helpers
# ---------------------------------------------------------------------------

class TestCheckWriteFile:
    def test_safe_relative_path(self):
        dangerous, _ = _check_write_file(".olav/services/netbox/docker-compose.yml")
        assert not dangerous

    def test_safe_absolute_within_project(self):
        path = str(_PROJECT_ROOT / ".olav/services/netbox/docker-compose.yml")
        dangerous, _ = _check_write_file(path)
        assert not dangerous

    def test_dangerous_tmp(self):
        dangerous, reason = _check_write_file("/tmp/netbox/docker-compose.yml")
        assert dangerous
        assert "project root" in reason

    def test_dangerous_etc(self):
        dangerous, reason = _check_write_file("/etc/passwd")
        assert dangerous
        assert "blocked" in reason

    def test_dangerous_usr(self):
        dangerous, _ = _check_write_file("/usr/local/bin/evil")
        assert dangerous

    def test_empty_path_is_safe(self):
        dangerous, _ = _check_write_file("")
        assert not dangerous


class TestCheckExecute:
    def test_safe_docker_compose(self):
        dangerous, _ = _check_execute("docker compose up -d")
        assert not dangerous

    def test_safe_curl(self):
        dangerous, _ = _check_execute("curl -s http://localhost:8000/api/")
        assert not dangerous

    def test_dangerous_rm_rf(self):
        dangerous, reason = _check_execute("rm -rf /home")
        assert dangerous
        assert "rm -rf" in reason

    def test_dangerous_mkfs(self):
        dangerous, reason = _check_execute("mkfs.ext4 /dev/sda1")
        assert dangerous

    def test_dangerous_dd(self):
        dangerous, _ = _check_execute("dd if=/dev/zero of=/dev/sda")
        assert dangerous

    def test_case_insensitive(self):
        dangerous, _ = _check_execute("RM -RF /tmp/data")
        assert dangerous


# ---------------------------------------------------------------------------
# Integration: after_model gating
# ---------------------------------------------------------------------------

class TestAfterModel:
    def _make_state(self, tool_calls: list[dict]) -> dict:
        """Build minimal agent state with one AIMessage containing tool_calls."""
        tc_objects = [
            MagicMock(
                spec=dict,
                **{"__getitem__.side_effect": lambda k, tc=tc: tc[k],
                   "get": lambda k, d=None, tc=tc: tc.get(k, d),
                   "__contains__": lambda k, tc=tc: k in tc,
                   "name": tc["name"],
                   "id": tc["id"]},
            )
            for tc in tool_calls
        ]
        # Use real ToolCall-like dicts via AIMessage
        msg = AIMessage(content="", tool_calls=tool_calls)
        return {"messages": [msg]}

    def test_no_watched_tools_no_interrupt(self):
        """execute_sql is not watched — should pass through."""
        mw = OLAVSafetyMiddleware()
        state = self._make_state([
            {"name": "execute_sql", "args": {"sql": "SELECT 1"}, "id": "t1", "type": "tool_call"}
        ])
        result = mw.after_model(state, MagicMock())
        assert result is None

    def test_safe_write_file_no_interrupt(self):
        """write_file within project root — no interrupt."""
        mw = OLAVSafetyMiddleware()
        state = self._make_state([
            {"name": "write_file", "args": {"path": ".olav/services/netbox/docker-compose.yml"}, "id": "t1", "type": "tool_call"}
        ])
        result = mw.after_model(state, MagicMock())
        assert result is None

    def test_dangerous_write_file_triggers_interrupt(self):
        """write_file outside project root — must interrupt."""
        mw = OLAVSafetyMiddleware()
        state = self._make_state([
            {"name": "write_file", "args": {"path": "/tmp/netbox/docker-compose.yml"}, "id": "t1", "type": "tool_call"}
        ])

        approved_response = {"decisions": [{"type": "approve"}]}

        with patch("olav.plugins.middleware.safety.interrupt", return_value=approved_response) as mock_interrupt:
            result = mw.after_model(state, MagicMock())

        mock_interrupt.assert_called_once()
        hitl_req = mock_interrupt.call_args[0][0]
        assert hitl_req["action_requests"][0]["name"] == "write_file"
        assert "/tmp/" in hitl_req["action_requests"][0]["description"]

    def test_dangerous_execute_triggers_interrupt(self):
        """execute with rm -rf — must interrupt."""
        mw = OLAVSafetyMiddleware()
        state = self._make_state([
            {"name": "execute", "args": {"command": "rm -rf /tmp/netbox"}, "id": "t2", "type": "tool_call"}
        ])
        approved = {"decisions": [{"type": "approve"}]}

        with patch("olav.plugins.middleware.safety.interrupt", return_value=approved) as mock_interrupt:
            result = mw.after_model(state, MagicMock())

        mock_interrupt.assert_called_once()
        req = mock_interrupt.call_args[0][0]
        assert "rm -rf" in req["action_requests"][0]["description"]

    def test_approve_keeps_original_tool_call(self):
        """Approving preserves the original tool call in the message."""
        mw = OLAVSafetyMiddleware()
        state = self._make_state([
            {"name": "write_file", "args": {"path": "/tmp/bad.yml"}, "id": "t1", "type": "tool_call"}
        ])
        approved = {"decisions": [{"type": "approve"}]}

        with patch("olav.plugins.middleware.safety.interrupt", return_value=approved):
            result = mw.after_model(state, MagicMock())

        assert result is not None
        ai_msg = result["messages"][0]
        assert len(ai_msg.tool_calls) == 1
        assert ai_msg.tool_calls[0]["args"]["path"] == "/tmp/bad.yml"

    def test_reject_produces_error_tool_message(self):
        """Rejecting produces a ToolMessage with status=error."""
        mw = OLAVSafetyMiddleware()
        state = self._make_state([
            {"name": "write_file", "args": {"path": "/tmp/bad.yml"}, "id": "t1", "type": "tool_call"}
        ])
        rejected = {"decisions": [{"type": "reject", "message": "Not allowed outside project"}]}

        with patch("olav.plugins.middleware.safety.interrupt", return_value=rejected):
            result = mw.after_model(state, MagicMock())

        assert result is not None
        messages = result["messages"]
        ai_msg = messages[0]
        assert ai_msg.tool_calls == []  # rejected → removed from tool calls
        error_msg = messages[1]
        assert error_msg.status == "error"
        assert "Not allowed" in error_msg.content

    def test_mixed_batch_only_dangerous_interrupted(self):
        """Batch with one safe + one dangerous call — only dangerous is interrupted."""
        mw = OLAVSafetyMiddleware()
        state = self._make_state([
            {"name": "execute_sql", "args": {"sql": "SELECT 1"}, "id": "t1", "type": "tool_call"},
            {"name": "write_file", "args": {"path": "/tmp/bad.yml"}, "id": "t2", "type": "tool_call"},
        ])
        approved = {"decisions": [{"type": "approve"}]}

        with patch("olav.plugins.middleware.safety.interrupt", return_value=approved) as mock_interrupt:
            result = mw.after_model(state, MagicMock())

        # Only 1 interrupt for write_file, execute_sql passes through
        mock_interrupt.assert_called_once()
        req = mock_interrupt.call_args[0][0]
        assert len(req["action_requests"]) == 1
        assert req["action_requests"][0]["name"] == "write_file"

        # Both tool calls preserved (execute_sql untouched, write_file approved)
        ai_msg = result["messages"][0]
        assert len(ai_msg.tool_calls) == 2

    def test_no_messages_returns_none(self):
        mw = OLAVSafetyMiddleware()
        assert mw.after_model({"messages": []}, MagicMock()) is None

    def test_plugin_registered_by_load_builtin(self):
        """OLAVSafetyMiddleware is auto-discovered by load_builtin_plugins."""
        from olav.plugins import load_builtin_plugins
        from olav.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        load_builtin_plugins(registry)
        middleware_names = [p.name for p in registry.get_middleware_plugins()]
        assert "safety" in middleware_names
