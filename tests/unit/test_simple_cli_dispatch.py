"""
tests/unit/test_simple_cli_dispatch.py
──────────────────────────────────────
Unit coverage for the P6 cycle 2 dispatch inside
:func:`olav.cli.main.simple_cli`.

Behaviour under test:

1. ``OLAV_TUI_MODE=native`` → ``run_textual_app`` receives
   ``server_kwargs=...`` **and no** ``agent=`` kwarg (subprocess owns
   the graph via our scaffold patch).
2. ``OLAV_TUI_MODE=overlay`` → ``run_textual_app`` receives ``agent=``
   (v0.19 in-process path); ``server_kwargs`` is absent.
3. Auto-detect defaults to whatever ``resolve_tui_mode()`` returns —
   patched to a known value for deterministic tests.
4. Failsafe: auto mode + native attempt raises → falls back to
   overlay path.
5. Explicit ``native`` + native attempt raises → error surfaces (no
   silent fallback — users who typed the env var want the truth).

The tests stub ``run_textual_app`` so no real Textual process
starts; mode resolver is monkey-patched too so we aren't at the
mercy of filesystem state.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLAV_TUI_MODE", raising=False)
    # simple_cli routes non-TTY stdin to the headless _pipe_repl
    # (2026-06-12); these tests exercise the TUI dispatch, so pretend
    # stdin is a terminal (pytest's capture stdin reports isatty=False).
    import sys as _sys
    import types as _types

    monkeypatch.setattr(
        _sys, "stdin", _types.SimpleNamespace(isatty=lambda: True)
    )
    # Drop the cached tui_overlay so prior tests that re-imported it
    # under a stub sys.modules don't leave a stale module where our
    # monkey-patches can't take effect.
    import sys

    monkeypatch.delitem(sys.modules, "olav.cli.tui_overlay", raising=False)
    # main.py caches `from olav.cli.tui_overlay import X` at module
    # scope indirectly via `import os`, so re-importing main forces
    # its internal function-body imports to read the fresh overlay.
    monkeypatch.delitem(sys.modules, "olav.cli.main", raising=False)


def _build_session_state(*, auto_approve: bool = False) -> MagicMock:
    s = MagicMock()
    s.auto_approve = auto_approve
    s.no_splash = True  # suppress splash path
    return s


def _patch_run_textual(monkeypatch: pytest.MonkeyPatch, *, side_effect=None) -> AsyncMock:
    """Replace ``run_textual_app`` on the real ``deepagents_code.app``
    module so ``simple_cli``'s ``from … import`` picks up the mock
    without clobbering other attributes (DeepAgentsApp, etc.)."""
    mock = AsyncMock(return_value=None)
    if side_effect is not None:
        mock.side_effect = side_effect

    # setattr on the live module — avoids replacing the whole module
    # (which would lose DeepAgentsApp the overlay's real apply_* needs).
    monkeypatch.setattr("deepagents_code.app.run_textual_app", mock)
    return mock


def _patch_overlay(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Force the TUI mode resolver to return *mode* and make
    apply_olav_overlay a fast-return no-op so unit tests don't
    touch real deepagents internals.

    Uses module-object setattr (not string form) to survive test
    ordering where the tui_overlay module may have been re-imported
    under synthetic deepagents stubs by a prior test.
    """
    # Force a fresh import: drop any cached module so the test
    # starts from a clean state.
    import sys

    monkeypatch.delitem(sys.modules, "olav.cli.tui_overlay", raising=False)
    import olav.cli.tui_overlay as overlay

    monkeypatch.setattr(overlay, "resolve_tui_mode", lambda root=None: mode)
    monkeypatch.setattr(overlay, "apply_olav_overlay", lambda: True)


# ── 1. Native mode passes server_kwargs, no agent= ────────────────────────


