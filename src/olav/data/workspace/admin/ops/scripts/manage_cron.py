#!/usr/bin/env python3
# LEGACY-KEEP: the YAML-path probe below falls back to the pre-2026-05 ops/
# cron layout for installs that predate the ops→netops rename — intentional
# backward-compat, not dead code.
"""
Cron Management Tool — manage system crontab entries for olav scheduled tasks.

All managed entries call the olav CLI:
    olav --agent <agent> --auto-approve "<instruction>"

Entries are tagged with a comment prefix "olav:" for safe management
(only olav-tagged entries are modified/removed).

Usage:
    list_cron()                                → list all olav-managed cron jobs
    add_cron(schedule, agent, instruction)     → add or update a job
    remove_cron(job_id)                        → remove by job_id
    apply_cron_schedules(yaml_path)            → apply cron_schedules.yaml declaratively
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from crontab import CronTab

_COMMENT_PREFIX = "olav:"
_OLAV_BIN = shutil.which("olav") or "olav"


def _get_project_root() -> Path:
    """Resolve project root: OLAV_HOME env > walk up from cwd looking for pyproject.toml > cwd."""
    if home := os.getenv("OLAV_HOME"):
        return Path(home)
    p = Path.cwd()
    for candidate in [p, *p.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return p


def _get_crontab() -> CronTab:
    return CronTab(user=True)


def _job_to_dict(job) -> dict:
    comment = str(job.comment)
    parts = comment.removeprefix(_COMMENT_PREFIX).split("|", 2)
    agent = parts[0].strip() if len(parts) > 0 else ""
    instruction = parts[1].strip() if len(parts) > 1 else ""
    return {
        "job_id": comment,
        "agent": agent,
        "instruction": instruction,
        "schedule": str(job.slices),
        "command": str(job.command),
        "enabled": job.is_enabled(),
    }


def _find_job(cron: CronTab, agent: str, instruction: str):
    comment = f"{_COMMENT_PREFIX}{agent}|{instruction}"
    for job in cron.find_comment(comment):
        return job
    return None


def list_cron() -> dict[str, Any]:
    """List all olav-managed cron jobs."""
    cron = _get_crontab()
    jobs = [_job_to_dict(j) for j in cron if str(j.comment).startswith(_COMMENT_PREFIX)]
    return {"count": len(jobs), "jobs": jobs}


def add_cron(schedule: str, agent: str, instruction: str) -> dict[str, Any]:
    """Add or update an olav cron job.

    Args:
        schedule: Standard cron expression, e.g. "0 2 * * *"
        agent: olav agent name, e.g. "config", "audit", "ops"
        instruction: Natural language instruction passed to the agent, e.g. "take snapshot"
    """
    cron = _get_crontab()
    comment = f"{_COMMENT_PREFIX}{agent}|{instruction}"
    project_root = _get_project_root()
    # `mkdir -p ~/.olav/logs` on every fire: `olav init` creates the PROJECT
    # .olav/logs, not $HOME/.olav/logs, so without this the `>>` redirect target
    # dir is missing → the shell fails the redirect and the job never runs (it
    # silently no-ops every day). Creating it inline is robust even if the dir
    # is removed after the job is registered.
    command = (
        f'mkdir -p ~/.olav/logs && cd {project_root} && '
        f'{_OLAV_BIN} --agent {agent} --auto-approve "{instruction}" '
        f'>> ~/.olav/logs/cron_{agent}.log 2>&1'
    )

    existing = _find_job(cron, agent, instruction)
    if existing:
        previous_schedule = str(existing.slices)
        existing.setall(schedule)
        action = "updated"
        undo_kind, undo_data = "cron_update", {
            "comment": comment,
            "previous_schedule": previous_schedule,
        }
    else:
        job = cron.new(command=command, comment=comment)
        job.setall(schedule)
        action = "added"
        undo_kind, undo_data = "cron_add", {"comment": comment}

    cron.write()
    undo_recorded = _record_undo(undo_kind, f"{action} cron job {comment!r}", undo_data)
    return {
        "status": "ok",
        "action": action,
        "agent": agent,
        "instruction": instruction,
        "schedule": schedule,
        "undo_recorded": undo_recorded,
    }


def remove_cron(agent: str, instruction: str) -> dict[str, Any]:
    """Remove an olav-managed cron job by agent + instruction.

    Args:
        agent: olav agent name
        instruction: Instruction text used when the job was created
    """
    cron = _get_crontab()
    job = _find_job(cron, agent, instruction)
    if not job:
        return {"status": "not_found", "agent": agent, "instruction": instruction}
    removed_spec = {
        "comment": str(job.comment),
        "schedule": str(job.slices),
        "command": str(job.command),
    }
    cron.remove(job)
    cron.write()
    undo_recorded = _record_undo(
        "cron_remove", f"removed cron job {removed_spec['comment']!r}", removed_spec
    )
    return {
        "status": "ok",
        "action": "removed",
        "agent": agent,
        "instruction": instruction,
        "undo_recorded": undo_recorded,
    }


def _record_undo(kind: str, description: str, data: dict[str, Any]) -> bool:
    """Journal the mutation for undo_last_action (dev_docs/99 §7.4).
    Soft-fails — a broken journal must not fail the cron change itself;
    the ``undo_recorded`` result field tells the agent whether "undo"
    is actually available."""
    try:
        from olav.core.undo_journal import record_action

        return record_action(kind, description, data)
    except Exception:  # noqa: BLE001
        return False


def apply_cron_schedules(yaml_path: str = "") -> dict[str, Any]:
    """Apply cron_schedules.yaml declaratively — add/update all declared jobs.

    Args:
        yaml_path: Path to cron_schedules.yaml. Defaults to .olav/workspace/netops/netops_init/config/cron_schedules.yaml
    """
    if not yaml_path:
        root = Path(__file__).resolve().parents[4]
        # Probe netops/ first (current canonical layout); fall back to
        # the legacy ops/ paths for pre-2026-05 installs.
        candidates = [
            root / ".olav/workspace/netops/netops_init/config/cron_schedules.yaml",
            root / ".olav/workspace/ops/netops_init/config/cron_schedules.yaml",
            root / ".olav/workspace/ops/config/cron_schedules.yaml",
        ]
        yaml_path = str(next((p for p in candidates if p.exists()), candidates[0]))

    path = Path(yaml_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {yaml_path}"}

    data = yaml.safe_load(path.read_text())
    schedules = data.get("schedules", {})

    results = []
    for name, cfg in schedules.items():
        cron_expr = cfg.get("cron", "")
        agent = cfg.get("agent", "config")
        instruction = cfg.get("instruction", name)
        if not cron_expr:
            results.append({"name": name, "status": "skipped", "reason": "no cron expression"})
            continue
        result = add_cron(schedule=cron_expr, agent=agent, instruction=instruction)
        results.append({"name": name, **result})

    return {"status": "ok", "applied": len(results), "results": results}


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    action = _args.pop("action", "list")
    dispatch = {"list": list_cron, "add": add_cron, "remove": remove_cron, "apply": apply_cron_schedules}
    fn = dispatch.get(action)
    if fn is None:
        print(_json.dumps({"status": "error", "error": f"unknown action {action!r}"}))
    else:
        print(_json.dumps(fn(**_args), default=str))
