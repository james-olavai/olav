"""Sandbox prologue registered for the ``olav.sandbox_prologues`` entry-point.

The olav platform's sandbox iterates this group and concatenates every
registered prologue into the wrapper script. Every injected snippet runs
in a self-guarded try/except so a missing dependency never breaks the
sandbox for unrelated extensions.

This module ships with olav-netops and auto-injects ``model`` — a
pre-loaded :class:`NetworkModel` — into every sandbox execution. The
construction call itself is lazy on DuckDB, so the cost is pay-per-use.
"""

from __future__ import annotations


NETWORK_MODEL_PROLOGUE = """\
# ── olav-netops sandbox prologue: NetworkModel auto-inject (ARCH-14) ──
try:
    from olav_netops.sim import load_network_model as _olav_load_network_model
    model = _olav_load_network_model()
except Exception:
    model = None
# ── end olav-netops sandbox prologue ──────────────────────────────────
"""


def network_model_prologue() -> str:
    """Entry-point callable: return the injection source as a string.

    Using a callable (not a module-level constant export) defers any
    future runtime logic (e.g. environment-conditional injection)
    without breaking the entry-point contract.
    """
    return NETWORK_MODEL_PROLOGUE
