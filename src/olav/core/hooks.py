"""hooks.py — Lightweight fire-and-forget event hook dispatcher.

Allows OLAV session lifecycle events to trigger external shell commands
configured in ~/.olav/hooks.json, without blocking the agent event loop.

Supported events:
    session.start    — new agent session created
    session.end      — agent session closed
    tool.call        — tool execution completed
    hitl.requested   — human-in-the-loop approval requested
    hitl.decision    — HITL decision recorded (approved/rejected)

Configuration (``~/.olav/hooks.json``):
    {
        "hooks": [
            {"event": "session.start", "command": "notify-send 'OLAV session started'"},
            {"event": "tool.call",     "command": "/usr/local/bin/olav-audit-hook.sh"}
        ]
    }

Payload fields are injected as ``OLAV_HOOK_*`` environment variables so the
hook command can act on them without parsing JSON.

Design constraints:
    - Never blocks: commands run via ``subprocess.Popen`` (fire-and-forget)
    - Never raises: errors are logged at WARNING, execution continues
    - No new external dependencies: stdlib only
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("olav.hooks")

# ── Event type ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HookEvent:
    """Immutable event object passed to hook dispatchers."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)


# ── Registry ──────────────────────────────────────────────────────────────────


class HookRegistry:
    """Loads hook command definitions from a JSON config file."""

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path.home() / ".olav" / "hooks.json"
        self._config_path = config_path
        self._hooks: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        try:
            data = json.loads(self._config_path.read_text())
            for entry in data.get("hooks", []):
                event = entry.get("event", "")
                command = entry.get("command", "")
                if event and command:
                    self._hooks.setdefault(event, []).append(command)
        except Exception as exc:
            logger.warning("hooks.json load error (%s): %s", self._config_path, exc)

    def hooks_for(self, event_name: str) -> list[str]:
        """Return list of shell commands registered for *event_name*."""
        return list(self._hooks.get(event_name, []))


# ── Dispatcher ────────────────────────────────────────────────────────────────


class HookDispatcher:
    """Executes registered hook commands for incoming events."""

    def __init__(self, registry: HookRegistry | None = None) -> None:
        self._registry = registry or HookRegistry()

    def fire(self, event: HookEvent) -> None:
        """Fire all commands registered for *event.name* (non-blocking)."""
        commands = self._registry.hooks_for(event.name)
        for command in commands:
            env = self._build_env(event)
            try:
                subprocess.Popen(
                    command,
                    shell=True,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            except Exception as exc:
                logger.warning("Hook command failed (event=%s): %s", event.name, exc)

    async def async_fire(self, event: HookEvent) -> None:
        """Schedule ``fire()`` as a background asyncio task (non-blocking)."""
        asyncio.get_event_loop().run_in_executor(None, self.fire, event)

    @staticmethod
    def _build_env(event: HookEvent) -> dict[str, str]:
        """Build environment variables for hook process from event payload."""
        env = dict(os.environ)
        env["OLAV_HOOK_EVENT"] = event.name
        for key, value in event.payload.items():
            env_key = f"OLAV_HOOK_{key.upper()}"
            env[env_key] = str(value)
        return env


# ── Singleton ─────────────────────────────────────────────────────────────────

_dispatcher: HookDispatcher | None = None


def get_dispatcher() -> HookDispatcher:
    """Return the process-level singleton HookDispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = HookDispatcher()
    return _dispatcher


def fire_hook(event_name: str, **payload: Any) -> None:
    """Convenience function: fire an event on the global dispatcher.

    Example::

        from olav.core.hooks import fire_hook
        fire_hook("session.start", user="alice", agent_id="ops")
    """
    get_dispatcher().fire(HookEvent(name=event_name, payload=payload))
