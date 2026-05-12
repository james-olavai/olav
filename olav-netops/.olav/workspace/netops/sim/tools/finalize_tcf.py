"""finalize_tcf @tool — thin wrapper around the sim.finalize entry-point.

R-CAB-THREE-STAGE Day 4 (2026-05-12, dev_docs/75).

The Python work lives in ``olav.core.cab.sim.finalize.finalize_tcf_from_draft``;
this @tool is just the workspace-side hook that lets the orchestrator
dispatch via ``task("sim", "finalize", {"draft_path": ...})``.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
def finalize_tcf(draft_path: str) -> dict[str, Any]:
    """Finalize a draft into a TCF spec (or a structured rejection).

    Args:
        draft_path: Path to the Analyzer-produced ``draft.yaml``,
            typically ``exports/cab/<change_id>/draft.yaml``.

    Returns:
        One of:
          - ``{"status": "ok", "spec_path": "...",
                "next_step": {"action": "lab_validate", ...}}``
          - ``{"status": "rejected", "rejection_path": "...",
                "blockers": [...],
                "next_step": {"action": "analyzer_revise", ...}}``
          - ``{"status": "error", "error": "..."}``

    NEVER raises. Errors are surfaced via the envelope.
    """
    from olav.core.cab.sim.finalize import finalize_tcf_from_draft
    return finalize_tcf_from_draft(draft_path)
