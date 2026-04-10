#!/usr/bin/env python3
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
from langchain_core.tools import tool

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


@tool
def list_cron() -> dict[str, Any]:
    """List all olav-managed cron jobs."""
    cron = _get_crontab()
    jobs = [_job_to_dict(j) for j in cron if str(j.comment).startswith(_COMMENT_PREFIX)]
    return {"count": len(jobs), "jobs": jobs}


@tool
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
    command = f'cd {project_root} && {_OLAV_BIN} --agent {agent} --auto-approve "{instruction}" >> ~/.olav/logs/cron_{agent}.log 2>&1'

    existing = _find_job(cron, agent, instruction)
    if existing:
        existing.setall(schedule)
        action = "updated"
    else:
        job = cron.new(command=command, comment=comment)
        job.setall(schedule)
        action = "added"

    cron.write()
    return {"status": "ok", "action": action, "agent": agent, "instruction": instruction, "schedule": schedule}


@tool
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
    cron.remove(job)
    cron.write()
    return {"status": "ok", "action": "removed", "agent": agent, "instruction": instruction}


@tool
def apply_cron_schedules(yaml_path: str = "") -> dict[str, Any]:
    """Apply cron_schedules.yaml declaratively — add/update all declared jobs.

    Args:
        yaml_path: Path to cron_schedules.yaml. Defaults to .olav/workspace/ops/netops_init/config/cron_schedules.yaml
    """
    if not yaml_path:
        root = Path(__file__).resolve().parents[4]
        # Post-M3: netops_init/config/ is canonical; fall back to legacy ops/config/
        new_path = root / ".olav/workspace/ops/netops_init/config/cron_schedules.yaml"
        legacy_path = root / ".olav/workspace/ops/config/cron_schedules.yaml"
        yaml_path = str(new_path if new_path.exists() else legacy_path)

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
        result = add_cron.invoke({"schedule": cron_expr, "agent": agent, "instruction": instruction})
        results.append({"name": name, **result})

    return {"status": "ok", "applied": len(results), "results": results}
