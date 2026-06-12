"""
tests/unit/test_run_context.py
──────────────────────────────
Unit coverage for src/olav/plugins/middleware/_context.py.

OlavRunContext is the per-invocation carrier that replaces the
imperative ``AuditCallbackPlugin.bind_run(run_id)`` pattern.  It
travels via LangGraph's ``Runtime.context`` from the CLI/API entry
point into every middleware hook.

Guarantees:
  1. Module/class is importable.
  2. All fields default to safe, None-like values (no import-time
     recorder construction, no UUID generation — pure data).
  3. ``with_run_id`` returns a *new* instance (frozen-dataclass
     immutability) so middleware can't accidentally mutate shared
     context.
  4. ``as_dict`` produces a dict suitable for audit payloads with
     only the lightweight, JSON-safe fields (no recorder object).
"""

from __future__ import annotations

import pytest


def test_module_importable() -> None:
    from olav.plugins.middleware import _context

    assert hasattr(_context, "OlavRunContext")


def test_default_values_are_safe() -> None:
    from olav.plugins.middleware._context import OlavRunContext

    ctx = OlavRunContext()
    assert ctx.run_id is None
    assert ctx.recorder is None
    assert ctx.agent_id is None
    assert ctx.user_id is None
    # Default source_channel is "cli" — matches source_channel argument
    # passed to AuditEventRecorder events from single-query mode.
    assert ctx.source_channel == "cli"


def test_constructor_accepts_all_fields() -> None:
    from olav.plugins.middleware._context import OlavRunContext

    sentinel_recorder = object()  # any marker; middleware only forwards it
    ctx = OlavRunContext(
        run_id="abc-123",
        recorder=sentinel_recorder,
        agent_id="core",
        user_id="yhvh",
        source_channel="cli_interactive",
    )
    assert ctx.run_id == "abc-123"
    assert ctx.recorder is sentinel_recorder
    assert ctx.agent_id == "core"
    assert ctx.user_id == "yhvh"
    assert ctx.source_channel == "cli_interactive"


def test_with_run_id_returns_new_instance() -> None:
    """Swapping run_id must not mutate the caller's context — otherwise
    two concurrent turns on the same agent would stomp each other's
    run_id in the audit trail."""
    from olav.plugins.middleware._context import OlavRunContext

    original = OlavRunContext(run_id="old", agent_id="core")
    updated = original.with_run_id("new")

    assert original.run_id == "old"  # untouched
    assert updated.run_id == "new"
    assert updated.agent_id == "core"  # other fields preserved
    assert updated is not original


def test_as_dict_excludes_recorder() -> None:
    """as_dict() is for audit payloads / logs, so it must not
    serialize the AuditEventRecorder reference (which is not JSON-safe
    and would pull the whole DB connection into the payload)."""
    from olav.plugins.middleware._context import OlavRunContext

    recorder = object()
    ctx = OlavRunContext(
        run_id="r1",
        recorder=recorder,
        agent_id="ops",
        user_id="alice",
        source_channel="api",
    )
    as_dict = ctx.as_dict()

    assert "recorder" not in as_dict
    assert as_dict == {
        "run_id": "r1",
        "agent_id": "ops",
        "user_id": "alice",
        "source_channel": "api",
    }


def test_as_dict_omits_none_fields() -> None:
    """Keep audit payloads compact — skip fields that are None."""
    from olav.plugins.middleware._context import OlavRunContext

    ctx = OlavRunContext(run_id="r1")
    as_dict = ctx.as_dict()
    assert as_dict == {"run_id": "r1", "source_channel": "cli"}
    # user_id / agent_id missing because they're None
