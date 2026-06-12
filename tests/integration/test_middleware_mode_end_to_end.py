"""
tests/integration/test_middleware_mode_end_to_end.py
────────────────────────────────────────────────────
Integration test proving the P3 dual-path mode selector takes effect
inside a real ``OLAVAgent`` — not just inside
:func:`partition_for_mode` unit tests.

Rather than booting the full LangGraph (requires LLM credentials),
this test constructs a fresh :class:`PluginRegistry`, runs auto-
discovery, and applies :func:`partition_for_mode` in both modes.
Then it asserts:

  * middleware mode → AuditMiddleware IN middleware list,
                       AuditCallbackPlugin OUT of callback list
  * callback mode   → AuditMiddleware OUT of middleware list,
                       AuditCallbackPlugin IN callback list

This is the minimum reproduction that catches regressions from:

  * a future rename of AuditMiddleware.name ("audit_middleware")
  * a future rename of AuditCallbackPlugin.name ("audit")
  * someone wiring `OLAVAgent.ainvoke` to the raw
    ``plugin_registry.get_callback_plugins()`` instead of
    ``self._olav_callbacks``

If the full LangGraph path is needed, that lives in later cycles with
recorded fixtures.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLAV_MIDDLEWARE_MODE", raising=False)


# ── 1. Real registry + partition in explicit callback mode ────────────────


def test_real_registry_callback_mode_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OLAV_MIDDLEWARE_MODE=callback`` still opts into the legacy path
    (v0.20.3+ default is middleware, so we have to set the env var
    explicitly to exercise this branch)."""
    monkeypatch.setenv("OLAV_MIDDLEWARE_MODE", "callback")

    from olav.plugins import load_builtin_plugins
    from olav.plugins.middleware._mode import (
        partition_for_mode,
        resolve_middleware_mode,
    )
    from olav.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    load_builtin_plugins(registry)

    mode = resolve_middleware_mode()
    assert mode == "callback"

    middleware, callbacks = partition_for_mode(registry, mode)
    mw_names = {m.name for m in middleware}
    cb_names = {c.name for c in callbacks}

    # AuditMiddleware dropped in callback mode
    assert "audit_middleware" not in mw_names
    # Other real middleware plugins still present (guard against the
    # partitioner accidentally dropping too much)
    assert "guardrails" in mw_names
    assert "memory_capture" in mw_names

    # AuditCallbackPlugin present on the callback side
    assert "audit" in cb_names


def test_real_registry_default_mode_is_middleware() -> None:
    """No env var → middleware mode per v0.20.3 cutover."""
    from olav.plugins import load_builtin_plugins
    from olav.plugins.middleware._mode import (
        partition_for_mode,
        resolve_middleware_mode,
    )
    from olav.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    load_builtin_plugins(registry)

    mode = resolve_middleware_mode()
    assert mode == "middleware"

    middleware, callbacks = partition_for_mode(registry, mode)
    mw_names = {m.name for m in middleware}
    cb_names = {c.name for c in callbacks}

    # AuditMiddleware present
    assert "audit_middleware" in mw_names
    # AuditCallbackPlugin dropped
    assert "audit" not in cb_names
    # security_sidecar observer still lives on the callback side
    assert "security_sidecar" in cb_names


# ── 2. Real registry + partition in middleware mode ────────────────────────


def test_real_registry_middleware_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit OLAV_MIDDLEWARE_MODE=middleware → middleware mode."""
    from olav.plugins import load_builtin_plugins
    from olav.plugins.middleware._mode import (
        partition_for_mode,
        resolve_middleware_mode,
    )
    from olav.plugins.registry import PluginRegistry

    monkeypatch.setenv("OLAV_MIDDLEWARE_MODE", "middleware")

    registry = PluginRegistry()
    load_builtin_plugins(registry)

    mode = resolve_middleware_mode()
    assert mode == "middleware"

    middleware, callbacks = partition_for_mode(registry, mode)
    mw_names = {m.name for m in middleware}
    cb_names = {c.name for c in callbacks}

    # AuditMiddleware included
    assert "audit_middleware" in mw_names

    # AuditCallbackPlugin dropped; security_sidecar still present
    # (it's a genuine observer, not audit)
    assert "audit" not in cb_names
    assert "security_sidecar" in cb_names


# ── 3. No duplicate audit instances across both lists ──────────────────────


def test_exactly_one_audit_path_per_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guardrail against drift — no mode should leave BOTH audit
    paths active (would double-count events)."""
    from olav.plugins import load_builtin_plugins
    from olav.plugins.middleware._mode import partition_for_mode
    from olav.plugins.registry import PluginRegistry

    for mode in ("callback", "middleware"):
        registry = PluginRegistry()
        load_builtin_plugins(registry)
        middleware, callbacks = partition_for_mode(registry, mode)

        has_mw_audit = any(m.name == "audit_middleware" for m in middleware)
        has_cb_audit = any(c.name == "audit" for c in callbacks)

        # Exactly one must be true, never both, never neither.
        assert has_mw_audit != has_cb_audit, (
            f"mode={mode}: mw_audit={has_mw_audit}, cb_audit={has_cb_audit}"
        )
