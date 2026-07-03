"""Undo journal — generalized "undo my last action" for agent write-actions
(dev_docs/99 §7.4).

``rollback_config`` (§3.5) covers LLM/embedding config only. This journal
extends the same explicit-undo philosophy to the other agent write paths —
workspace file writes and cron mutations — without any automatic
reverting: an entry is recorded at write time by the acting script, and
reverted only when a user/agent explicitly asks ("undo that").

Storage: one JSON file per action under ``.olav/run/undo/`` (runtime dir,
never committed), capped at the most recent ``_MAX_ENTRIES``. Undo pops
the newest entry, applies the kind-specific revert, and deletes the entry
on success — single-step, most-recent-first, matching ``rollback_config``'s
one-slot semantics rather than a full history tree.

Supported kinds:
- ``file_write``  — data: {path, existed, previous_content}
- ``cron_add``    — data: {comment}
- ``cron_update`` — data: {comment, previous_schedule}
- ``cron_remove`` — data: {comment, schedule, command}
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 20

_UNDO_DIR_OVERRIDE: Path | None = None
"""Test seam — set to a tmp dir to isolate journal state."""


def _undo_dir() -> Path:
    if _UNDO_DIR_OVERRIDE is not None:
        return _UNDO_DIR_OVERRIDE
    from olav.core.config import CONFIG_DIR

    return Path(CONFIG_DIR).parent / "run" / "undo"


def _project_root() -> Path:
    from olav.core.config import CONFIG_DIR

    return Path(CONFIG_DIR).parent.parent


def record_action(kind: str, description: str, data: dict[str, Any]) -> bool:
    """Append one undoable action to the journal. Returns False on failure
    (callers surface ``undo_recorded: false`` rather than failing the write
    itself — but must not silently claim undo coverage that doesn't exist).
    """
    try:
        undo_dir = _undo_dir()
        undo_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "kind": kind,
            "description": description,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
        }
        (undo_dir / f"{time.time_ns()}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Cap: prune oldest beyond _MAX_ENTRIES.
        entries = sorted(undo_dir.glob("*.json"))
        for stale in entries[:-_MAX_ENTRIES]:
            stale.unlink(missing_ok=True)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("undo_journal.record_action failed: %s", exc)
        return False


def list_actions(limit: int = 5) -> list[dict[str, Any]]:
    """Most-recent-first summaries of undoable actions."""
    try:
        entries = sorted(_undo_dir().glob("*.json"), reverse=True)[:limit]
        out = []
        for path in entries:
            e = json.loads(path.read_text(encoding="utf-8"))
            out.append({
                "kind": e.get("kind"),
                "description": e.get("description"),
                "created_at": e.get("created_at"),
            })
        return out
    except Exception:  # noqa: BLE001
        return []


def undo_last() -> dict[str, Any]:
    """Revert the most recent journaled action.

    Returns ``{"undone": bool, "message": str, ...}``. On revert failure
    the entry is kept (retryable after the user fixes the environment);
    on success it is deleted so the next call undoes the action before it.
    """
    try:
        entries = sorted(_undo_dir().glob("*.json"), reverse=True)
    except Exception:  # noqa: BLE001
        entries = []
    if not entries:
        return {"undone": False, "message": "Nothing to undo — the undo journal is empty."}

    entry_path = entries[0]
    try:
        entry = json.loads(entry_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        entry_path.unlink(missing_ok=True)  # unreadable entry is unrecoverable
        return {"undone": False, "message": f"Latest undo entry was unreadable and was discarded: {exc}"}

    kind = entry.get("kind", "")
    handler = _HANDLERS.get(kind)
    if handler is None:
        return {
            "undone": False,
            "message": f"Don't know how to undo kind {kind!r} — entry kept for manual handling.",
        }

    try:
        message = handler(entry.get("data") or {})
    except Exception as exc:  # noqa: BLE001
        return {
            "undone": False,
            "message": f"Undo of “{entry.get('description', kind)}” failed: {exc}. Entry kept — retry after fixing the cause.",
        }

    entry_path.unlink(missing_ok=True)
    return {
        "undone": True,
        "description": entry.get("description", ""),
        "message": message,
    }


# ── kind handlers ────────────────────────────────────────────────────────────


def _undo_file_write(data: dict[str, Any]) -> str:
    path = Path(data["path"])
    # Defense in depth: only ever restore inside the project root — same
    # containment write_workspace_file enforced when the entry was recorded.
    path.resolve().relative_to(_project_root().resolve())
    if data.get("existed"):
        path.write_text(data.get("previous_content") or "", encoding="utf-8")
        return f"Restored previous content of {path}."
    path.unlink(missing_ok=True)
    return f"Removed {path} (it did not exist before the undone write)."


def _get_crontab():
    from crontab import CronTab

    return CronTab(user=True)


def _undo_cron_add(data: dict[str, Any]) -> str:
    cron = _get_crontab()
    comment = data["comment"]
    removed = 0
    for job in list(cron.find_comment(comment)):
        cron.remove(job)
        removed += 1
    if not removed:
        return f"Cron job {comment!r} was already gone — nothing to remove."
    cron.write()
    return f"Removed cron job {comment!r}."


def _undo_cron_update(data: dict[str, Any]) -> str:
    cron = _get_crontab()
    comment = data["comment"]
    for job in cron.find_comment(comment):
        job.setall(data["previous_schedule"])
        cron.write()
        return f"Restored schedule of cron job {comment!r} to {data['previous_schedule']!r}."
    return f"Cron job {comment!r} no longer exists — nothing to restore."


def _undo_cron_remove(data: dict[str, Any]) -> str:
    cron = _get_crontab()
    job = cron.new(command=data["command"], comment=data["comment"])
    job.setall(data["schedule"])
    cron.write()
    return f"Re-added cron job {data['comment']!r} ({data['schedule']})."


_HANDLERS = {
    "file_write": _undo_file_write,
    "cron_add": _undo_cron_add,
    "cron_update": _undo_cron_update,
    "cron_remove": _undo_cron_remove,
}
