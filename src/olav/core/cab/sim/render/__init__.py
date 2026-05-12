"""Native render layer — DraftChangePlan → CabTcf.

R-CAB-THREE-STAGE Day 4 deferred + 2026-05-13 cleanup:
The legacy ``tcf_writer.render_tcf_from_change_plan`` adapter is
gone. Each intent has a native renderer that reads ONLY from the
draft's typed envelope (devices, facts_collected, intent_args) and
produces a Pydantic ``CabTcf`` — no DB queries, no plan_md string
intermediate, no LLM call.

Adding a new intent renderer:
  1. Create ``render/<intent>.py`` with ``render(draft, lab_subnet)
     → CabTcf``.
  2. Register in ``RENDERERS`` below.
"""
from __future__ import annotations

from typing import Callable

from olav.core.cab.schemas import DraftChangePlan
from olav.core.cab.tcf_schema import CabTcf

from . import freeform_cli


RENDERERS: dict[str, Callable[[DraftChangePlan, str], CabTcf]] = {
    "freeform_cli": freeform_cli.render,
}


def render_spec(draft: DraftChangePlan, lab_subnet: str, change_id: str) -> CabTcf:
    """Dispatch to the per-intent native renderer.

    Raises KeyError for intents without a native renderer (yet) — the
    caller can fall back to legacy for the transition window.
    """
    fn = RENDERERS[draft.proposed_intent]
    return fn(draft, lab_subnet, change_id)


__all__ = ["RENDERERS", "render_spec"]
