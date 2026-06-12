"""TDD — Hook system (src/olav/core/hooks.py).

Events: session.start, session.end, tool.call, hitl.requested, hitl.decision
Config: ~/.olav/hooks.json
Fire-and-forget: never blocks event loop.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── HookEvent dataclass ────────────────────────────────────────────────────────


class TestHookEvent:
    """HookEvent carries event name and payload."""

    def test_hook_event_has_name_and_payload(self):
        from olav.core.hooks import HookEvent
        evt = HookEvent(name="session.start", payload={"user": "alice"})
        assert evt.name == "session.start"
        assert evt.payload == {"user": "alice"}

    def test_hook_event_is_frozen(self):
        from olav.core.hooks import HookEvent
        evt = HookEvent(name="tool.call", payload={})
        try:
            evt.name = "changed"  # type: ignore
            assert False, "Should be immutable"
        except (AttributeError, TypeError):
            pass


# ── HookRegistry config loading ───────────────────────────────────────────────


class TestHookRegistryConfig:
    """HookRegistry loads hook commands from ~/.olav/hooks.json."""

    def test_empty_hooks_file_loads_cleanly(self, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({"hooks": []}))
        from olav.core.hooks import HookRegistry
        registry = HookRegistry(config_path=hooks_file)
        assert registry.hooks_for("session.start") == []

    def test_hooks_file_missing_returns_empty(self, tmp_path):
        from olav.core.hooks import HookRegistry
        registry = HookRegistry(config_path=tmp_path / "nonexistent.json")
        assert registry.hooks_for("session.start") == []

    def test_hooks_file_invalid_json_returns_empty(self, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text("not json!")
        from olav.core.hooks import HookRegistry
        registry = HookRegistry(config_path=hooks_file)
        assert registry.hooks_for("session.start") == []

    def test_hooks_file_loads_event_commands(self, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": [
                {"event": "session.start", "command": "echo session started"},
                {"event": "tool.call", "command": "logger -t olav tool called"},
            ]
        }))
        from olav.core.hooks import HookRegistry
        registry = HookRegistry(config_path=hooks_file)
        assert registry.hooks_for("session.start") == ["echo session started"]
        assert registry.hooks_for("tool.call") == ["logger -t olav tool called"]
        assert registry.hooks_for("session.end") == []

    def test_multiple_hooks_for_same_event(self, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": [
                {"event": "session.end", "command": "cmd1"},
                {"event": "session.end", "command": "cmd2"},
            ]
        }))
        from olav.core.hooks import HookRegistry
        registry = HookRegistry(config_path=hooks_file)
        cmds = registry.hooks_for("session.end")
        assert len(cmds) == 2
        assert "cmd1" in cmds
        assert "cmd2" in cmds


# ── HookDispatcher fire behaviour ─────────────────────────────────────────────


class TestHookDispatcher:
    """HookDispatcher fires hook commands as non-blocking background processes."""

    def test_fire_executes_command_for_matching_event(self, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": [{"event": "session.start", "command": "echo hi"}]
        }))
        from olav.core.hooks import HookRegistry, HookDispatcher, HookEvent
        registry = HookRegistry(config_path=hooks_file)
        dispatcher = HookDispatcher(registry=registry)

        executed = []

        def fake_popen(cmd, **kwargs):
            executed.append(cmd)
            return MagicMock()

        with patch("subprocess.Popen", side_effect=fake_popen):
            dispatcher.fire(HookEvent(name="session.start", payload={"user": "u1"}))

        assert len(executed) == 1
        assert "echo hi" in executed[0]

    def test_fire_does_nothing_for_unregistered_event(self, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({"hooks": []}))
        from olav.core.hooks import HookRegistry, HookDispatcher, HookEvent
        registry = HookRegistry(config_path=hooks_file)
        dispatcher = HookDispatcher(registry=registry)

        with patch("subprocess.Popen") as mock_popen:
            dispatcher.fire(HookEvent(name="session.start", payload={}))
            mock_popen.assert_not_called()

    def test_fire_injects_event_payload_as_env_vars(self, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": [{"event": "tool.call", "command": "notify.sh"}]
        }))
        from olav.core.hooks import HookRegistry, HookDispatcher, HookEvent
        registry = HookRegistry(config_path=hooks_file)
        dispatcher = HookDispatcher(registry=registry)

        captured = {}

        def fake_popen(cmd, env=None, **kwargs):
            captured["env"] = env
            return MagicMock()

        with patch("subprocess.Popen", side_effect=fake_popen):
            dispatcher.fire(HookEvent(name="tool.call", payload={"tool": "get_routes"}))

        assert captured.get("env") is not None
        assert captured["env"].get("OLAV_HOOK_EVENT") == "tool.call"
        assert captured["env"].get("OLAV_HOOK_TOOL") == "get_routes"

    def test_fire_never_raises_on_popen_error(self, tmp_path):
        """A broken hook command must never crash the agent."""
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": [{"event": "session.end", "command": "/nonexistent/script.sh"}]
        }))
        from olav.core.hooks import HookRegistry, HookDispatcher, HookEvent
        registry = HookRegistry(config_path=hooks_file)
        dispatcher = HookDispatcher(registry=registry)

        with patch("subprocess.Popen", side_effect=FileNotFoundError("not found")):
            # Must not raise
            dispatcher.fire(HookEvent(name="session.end", payload={}))

    def test_async_fire_is_non_blocking(self, tmp_path):
        """async_fire schedules hook without awaiting — returns immediately."""
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": [{"event": "hitl.requested", "command": "echo hitl"}]
        }))
        from olav.core.hooks import HookRegistry, HookDispatcher, HookEvent
        registry = HookRegistry(config_path=hooks_file)
        dispatcher = HookDispatcher(registry=registry)

        popen_calls = []

        def fake_popen(cmd, **kwargs):
            popen_calls.append(cmd)
            return MagicMock()

        async def run():
            with patch("subprocess.Popen", side_effect=fake_popen):
                await dispatcher.async_fire(HookEvent(name="hitl.requested", payload={}))
                # Give the background task time to run
                await asyncio.sleep(0.05)

        asyncio.run(run())
        assert len(popen_calls) == 1


# ── Global dispatcher singleton ───────────────────────────────────────────────


class TestGlobalDispatcher:
    """get_dispatcher() returns a process-level singleton."""

    def test_get_dispatcher_returns_same_instance(self):
        from olav.core.hooks import get_dispatcher
        d1 = get_dispatcher()
        d2 = get_dispatcher()
        assert d1 is d2

    def test_get_dispatcher_is_hook_dispatcher_type(self):
        from olav.core.hooks import get_dispatcher, HookDispatcher
        dispatcher = get_dispatcher()
        assert isinstance(dispatcher, HookDispatcher)

    def test_fire_hook_convenience_function(self):
        """fire_hook() is a top-level shortcut for get_dispatcher().fire()."""
        from olav.core import hooks
        fired = []
        with patch.object(hooks.get_dispatcher(), "fire", side_effect=lambda e: fired.append(e)):
            hooks.fire_hook("session.start", user="testuser")
        assert len(fired) == 1
        assert fired[0].name == "session.start"
        assert fired[0].payload.get("user") == "testuser"
