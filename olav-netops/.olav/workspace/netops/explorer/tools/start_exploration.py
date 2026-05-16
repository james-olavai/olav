"""@tool ``start_exploration`` — open a new audit run.

The orchestrator typically calls this once at session start with the
user's prompt's snapshot hint.  Returns a ``run_id`` the LLM uses to
tag all subsequent ``record_finding`` calls.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def start_exploration(
    snapshot_id: str = "",
    requested_by: str = "manual",
    budget_turns: int = 30,
    budget_findings: int = 20,
    budget_wall_sec: int = 1500,
) -> dict:
    """Open a new exploration run; return its ``run_id``.

    Args:
        snapshot_id:      Optional — the netops snapshot being audited.
                          Pass empty to audit the latest available state.
        requested_by:     Who triggered this run (user_id, 'cron', etc.).
        budget_turns:     Hard cap on agent step count (default 30).
        budget_findings:  Hard cap on `record_finding` calls (default 20).
        budget_wall_sec:  Hard cap on wall time in seconds (default 1500 = 25 min).

    Returns:
        ``{"run_id": "<uuid>", "snapshot_id": "<...>"}``
    """
    from olav.core.config import MAIN_DB_PATH
    from olav.core.explorer.scratchpad import start_exploration as _start

    run_id = _start(
        db_path=MAIN_DB_PATH,
        snapshot_id=snapshot_id or "",
        requested_by=requested_by,
        budget_turns=budget_turns,
        budget_findings=budget_findings,
        budget_wall_sec=budget_wall_sec,
    )
    return {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "note": (
            "Use this run_id in all subsequent record_finding / "
            "update_exploration_run calls."
        ),
    }
