"""``olav cron`` — enable / disable / list scheduled self-management jobs.

A thin, discoverable front door to the declarative ``cron_schedules.yaml``
(daily self-reflection, snapshot, trace-learner, weekly audit). The schedules
ship with the workspace at ``olav init`` but are NEVER auto-written to the
user's crontab — activating a recurring job that shells ``olav --auto-approve``
(a daily LLM call, and for ``snapshot`` live-device SSH) is an explicit opt-in.
This command is that opt-in:

    olav cron enable            # activate all declared jobs (prints each)
    olav cron enable reflect    # activate just the daily self-reflection
    olav cron list              # show currently active olav cron jobs
    olav cron disable [name]    # remove all, or one, olav cron jobs

The heavy lifting (crontab mutation + undo journaling) lives in the admin/ops
``manage_cron`` skill script; this only resolves the schedule config and
routes to it, so there is one source of truth for cron mechanics.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import yaml


def _load_manage_cron():
    """Import the manage_cron skill script (deployed workspace first, then the
    packaged copy) so cron mechanics stay in one place."""
    candidates = [
        Path(".olav/workspace/admin/ops/scripts/manage_cron.py"),
        Path(__file__).resolve().parents[2]
        / "data/workspace/admin/ops/scripts/manage_cron.py",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise FileNotFoundError("manage_cron.py not found (run `olav init` first)")
    spec = importlib.util.spec_from_file_location("_olav_manage_cron", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_schedules_yaml() -> Path | None:
    candidates = [
        Path(".olav/workspace/netops/netops_init/config/cron_schedules.yaml"),
        Path(__file__).resolve().parents[2]
        / "data/workspace/netops/netops_init/config/cron_schedules.yaml",
    ]
    return next((p for p in candidates if p.exists()), None)


def _load_schedules() -> dict[str, dict[str, Any]]:
    p = _resolve_schedules_yaml()
    if p is None:
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("schedules", {}) or {}


class CronCommand:
    async def execute(self, action: str = "list", name: str | None = None) -> str:
        try:
            mc = _load_manage_cron()
        except Exception as exc:  # noqa: BLE001
            return f"⚠ cron unavailable: {exc}"

        if action == "list":
            return self._list(mc)
        if action == "enable":
            return self._enable(mc, name)
        if action == "disable":
            return self._disable(mc, name)
        return f"⚠ unknown cron action {action!r} (use enable / disable / list)"

    # ── list ─────────────────────────────────────────────────────────────
    def _list(self, mc) -> str:
        r = mc.list_cron()
        jobs = r.get("jobs", [])
        if not jobs:
            return (
                "no olav cron jobs active.\n"
                "enable the daily self-reflection with: olav cron enable reflect\n"
                "or all declared jobs with:            olav cron enable"
            )
        lines = [f"active olav cron jobs ({len(jobs)}):"]
        for j in jobs:
            lines.append(
                f"  {j.get('schedule', '?'):<12} {j.get('agent', '?'):<8} "
                f"{j.get('instruction', j.get('comment', ''))}"
            )
        return "\n".join(lines)

    # ── enable ───────────────────────────────────────────────────────────
    def _enable(self, mc, name: str | None) -> str:
        schedules = _load_schedules()
        if not schedules:
            return "⚠ no cron_schedules.yaml found (run `olav init` first)"
        if name is not None:
            if name not in schedules:
                return (
                    f"⚠ no schedule named {name!r}. Available: "
                    + ", ".join(sorted(schedules))
                )
            selected = {name: schedules[name]}
        else:
            selected = schedules

        results = []
        for jn, cfg in selected.items():
            cron_expr = cfg.get("cron", "")
            agent = cfg.get("agent", "config")
            instruction = cfg.get("instruction", jn)
            if not cron_expr:
                results.append(f"  ⚠ {jn}: no cron expression — skipped")
                continue
            r = mc.add_cron(schedule=cron_expr, agent=agent, instruction=instruction)
            status = r.get("status", "?")
            results.append(f"  ✓ {jn}: {cron_expr} (agent={agent}) [{status}]")
        header = (
            f"enabled cron job '{name}':" if name
            else "enabled all declared cron jobs (each runs `olav --auto-approve`):"
        )
        note = (
            "\nnote: these run a daily LLM call; `snapshot` also SSHes to live "
            "devices. Disable any with: olav cron disable <name>"
        )
        return header + "\n" + "\n".join(results) + note

    # ── disable ──────────────────────────────────────────────────────────
    def _disable(self, mc, name: str | None) -> str:
        if name is not None:
            schedules = _load_schedules()
            if name not in schedules:
                return f"⚠ no schedule named {name!r}"
            cfg = schedules[name]
            r = mc.remove_cron(
                agent=cfg.get("agent", "config"),
                instruction=cfg.get("instruction", name),
            )
            status = r.get("status")
            ok = status in ("ok", "success", "removed")
            return f"{'✓ disabled' if ok else '⚠'} {name}: {status}"
        # remove all olav-managed jobs
        listed = mc.list_cron().get("jobs", [])
        if not listed:
            return "no olav cron jobs to disable."
        removed = 0
        for j in listed:
            agent = j.get("agent")
            instr = j.get("instruction")
            if agent and instr:
                if mc.remove_cron(agent=agent, instruction=instr).get("status") in (
                    "ok", "success", "removed"
                ):
                    removed += 1
        return f"✓ disabled {removed} olav cron job(s)."
