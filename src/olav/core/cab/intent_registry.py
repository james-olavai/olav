"""ISSUE-ARCH-40 (P2, 2026-05-12) — single source of truth for
intent-type metadata shared by CAB emission, SRL render, and SRL
rollback.

Before this module:
    _SUPPORTED_INTENTS = {"ebgp_direct"}     # × 3 copies
    if len(devices) != 2: raise ...           # × 4 copies

Adding a new 2-device intent (e.g. ``ospf_p2p``) required editing
three files in lockstep, plus a fourth-file device-count guard, with
no compile-time safeguard against forgetting one. This module
centralises both facts.

Downstream importers:
  * olav.core.cab.prod_cli          — prod CLI generator dispatch
  * olav.core.lab.srl_render        — lab SRL render dispatch
  * olav.core.lab.srl_rollback      — lab SRL rollback dispatch
  * olav.core.cab.tcf_writer        — render_tcf_from_change_plan
    feasibility guard (eBGP requires exactly 2 devices in different ASNs)

Adding a new intent: append its name to ``TWO_DEVICE_INTENTS`` (if it
needs exactly two devices) OR to the relevant intent_schemas/*.intent.yaml
(for arbitrary-device intents like static_route_add, vlan_add).
"""
from __future__ import annotations


#: Intents that operate on exactly two devices (a symmetric pair).
#: Editing this set propagates to every downstream renderer/dispatcher.
TWO_DEVICE_INTENTS: frozenset[str] = frozenset({"ebgp_direct"})


def is_two_device_intent(intent_type: str) -> bool:
    """True iff ``intent_type`` requires exactly 2 devices."""
    return intent_type in TWO_DEVICE_INTENTS


def require_two_devices(intent_type: str, devices) -> None:
    """Raise ValueError when ``intent_type`` is a two-device intent
    and ``devices`` is not a list of length 2. No-op otherwise.

    Use this at every dispatch boundary instead of inlining
    ``if len(devices) != 2`` — single source of truth keeps the
    error message consistent and future intent additions don't have
    to edit four files.
    """
    if not is_two_device_intent(intent_type):
        return
    if not isinstance(devices, list) or len(devices) != 2:
        n = len(devices) if isinstance(devices, list) else f"non-list ({type(devices).__name__})"
        raise ValueError(
            f"intent {intent_type!r} requires exactly 2 devices; got {n}"
        )
