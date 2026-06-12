"""Workspace multi-copy sync gate.

The two-workspace sync rule (CLAUDE.md) requires every workspace
agent's source / runtime / bundle copies to stay byte-identical.
History shows manual discipline fails: the audit SKILL.md drifted
unnoticed for a week, and 60eba6f7 committed *different* wording to
two copies in a single commit. scripts/workspace_drift.py detects
this, but until 2026-06-12 nothing ran it automatically — this gate
makes every governance run a drift check, so divergence is caught at
test time instead of during the next incident.

Missing dirs (e.g. runtime before `olav init`, retired domains) are
skipped by the script itself, so this passes on a fresh checkout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_workspace_copies_in_sync():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "workspace_drift.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=120,
    )
    assert proc.returncode == 0, (
        "workspace copies have drifted — run `python scripts/workspace_drift.py` "
        "and sync (always edit source + runtime + bundle together):\n"
        + proc.stdout[-3000:]
    )
