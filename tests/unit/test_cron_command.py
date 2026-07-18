"""Tests for `olav cron` (opt-in activation of declared scheduled jobs) +
the init/doctor hints that point at it.

The scheduled self-reflection job must be reachable via an EXPLICIT command
(never auto-written to the user's crontab by init). These prove the command
is registered, routes to manage_cron correctly, and that init/doctor surface
the opt-in.
"""
from __future__ import annotations

import asyncio

import pytest

from olav.cli.commands import cron as cron_mod
from olav.cli.commands.cron import CronCommand


class _FakeMC:
    """Stand-in for the manage_cron skill module."""

    def __init__(self, jobs=None):
        self.jobs = jobs or []
        self.added = []
        self.removed = []

    def list_cron(self):
        return {"count": len(self.jobs), "jobs": self.jobs}

    def add_cron(self, schedule, agent, instruction):
        self.added.append((schedule, agent, instruction))
        return {"status": "ok", "action": "added"}

    def remove_cron(self, agent, instruction):
        self.removed.append((agent, instruction))
        return {"status": "ok", "action": "removed"}


_SCHEDULES = {
    "reflect": {"cron": "0 4 * * *", "agent": "admin",
                "instruction": "reflect on today's errors and propose improvements"},
    "snapshot": {"cron": "0 2 * * *", "agent": "config", "instruction": "take snapshot"},
}


@pytest.fixture
def patched(monkeypatch):
    mc = _FakeMC()
    monkeypatch.setattr(cron_mod, "_load_manage_cron", lambda: mc)
    monkeypatch.setattr(cron_mod, "_load_schedules", lambda: dict(_SCHEDULES))
    return mc


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── registration: cron is a known command (not routed to the agent) ───────
def test_cron_is_a_known_command():
    from olav.cli.main import _KNOWN_COMMANDS

    assert "cron" in _KNOWN_COMMANDS, (
        "cron missing from _KNOWN_COMMANDS → `olav cron ...` would misroute to "
        "the natural-language agent path instead of dispatching"
    )


# ── enable by name activates ONLY that job ────────────────────────────────
def test_enable_single_job_adds_only_it(patched):
    out = _run(CronCommand().execute("enable", "reflect"))
    assert patched.added == [
        ("0 4 * * *", "admin", "reflect on today's errors and propose improvements")
    ]
    assert "reflect" in out and "0 4 * * *" in out
    # disclosure that this schedules a recurring LLM job
    assert "daily LLM call" in out


def test_enable_all_adds_every_declared_job(patched):
    _run(CronCommand().execute("enable", None))
    added_names = {a[2] for a in patched.added}
    assert "take snapshot" in added_names
    assert any("reflect" in n for n in added_names)


def test_enable_unknown_name_is_rejected(patched):
    out = _run(CronCommand().execute("enable", "nope"))
    assert "no schedule named" in out.lower()
    assert patched.added == []


# ── list / disable ────────────────────────────────────────────────────────
def test_list_empty_points_at_enable(patched):
    out = _run(CronCommand().execute("list"))
    assert "olav cron enable reflect" in out


def test_disable_all_removes_active_jobs(monkeypatch):
    mc = _FakeMC(jobs=[
        {"schedule": "0 4 * * *", "agent": "admin",
         "instruction": "reflect on today's errors and propose improvements"},
    ])
    monkeypatch.setattr(cron_mod, "_load_manage_cron", lambda: mc)
    monkeypatch.setattr(cron_mod, "_load_schedules", lambda: dict(_SCHEDULES))
    out = _run(CronCommand().execute("disable", None))
    assert mc.removed == [
        ("admin", "reflect on today's errors and propose improvements")
    ]
    assert "disabled 1" in out


# ── the cron command line must self-create its log dir ────────────────────
def test_manage_cron_command_creates_log_dir():
    """add_cron's crontab line must `mkdir -p ~/.olav/logs` before the `>>`
    redirect — `olav init` creates the PROJECT .olav/logs, not $HOME/.olav/logs,
    so without this every cron job silently no-ops (the shell fails the redirect
    and never runs the command). Regression guard for a silent-failure bug."""
    src = (
        REPO_SRC := __import__("pathlib").Path(__file__).resolve().parents[1].parent
        / "src/olav/data/workspace/admin/ops/scripts/manage_cron.py"
    ).read_text()
    assert "mkdir -p ~/.olav/logs" in src, (
        "manage_cron add_cron must create ~/.olav/logs inline or cron jobs "
        "silently fail the log redirect and never run"
    )


# ── init + doctor surface the opt-in hint ─────────────────────────────────
def test_init_and_doctor_emit_cron_hint():
    from olav.cli.commands.doctor import DoctorCommand
    from olav.cli.commands.init import InitCommand

    for hint in (InitCommand()._cron_hint(), DoctorCommand()._cron_hint()):
        # either points at the enable command, or reports active jobs
        assert "cron enable reflect" in hint or "active" in hint
