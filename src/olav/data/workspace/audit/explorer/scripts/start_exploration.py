#!/usr/bin/env python3
"""Start a new structured exploration run; returns run_id.

Opens a session row in netops.exploration_runs so every subsequent
record_finding call can be linked to this investigation.  Call this
after the SURVEY step when you have a snapshot_id anchor.

Args (JSON via stdin):
    snapshot_id  str  — snapshot_id from v_snapshots_auto (anchor for the run)
    requested_by str  — caller label, e.g. "explorer" (default)
    budget_turns int  — max turns before auto-abort (default 30)
    budget_findings int — max findings to record (default 20)

Output JSON:
    run_id   str  — opaque ID to pass to every record_finding call
    status   str  — "started"
"""
from __future__ import annotations

import json
import sys

from olav.core.config import MAIN_DB_PATH
from olav.core.explorer.scratchpad import start_exploration


def main() -> None:
    raw = sys.stdin.read().strip()
    args: dict = json.loads(raw) if raw else {}

    snapshot_id: str = args.get("snapshot_id") or "unknown"
    requested_by: str = args.get("requested_by") or "explorer"
    budget_turns: int = int(args.get("budget_turns") or 30)
    budget_findings: int = int(args.get("budget_findings") or 20)

    run_id = start_exploration(
        db_path=MAIN_DB_PATH,
        snapshot_id=snapshot_id,
        requested_by=requested_by,
        budget_turns=budget_turns,
        budget_findings=budget_findings,
    )
    print(json.dumps({"run_id": run_id, "status": "started"}))


if __name__ == "__main__":
    main()
