"""@tool ``update_exploration_run`` — budget / status bookkeeping.

Called at the end of REPORT phase to finalise the run, and any time
during the run to bump ``turns_used`` / ``wall_sec_used`` counters.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def update_exploration_run(
    run_id: str,
    status: str | None = None,
    turns_used: int | None = None,
    wall_sec_used: int | None = None,
    final_report_path: str | None = None,
) -> dict:
    """Update fields on the exploration_runs row.

    Args:
        run_id:            From start_exploration().
        status:            ``in_progress`` / ``completed`` / ``aborted`` /
                           ``timeout``.  Setting to a terminal value
                           (completed/aborted/timeout) auto-sets ended_at.
        turns_used:        Optional bump.
        wall_sec_used:     Optional bump.
        final_report_path: Path to the saved markdown report (e.g.
                           ``exports/reports/explore_<id>.md``).

    Returns:
        ``{"updated": True}``.
    """
    from olav.core.config import MAIN_DB_PATH
    from olav.core.explorer.scratchpad import update_exploration_run as _update

    _update(
        db_path=MAIN_DB_PATH,
        run_id=run_id, status=status,
        turns_used=turns_used, wall_sec_used=wall_sec_used,
        final_report_path=final_report_path,
    )
    return {"updated": True}
