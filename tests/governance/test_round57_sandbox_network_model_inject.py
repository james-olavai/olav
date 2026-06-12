"""Round 57 — ARCH-14 sandbox NetworkModel auto-inject.

**R74 cutover** (ADR-0002 V1 fix): the prologue moved from a hardcoded
``_NETWORK_MODEL_PROLOGUE`` module constant in
``olav.platform.sandbox`` to an entry-point registration at
``olav.sandbox_prologues.netops_network_model`` → shipped from
``olav_netops.sandbox_prologue.NETWORK_MODEL_PROLOGUE``.

These tests pin the NEW location so the ARCH-14 contract ("every
sandbox script gets ``model`` pre-bound to a NetworkModel, or
``None`` when olav_netops isn't installed") survives the
platform/domain boundary cleanup.
"""

from __future__ import annotations

import re

import pytest


def _load_prologue() -> str:
    try:
        from olav_netops.sandbox_prologue import NETWORK_MODEL_PROLOGUE
    except ImportError:
        pytest.skip(
            "olav_netops not installed — sandbox prologue is shipped "
            "by that wheel. Install it to exercise the prologue pin."
        )
    return NETWORK_MODEL_PROLOGUE


def test_network_model_prologue_exists():
    src = _load_prologue()
    assert isinstance(src, str) and src.strip()


def test_prologue_imports_load_network_model():
    src = _load_prologue()
    assert "from olav_netops.sim import load_network_model" in src


def test_prologue_binds_model_local():
    src = _load_prologue()
    assert "model = _olav_load_network_model()" in src


def test_prologue_degrades_to_none_on_import_failure():
    src = _load_prologue()
    pattern = re.compile(r"except\s+Exception\s*:\s*\n\s*model\s*=\s*None")
    assert pattern.search(src), (
        "prologue must set `model = None` on import failure; got:\n" + src
    )


def test_prologue_uses_broad_except_not_bare():
    src = _load_prologue()
    assert "except Exception:" in src
    assert "except:\n" not in src  # bare `except:` forbidden


def test_prologue_registered_via_entry_point():
    """Entry-point contract: olav-netops ships the registration;
    platform sandbox discovers it without importing olav_netops directly."""
    from importlib.metadata import entry_points
    eps = list(entry_points(group="olav.sandbox_prologues"))
    if not eps:
        pytest.skip("no olav.sandbox_prologues entry-points registered")
    assert any(ep.name == "netops_network_model" for ep in eps), (
        f"netops_network_model entry-point missing; got: {[e.name for e in eps]}"
    )


def test_sandbox_collects_domain_prologues():
    """`_collect_domain_prologues()` replaced the old module-level
    ``_NETWORK_MODEL_PROLOGUE`` constant; it iterates registered
    prologues and concatenates their sources."""
    from importlib.metadata import entry_points
    from olav.platform.sandbox import _collect_domain_prologues
    out = _collect_domain_prologues()
    assert isinstance(out, str)
    eps = list(entry_points(group="olav.sandbox_prologues"))
    if any(ep.name == "netops_network_model" for ep in eps):
        assert "load_network_model" in out
