"""
tests/unit/test_tui_mode_resolver.py
────────────────────────────────────
Unit coverage for :func:`olav.cli.tui_overlay.resolve_tui_mode`
(P6 cycle 1).

The resolver picks between two paths for the OLAV TUI:

* ``"native"`` — simple_cli will call
  ``run_textual_app(server_kwargs=...)`` so deepagents-cli spawns a
  langgraph subprocess.  ``/agents`` command natively switches
  workspaces; our overlay just handles banner/title.
* ``"overlay"`` — simple_cli keeps v0.19.x in-process behaviour
  (``run_textual_app(agent=<graph>)``).  The full overlay stays
  active: ``/workspace``, ``/ops`` aliases, restart-on-swap loop.

Decision precedence:

1. ``OLAV_TUI_MODE`` env var (``native`` / ``overlay``); unknown
   values fall back to the layout-driven default with a warning.
2. Auto-detect via ``.deepagents/agents/`` existence — new layout
   implies native, legacy implies overlay.

The default flips once Phase B (v0.20.2) ships: `new` layout + env
unset → `native`.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLAV_TUI_MODE", raising=False)


# ── 1. Explicit env var wins ───────────────────────────────────────────────


def test_explicit_native_returns_native(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olav.cli.tui_overlay import resolve_tui_mode

    monkeypatch.setenv("OLAV_TUI_MODE", "native")
    # Root has legacy workspace; env should override
    (tmp_path / ".olav" / "workspace" / "core").mkdir(parents=True)
    assert resolve_tui_mode(root=tmp_path) == "native"


def test_explicit_overlay_returns_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olav.cli.tui_overlay import resolve_tui_mode

    monkeypatch.setenv("OLAV_TUI_MODE", "overlay")
    # Root has new layout; env should override
    (tmp_path / ".deepagents" / "agents" / "core").mkdir(parents=True)
    assert resolve_tui_mode(root=tmp_path) == "overlay"


def test_mixed_case_env_normalised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olav.cli.tui_overlay import resolve_tui_mode

    monkeypatch.setenv("OLAV_TUI_MODE", "Native")
    assert resolve_tui_mode(root=tmp_path) == "native"


def test_unknown_env_falls_back_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from olav.cli.tui_overlay import resolve_tui_mode

    monkeypatch.setenv("OLAV_TUI_MODE", "turbo")  # not valid
    # Root has neither layout → auto-default (new) → "native"
    with caplog.at_level(logging.WARNING):
        mode = resolve_tui_mode(root=tmp_path)
    assert mode in ("native", "overlay")  # falls back to layout-driven
    assert any("turbo" in rec.message for rec in caplog.records)


def test_empty_env_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olav.cli.tui_overlay import resolve_tui_mode

    monkeypatch.setenv("OLAV_TUI_MODE", "")
    # Root has new layout → native
    (tmp_path / ".deepagents" / "agents" / "core").mkdir(parents=True)
    assert resolve_tui_mode(root=tmp_path) == "native"


# ── 2. Auto-detect from layout ─────────────────────────────────────────────


def test_auto_detect_new_layout_is_native(tmp_path: Path) -> None:
    from olav.cli.tui_overlay import resolve_tui_mode

    (tmp_path / ".deepagents" / "agents" / "core").mkdir(parents=True)
    assert resolve_tui_mode(root=tmp_path) == "native"


def test_auto_detect_legacy_layout_is_overlay(tmp_path: Path) -> None:
    from olav.cli.tui_overlay import resolve_tui_mode

    (tmp_path / ".olav" / "workspace" / "core").mkdir(parents=True)
    # No new layout
    assert resolve_tui_mode(root=tmp_path) == "overlay"


def test_auto_detect_no_layout_defaults_native(tmp_path: Path) -> None:
    """Fresh projects — no .olav/, no .deepagents/ — default to native
    so `olav init` on a brand-new project uses the new layout."""
    from olav.cli.tui_overlay import resolve_tui_mode

    assert resolve_tui_mode(root=tmp_path) == "native"


def test_auto_detect_both_prefers_native(tmp_path: Path) -> None:
    """Partial-migration state (both layouts present) → native.
    Matches tool_loader.detect_layout and
    migrate.v0_20_layout.already_migrated policy."""
    from olav.cli.tui_overlay import resolve_tui_mode

    (tmp_path / ".olav" / "workspace" / "core").mkdir(parents=True)
    (tmp_path / ".deepagents" / "agents" / "core").mkdir(parents=True)
    assert resolve_tui_mode(root=tmp_path) == "native"


# ── 3. Default root ────────────────────────────────────────────────────────


def test_default_root_is_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When root is not passed, uses cwd."""
    from olav.cli import tui_overlay

    (tmp_path / ".deepagents" / "agents" / "core").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert tui_overlay.resolve_tui_mode() == "native"
