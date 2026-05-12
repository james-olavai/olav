"""Derive R88-A / R89 (/ R90) tool arguments from a CabTcf.

These helpers translate a structured TCF into the parametric input
that the deterministic generator tools accept. They're cheap pure
functions — read fields off the model, validate basic compat with
the intent type, raise clear errors when something's missing.

Why these are separate from the tools themselves: the tools live in
``olav-netops/.olav/workspace/netops/lab/tools/`` (MCP tools, language-
agnostic args). The helpers live in ``src/olav/core/cab/`` so any
caller (lab agent, tests, CLI) can derive args without touching the
tool surface.
"""

from __future__ import annotations

from typing import Any

from .tcf_schema import CabTcf


# ISSUE-ARCH-40 (P2, 2026-05-12): both R89 (srl_render) and R90
# (srl_rollback) consume the same shared intent registry, so the two
# aliases here just reference it. Keeping the named aliases preserves
# the existing local-symbol callers (and the public API: tests still
# import these names).
from .intent_registry import TWO_DEVICE_INTENTS as _R89_SUPPORTED_INTENTS
from .intent_registry import TWO_DEVICE_INTENTS as _R90_SUPPORTED_INTENTS


def _lab_name_for(tcf: CabTcf, suffix: str = "") -> str:
    """Build the CLAB lab name from change_id (lowercase, optional suffix)."""
    base = tcf.change_id.lower()
    return f"{base}{suffix}"


def tcf_to_r88_args(tcf: CabTcf, *, lab_name: str | None = None) -> dict[str, Any]:
    """Derive ``generate_clab_topology`` invoke args from a TCF.

    Args:
        tcf: parsed CabTcf
        lab_name: override the auto-derived lab_name (default
            ``<change_id>_lab``)

    Returns:
        dict with ``nodes`` (list of prod device names — uppercase as
        stored) and ``lab_name`` ready for
        ``generate_clab_topology.invoke(...)``. Add other args
        (``image``, ``snapshot_id``) at the call site if needed.
    """
    if not tcf.devices:
        raise ValueError(
            f"TCF {tcf.change_id!r} has no devices — "
            f"generate_clab_topology needs at least 1"
        )
    return {
        "nodes": [d.name for d in tcf.devices],
        "lab_name": lab_name or _lab_name_for(tcf, "_lab"),
    }


def tcf_to_r89_args(tcf: CabTcf) -> dict[str, Any]:
    """Derive ``generate_srl_lab_config`` invoke args from a TCF.

    Pulls 3 parallel arrays (nodes / loopbacks / asns) from
    ``tcf.devices`` and intent_type / lab_subnet from ``tcf.intent``.

    Raises ValueError with a clear message when:
      * intent.type is not in _R89_SUPPORTED_INTENTS
      * any device is missing prod_loopback or prod_asn (R89 needs
        both — sim should populate them when the change requires
        BGP / loopback peering)

    The error path is meant to surface defects at TCF emission time,
    not silently produce wrong configs.
    """
    if tcf.intent.type not in _R89_SUPPORTED_INTENTS:
        raise ValueError(
            f"TCF {tcf.change_id!r}: intent.type {tcf.intent.type!r} "
            f"not supported by R89 (generate_srl_lab_config). "
            f"Supported: {sorted(_R89_SUPPORTED_INTENTS)}. "
            f"Either add a handler to R89 or use a different intent."
        )

    missing: list[str] = []
    for d in tcf.devices:
        if not d.prod_loopback:
            missing.append(f"{d.name}.prod_loopback")
        if d.prod_asn is None:
            missing.append(f"{d.name}.prod_asn")
    if missing:
        raise ValueError(
            f"TCF {tcf.change_id!r}: missing required fields for R89: "
            f"{missing}. R89 needs prod_loopback + prod_asn on every "
            f"device for an ebgp_direct intent."
        )

    args: dict[str, Any] = {
        "nodes": [d.name for d in tcf.devices],
        "loopbacks": [d.prod_loopback for d in tcf.devices],
        "asns": [int(d.prod_asn) for d in tcf.devices],
        "intent_type": tcf.intent.type,
    }

    # Intent extras flow through model_dump (extra="allow")
    intent_extras = tcf.intent.model_dump()
    if "lab_subnet" in intent_extras:
        args["lab_subnet"] = intent_extras["lab_subnet"]

    return args


def tcf_to_r90_args(tcf: CabTcf) -> dict[str, Any]:
    """Derive R90 rollback generator invoke args from a TCF.

    R90 is the rollback counterpart to R89 (Phase 6, future).
    Reads ``tcf.rollback`` blocks rather than ``tcf.implementation``
    and emits SRL ``delete /`` lines for the digital twin.

    Until R90 is implemented this helper validates input shape so
    the future tool can rely on it.
    """
    if tcf.intent.type not in _R90_SUPPORTED_INTENTS:
        raise ValueError(
            f"TCF {tcf.change_id!r}: intent.type {tcf.intent.type!r} "
            f"not yet supported by R90 (rollback generator). "
            f"Supported: {sorted(_R90_SUPPORTED_INTENTS)}."
        )
    if not tcf.rollback:
        raise ValueError(
            f"TCF {tcf.change_id!r}: rollback list is empty — "
            f"R90 needs at least one rollback block to validate. "
            f"Sim should populate rollback alongside implementation."
        )

    # Same parameter shape as R89 — devices facts, plus the rollback
    # block list passed through as the "intent" of the undo.
    base = tcf_to_r89_args(tcf)
    base["rollback_blocks"] = [
        {
            "device": b.device,
            "phase": b.phase,
            "action": b.action,
            "cli": list(b.cli),
        }
        for b in tcf.rollback
    ]
    return base


# ARCH-39 (2026-05-10): the public API names ``tcf_to_r88_args`` etc. are
# keyed by historical OLAV design revision numbers (R88, R89, R90 — three
# milestones during the deterministic-generator refactor). The numbers
# carry no semantic meaning to readers unfamiliar with that history.
# Below are descriptive aliases that NEW code should use; the legacy
# names stay exported for backwards compatibility with downstream
# callers / tests.
tcf_to_clab_topology_args = tcf_to_r88_args
tcf_to_srl_render_args = tcf_to_r89_args
tcf_to_prod_cli_args = tcf_to_r90_args


__all__ = [
    # Legacy (r88/r89/r90 = OLAV design revision numbers; kept for compat)
    "tcf_to_r88_args",
    "tcf_to_r89_args",
    "tcf_to_r90_args",
    # ARCH-39 descriptive aliases — preferred for new code
    "tcf_to_clab_topology_args",
    "tcf_to_srl_render_args",
    "tcf_to_prod_cli_args",
]
