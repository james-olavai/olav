#!/usr/bin/env python3
"""Mark an exploration run as completed and record the report path.

Call this as the final step after format_and_export has written
the markdown report.  Transitions the run from 'in_progress' to
'completed' so downstream agents can query
  SELECT * FROM netops.exploration_runs WHERE status = 'completed'
to find finished investigations.

Args (JSON via stdin):
    run_id             str  — from start_exploration (required)
    final_report_path  str  — absolute or relative path to the markdown report (optional)
    turns_used         int  — number of tool-call turns consumed (optional)

Output JSON:
    status  str  — "completed"
    run_id  str  — echo of the input run_id
"""
from __future__ import annotations

import json
import sys

from olav.core.config import MAIN_DB_PATH
from olav.core.explorer.scratchpad import update_exploration_run


def main() -> None:
    raw = sys.stdin.read().strip()
    args: dict = json.loads(raw) if raw else {}

    run_id: str = args["run_id"]
    final_report_path: str | None = args.get("final_report_path")
    turns_used: int | None = args.get("turns_used")

    update_exploration_run(
        db_path=MAIN_DB_PATH,
        run_id=run_id,
        status="completed",
        final_report_path=final_report_path,
        turns_used=turns_used,
    )
    print(json.dumps({"status": "completed", "run_id": run_id}))


if __name__ == "__main__":
    main()
