"""Per-intent feasibility rules for the Sim stage.

R-CAB-THREE-STAGE Day 3 (2026-05-12, dev_docs/75).

Each ``<intent>.py`` exports a single ``check(draft) → FeasibilityVerdict``.
This module exposes the dispatch:

    >>> from olav.core.cab.sim.feasibility import check_feasibility
    >>> v = check_feasibility(draft)
    >>> v.feasibility  # "OK" or "BLOCKED"

Adding a new intent:
  1. Add the literal name to ``SupportedIntent`` in
     ``olav.core.cab.schemas.draft``.
  2. Create ``sim/feasibility/<intent>.py`` with a ``check()`` function.
  3. Register it in ``CHECKERS`` below.
  4. Add render + renderer dispatch (Day 4 work) under
     ``sim/render/<intent>.py``.
"""
from __future__ import annotations

from typing import Callable

from olav.core.cab.schemas import DraftChangePlan, FeasibilityVerdict

from . import (
    ebgp_direct,
    freeform_cli,
    ibgp_direct,
    static_route_add,
    vlan_add,
)


CHECKERS: dict[str, Callable[[DraftChangePlan], FeasibilityVerdict]] = {
    "ebgp_direct": ebgp_direct.check,
    "ibgp_direct": ibgp_direct.check,
    "static_route_add": static_route_add.check,
    "vlan_add": vlan_add.check,
    "freeform_cli": freeform_cli.check,
}


def check_feasibility(draft: DraftChangePlan) -> FeasibilityVerdict:
    """Dispatch to the per-intent checker.

    The intent is Literal-validated at DraftChangePlan construction
    time, so a KeyError here means an intent was added to
    ``SupportedIntent`` without a corresponding checker.
    """
    try:
        return CHECKERS[draft.proposed_intent](draft)
    except KeyError:  # pragma: no cover — caught by the Literal upstream
        raise KeyError(
            f"no feasibility checker registered for intent "
            f"{draft.proposed_intent!r}; add one in "
            f"olav.core.cab.sim.feasibility/"
        )


__all__ = ["check_feasibility", "CHECKERS"]
