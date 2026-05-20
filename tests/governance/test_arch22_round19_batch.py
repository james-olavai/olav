"""ARCH-22 Round 19 batch — housekeeping fixes with governance pins.

Scope (Round 19):

* **C3**: `OLAV_WEB_PORT` env var overrides ``DEFAULT_WEB_PORT``
  (previously hardcoded to 2280). Exercise both the successful-parse path
  and the invalid-value fallback.
* ~~**C4**~~: remote_execute.py deleted (rev 279); C4 check retired.
* **A1**: ``.olav/workspace/`` tree must contain zero ``*.disabled``
  files. ``olav refresh`` sweeps them (see ``test_disabled_cleanup.py``);
  this test is the on-disk deployment-state backstop.

Items from ARCH-22 intentionally NOT fixed this round (pin their
deferral reason so we don't silently forget):

* A2 audit_logger.py delete — blocked by ``test_audit_logger_noop.py``
  + ``LEGACY-REMOVE-v0.19`` marker (current v0.18.x, defer to v0.19).
* A4 ``_legacy_archived/`` 180MB move — needs operator decision on
  archive strategy (independent repo vs. git tag).
* C1/C2/C5 — coupled with ARCH-20 Phase 3, enterprise module, or
  next-major breaking change respectively.
* D 27-ref legacy tagging — manual review, not appropriate for auto mode.
* E ``_deepagents_bridge.py`` refactor — code rewrite, separate round.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]


# ── ARCH-22 C3: OLAV_WEB_PORT env override ──────────────────────────────────


def test_c3_web_port_honors_env_override(monkeypatch):
    """Setting ``OLAV_WEB_PORT`` before module import yields that value."""
    monkeypatch.setenv("OLAV_WEB_PORT", "9999")
    from olav.core import defaults
    importlib.reload(defaults)
    try:
        assert defaults.DEFAULT_WEB_PORT == 9999
    finally:
        monkeypatch.delenv("OLAV_WEB_PORT")
        importlib.reload(defaults)
    assert defaults.DEFAULT_WEB_PORT == 2280


def test_c3_invalid_env_falls_back_to_default(monkeypatch):
    """Garbage in the env var falls back to the baked-in default (no crash)."""
    monkeypatch.setenv("OLAV_WEB_PORT", "not-a-number")
    from olav.core import defaults
    importlib.reload(defaults)
    try:
        assert defaults.DEFAULT_WEB_PORT == 2280
    finally:
        monkeypatch.delenv("OLAV_WEB_PORT")
        importlib.reload(defaults)


def test_c3_env_int_helper_handles_unset_and_invalid():
    """Direct helper unit — does not depend on module-level reload state."""
    from olav.core.defaults import _env_int
    # Unset → default
    assert _env_int("__OLAV_NONEXISTENT_VAR__", 42) == 42


def test_c3_env_int_helper_parses_valid(monkeypatch):
    monkeypatch.setenv("__OLAV_TEST_INT__", "1234")
    from olav.core.defaults import _env_int
    assert _env_int("__OLAV_TEST_INT__", 0) == 1234


def test_c3_env_int_helper_falls_back_on_garbage(monkeypatch):
    monkeypatch.setenv("__OLAV_TEST_INT__", "not_a_number")
    from olav.core.defaults import _env_int
    assert _env_int("__OLAV_TEST_INT__", 99) == 99



# ── ARCH-22 A1: no *.disabled residue in deployment workspace ───────────────


def test_a1_no_disabled_files_under_workspace():
    """After Round 18 ``olav refresh`` added the disabled-sweep step, the
    deployed workspace must contain zero ``*.disabled`` files.
    """
    workspace = REPO / ".olav" / "workspace"
    residue = list(workspace.rglob("*.disabled"))
    assert not residue, (
        f"Round 19 regression: {len(residue)} ``*.disabled`` files present "
        f"under {workspace}: {[str(p.relative_to(REPO)) for p in residue[:5]]}"
    )


# ── ARCH-22 A2 deferral marker ──────────────────────────────────────────────


def test_a2_audit_logger_still_present_pending_v0_19():
    """Closed in Round 66: audit_logger.py deleted with the v0.19 cut.
    The test name is kept (for traceability) but the assertion inverts —
    the file and its noop test must now be ABSENT.
    """
    p = REPO / "src" / "olav" / "core" / "audit_logger.py"
    assert not p.exists(), (
        f"audit_logger.py reappeared at {p} — ARCH-22 A2 was closed at "
        f"the v0.19 cut (Round 66). Any reintroduction needs an ADR."
    )
    noop = REPO / "tests" / "unit" / "test_audit_logger_noop.py"
    assert not noop.exists(), (
        f"test_audit_logger_noop.py reappeared at {noop} — was removed "
        f"alongside audit_logger.py in Round 66."
    )