def test_native_mode_uses_server_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_overlay(monkeypatch, "native")
    run_mock = _patch_run_textual(monkeypatch)

    from olav.cli.main import simple_cli

    agent = MagicMock()
    agent.graph = MagicMock()
    asyncio.run(
        simple_cli(
            agent=agent,
            assistant_id="ops",
            session_state=_build_session_state(),
            backend=MagicMock(),
        )
    )

    assert run_mock.await_count == 1
    kwargs = run_mock.await_args.kwargs
    assert "server_kwargs" in kwargs, "native mode must pass server_kwargs"
    assert kwargs["server_kwargs"].get("assistant_id") == "ops"
    # NO agent=<graph> — subprocess owns the graph
    assert "agent" not in kwargs or kwargs.get("agent") is None


# ── 2. Overlay mode passes agent=, no server_kwargs ───────────────────────


def test_overlay_mode_uses_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_overlay(monkeypatch, "overlay")
    run_mock = _patch_run_textual(monkeypatch)

    from olav.cli.main import simple_cli

    graph_obj = MagicMock()
    agent = MagicMock()
    agent.graph = graph_obj

    asyncio.run(
        simple_cli(
            agent=agent,
            assistant_id="core",
            session_state=_build_session_state(),
            backend=MagicMock(),
        )
    )

    assert run_mock.await_count == 1
    kwargs = run_mock.await_args.kwargs
    assert kwargs.get("agent") is graph_obj
    assert "server_kwargs" not in kwargs, "overlay mode must NOT pass server_kwargs"


# ── 3. Auto mode + native failure → falls back to overlay ─────────────────


def test_native_failure_auto_mode_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_overlay(monkeypatch, "native")

    # First call (native) raises; second call (overlay) succeeds.
    call_args: list[dict] = []

    async def _flaky(*args, **kwargs):
        call_args.append(kwargs)
        if "server_kwargs" in kwargs:
            raise RuntimeError("simulated subprocess failure")
        return None

    monkeypatch.setattr("deepagents_code.app.run_textual_app", _flaky)

    from olav.cli.main import simple_cli

    agent = MagicMock()
    agent.graph = MagicMock()

    # Auto mode (no env var) — should fall through quietly.
    asyncio.run(
        simple_cli(
            agent=agent,
            assistant_id="core",
            session_state=_build_session_state(),
            backend=MagicMock(),
        )
    )

    assert len(call_args) == 2, f"expected 2 calls (native then overlay), got {len(call_args)}"
    assert "server_kwargs" in call_args[0]
    assert "server_kwargs" not in call_args[1]
    assert call_args[1].get("agent") is not None


# ── 4. Explicit native + failure → raises (no fallback) ──────────────────


def test_explicit_native_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLAV_TUI_MODE", "native")
    _patch_overlay(monkeypatch, "native")

    async def _boom(*args, **kwargs):
        raise RuntimeError("explicit native boom")

    monkeypatch.setattr("deepagents_code.app.run_textual_app", _boom)

    from olav.cli.main import simple_cli

    agent = MagicMock()
    agent.graph = MagicMock()

    with pytest.raises(RuntimeError, match="explicit native boom"):
        asyncio.run(
            simple_cli(
                agent=agent,
                assistant_id="core",
                session_state=_build_session_state(),
                backend=MagicMock(),
            )
        )


# ── 5. Explicit overlay takes the overlay branch directly ────────────────


def test_explicit_overlay_skips_native_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLAV_TUI_MODE", "overlay")
    _patch_overlay(monkeypatch, "overlay")
    run_mock = _patch_run_textual(monkeypatch)

    from olav.cli.main import simple_cli

    agent = MagicMock()
    agent.graph = MagicMock()

    asyncio.run(
        simple_cli(
            agent=agent,
            assistant_id="audit",
            session_state=_build_session_state(),
            backend=MagicMock(),
        )
    )

    # Exactly one call — no native attempt first.
    assert run_mock.await_count == 1
    kwargs = run_mock.await_args.kwargs
    assert "server_kwargs" not in kwargs
    assert kwargs.get("agent") is not None
