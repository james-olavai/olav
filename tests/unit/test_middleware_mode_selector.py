"""
tests/unit/test_middleware_mode_selector.py
───────────────────────────────────────────
Unit coverage for the OLAVAgent dual-path selector introduced in
P3 cycle 4.

The selector logic:

1. Reads ``OLAV_MIDDLEWARE_MODE`` env var.
2. Returns either ``"callback"`` or ``"middleware"``; anything else
   (unset, empty, typo) normalises to the v0.20.1 default
   ``"callback"``.
3. Given a :class:`PluginRegistry`, the mode-aware partitioner returns
   the *effective* middleware list and callback list — filtering so
   that audit runs in exactly one path per invocation:

   * ``mode="callback"``  → AuditCallbackPlugin in callbacks,
                             AuditMiddleware dropped from middleware
   * ``mode="middleware"`` → AuditMiddleware in middleware,
                             AuditCallbackPlugin dropped from callbacks

Every other plugin (guardrails, memory_capture, safety, …) passes
through unchanged in both modes.

The selector is a pure function — no I/O, no LangGraph dependencies —
so the tests don't need to build a real agent graph.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no ambient OLAV_MIDDLEWARE_MODE leaks into tests."""
    monkeypatch.delenv("OLAV_MIDDLEWARE_MODE", raising=False)


# ── 1. resolve_middleware_mode() ────────────────────────────────────────────


def test_default_mode_is_middleware() -> None:
    """v0.20.3 policy: unset env → middleware (cutover from callback
    default shipped in v0.20.1/v0.20.2).  Callback path still works
    via explicit ``OLAV_MIDDLEWARE_MODE=callback``."""
    from olav.plugins.middleware._mode import resolve_middleware_mode

    assert resolve_middleware_mode() == "middleware"


def test_explicit_callback_env_returns_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olav.plugins.middleware._mode import resolve_middleware_mode

    monkeypatch.setenv("OLAV_MIDDLEWARE_MODE", "callback")
    assert resolve_middleware_mode() == "callback"


def test_middleware_env_returns_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olav.plugins.middleware._mode import resolve_middleware_mode

    monkeypatch.setenv("OLAV_MIDDLEWARE_MODE", "middleware")
    assert resolve_middleware_mode() == "middleware"


def test_mixed_case_env_is_normalised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olav.plugins.middleware._mode import resolve_middleware_mode

    monkeypatch.setenv("OLAV_MIDDLEWARE_MODE", "MIDDLEWARE")
    assert resolve_middleware_mode() == "middleware"


def test_unknown_mode_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Typos like 'middlewre' / 'cb' must not crash; log a warning
    and fall back to the current default (v0.20.3+ = middleware)."""
    from olav.plugins.middleware._mode import resolve_middleware_mode

    monkeypatch.setenv("OLAV_MIDDLEWARE_MODE", "middlewre")
    import logging

    with caplog.at_level(logging.WARNING):
        mode = resolve_middleware_mode()
    assert mode == "middleware"
    assert any("middlewre" in rec.message for rec in caplog.records)


def test_empty_string_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olav.plugins.middleware._mode import resolve_middleware_mode

    monkeypatch.setenv("OLAV_MIDDLEWARE_MODE", "")
    assert resolve_middleware_mode() == "middleware"


# ── 2. partition_for_mode() — plugin list partitioning ──────────────────────


class _FakeMiddleware:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCallback:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeRegistry:
    def __init__(
        self,
        middleware_names: list[str],
        callback_names: list[str],
    ) -> None:
        self._mw = [_FakeMiddleware(n) for n in middleware_names]
        self._cb = [_FakeCallback(n) for n in callback_names]

    def get_middleware_plugins(self) -> list:
        return list(self._mw)

    def get_callback_plugins(self) -> list:
        return list(self._cb)


def test_partition_callback_mode_drops_audit_middleware() -> None:
    """In callback mode, AuditMiddleware must NOT receive events —
    otherwise both paths audit and we double-count."""
    from olav.plugins.middleware._mode import partition_for_mode

    registry = _FakeRegistry(
        middleware_names=["audit_middleware", "guardrails", "memory_capture"],
        callback_names=["audit", "security_sidecar"],
    )
    middleware, callbacks = partition_for_mode(registry, "callback")

    middleware_names = {m.name for m in middleware}
    callback_names = {c.name for c in callbacks}

    assert "audit_middleware" not in middleware_names
    assert "guardrails" in middleware_names
    assert "memory_capture" in middleware_names
    # Callback side: AuditCallbackPlugin (name="audit") stays
    assert "audit" in callback_names
    assert "security_sidecar" in callback_names


def test_partition_middleware_mode_drops_audit_callback() -> None:
    from olav.plugins.middleware._mode import partition_for_mode

    registry = _FakeRegistry(
        middleware_names=["audit_middleware", "guardrails"],
        callback_names=["audit", "security_sidecar"],
    )
    middleware, callbacks = partition_for_mode(registry, "middleware")

    middleware_names = {m.name for m in middleware}
    callback_names = {c.name for c in callbacks}

    assert "audit_middleware" in middleware_names
    assert "guardrails" in middleware_names
    # Callback side: AuditCallbackPlugin dropped; security_sidecar kept
    assert "audit" not in callback_names
    assert "security_sidecar" in callback_names


def test_partition_unknown_mode_falls_back_to_callback_partition() -> None:
    """Defensive — if somehow an invalid mode string reaches the
    partitioner, behave like callback mode."""
    from olav.plugins.middleware._mode import partition_for_mode

    registry = _FakeRegistry(
        middleware_names=["audit_middleware", "guardrails"],
        callback_names=["audit"],
    )
    middleware, callbacks = partition_for_mode(registry, "nonsense")
    assert "audit_middleware" not in {m.name for m in middleware}
    assert "audit" in {c.name for c in callbacks}


def test_partition_preserves_order() -> None:
    """Plugin order matters — some plugins depend on earlier ones
    rewriting the system prompt.  The partitioner must not reorder."""
    from olav.plugins.middleware._mode import partition_for_mode

    registry = _FakeRegistry(
        middleware_names=["first", "audit_middleware", "second", "third"],
        callback_names=[],
    )
    middleware, _ = partition_for_mode(registry, "middleware")
    assert [m.name for m in middleware] == [
        "first",
        "audit_middleware",
        "second",
        "third",
    ]


def test_partition_returns_empty_lists_for_empty_registry() -> None:
    from olav.plugins.middleware._mode import partition_for_mode

    registry = _FakeRegistry(middleware_names=[], callback_names=[])
    middleware, callbacks = partition_for_mode(registry, "middleware")
    assert middleware == []
    assert callbacks == []
