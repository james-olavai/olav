#!/usr/bin/env python3
"""undo_last_action — revert the most recent journaled agent write-action.

dev_docs/99 §7.4: extends rollback_config's explicit-undo philosophy to the
other write paths — workspace file writes (write_workspace_file) and cron
mutations (manage_cron). Those scripts journal each change; this one pops
and reverts the newest entry. Single-step, most-recent-first; call again
to undo the action before it.

NOT covered here: LLM/embedding config — that has its own validated path
(rollback_config). Use the right one for the user's actual request.

Usage:
    undo_last_action()                → revert the most recent action
    undo_last_action(list_only=True)  → preview what would be undone
"""

from __future__ import annotations

import sys
from pathlib import Path


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))


def undo_last_action(list_only: bool = False) -> dict:
    """Revert (or preview) the most recent undoable agent action.

    Args:
        list_only: When True, return the pending undoable actions
                   (most-recent-first) without reverting anything.

    Returns:
        list_only → {"actions": [...]}; otherwise the undo result:
        {"undone": bool, "message": str, ...}
    """
    from olav.core.undo_journal import list_actions, undo_last

    if list_only:
        return {"actions": list_actions()}
    return undo_last()


if __name__ == "__main__":
    import json as _json

    _args = _json.loads(sys.stdin.read() or "{}")
    print(_json.dumps(undo_last_action(**_args), ensure_ascii=False, default=str))
