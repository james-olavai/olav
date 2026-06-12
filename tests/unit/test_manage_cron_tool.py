from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


REPO = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO / ".olav" / "workspace" / "admin" / "ops" / "scripts" / "manage_cron.py"


class FakeJob:
    def __init__(self, comment: str, schedule: str, command: str = "echo hi", enabled: bool = True):
        self.comment = comment
        self.slices = schedule
        self.command = command
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def setall(self, schedule: str) -> None:
        self.slices = schedule


class FakeCron:
    def __init__(self, jobs=None):
        self.jobs = list(jobs or [])
        self.write_calls = 0

    def __iter__(self):
        return iter(self.jobs)

    def find_comment(self, comment: str):
        return (j for j in self.jobs if j.comment == comment)

    def new(self, command: str, comment: str):
        job = FakeJob(comment=comment, schedule="", command=command)
        self.jobs.append(job)
        return job

    def remove(self, job) -> None:
        self.jobs.remove(job)

    def write(self) -> None:
        self.write_calls += 1


def _load_module(modname: str):
    spec = importlib.util.spec_from_file_location(modname, TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("crontab", SimpleNamespace(CronTab=object))
    spec.loader.exec_module(mod)
    return mod


def test_list_cron_filters_to_olav_prefixed_jobs(monkeypatch):
    tool_mod = _load_module("_test_manage_cron_list")
    cron = FakeCron(
        [
            FakeJob(comment="olav:audit|take snapshot", schedule="0 2 * * *"),
            FakeJob(comment="backup:nightly", schedule="0 1 * * *"),
        ]
    )
    monkeypatch.setattr(tool_mod, "_get_crontab", lambda: cron)

    out = tool_mod.list_cron()

    assert out["count"] == 1
    assert out["jobs"][0]["job_id"] == "olav:audit|take snapshot"
    assert out["jobs"][0]["agent"] == "audit"


def test_add_cron_updates_existing_job(monkeypatch):
    tool_mod = _load_module("_test_manage_cron_add_update")
    existing = FakeJob(comment="olav:ops|rotate logs", schedule="0 1 * * *")
    cron = FakeCron([existing])

    monkeypatch.setattr(tool_mod, "_get_crontab", lambda: cron)
    monkeypatch.setattr(tool_mod, "_get_project_root", lambda: Path("/repo"))
    monkeypatch.setattr(tool_mod, "_OLAV_BIN", "olav")

    out = tool_mod.add_cron(schedule="*/5 * * * *", agent="ops", instruction="rotate logs")

    assert out["status"] == "ok"
    assert out["action"] == "updated"
    assert existing.slices == "*/5 * * * *"
    assert len(cron.jobs) == 1
    assert cron.write_calls == 1


def test_add_cron_creates_new_job(monkeypatch):
    tool_mod = _load_module("_test_manage_cron_add_create")
    cron = FakeCron([])

    monkeypatch.setattr(tool_mod, "_get_crontab", lambda: cron)
    monkeypatch.setattr(tool_mod, "_get_project_root", lambda: Path("/repo"))
    monkeypatch.setattr(tool_mod, "_OLAV_BIN", "olav")

    out = tool_mod.add_cron(schedule="0 4 * * *", agent="audit", instruction="take snapshot")

    assert out["action"] == "added"
    assert len(cron.jobs) == 1
    new_job = cron.jobs[0]
    assert new_job.slices == "0 4 * * *"
    assert new_job.comment == "olav:audit|take snapshot"
    assert "cd /repo && olav --agent audit --auto-approve" in new_job.command
    assert cron.write_calls == 1


def test_remove_cron_not_found(monkeypatch):
    tool_mod = _load_module("_test_manage_cron_remove_missing")
    cron = FakeCron([])
    monkeypatch.setattr(tool_mod, "_get_crontab", lambda: cron)

    out = tool_mod.remove_cron(agent="ops", instruction="missing")

    assert out == {"status": "not_found", "agent": "ops", "instruction": "missing"}
    assert cron.write_calls == 0


def test_remove_cron_removed(monkeypatch):
    tool_mod = _load_module("_test_manage_cron_remove_ok")
    job = FakeJob(comment="olav:ops|cleanup", schedule="0 1 * * *")
    cron = FakeCron([job])
    monkeypatch.setattr(tool_mod, "_get_crontab", lambda: cron)

    out = tool_mod.remove_cron(agent="ops", instruction="cleanup")

    assert out == {"status": "ok", "action": "removed", "agent": "ops", "instruction": "cleanup"}
    assert cron.jobs == []
    assert cron.write_calls == 1


def test_apply_cron_schedules_file_not_found_returns_error():
    tool_mod = _load_module("_test_manage_cron_apply_not_found")

    out = tool_mod.apply_cron_schedules(yaml_path="does-not-exist.yaml")

    assert out["status"] == "error"
    assert "File not found" in out["message"]


def test_apply_cron_schedules_uses_add_cron_invoke(monkeypatch):
    tool_mod = _load_module("_test_manage_cron_apply_ok")

    target = "virtual_cron_schedules.yaml"
    yaml_text = (
        "schedules:\n"
        "  nightly:\n"
        "    cron: '0 2 * * *'\n"
        "    agent: audit\n"
        "    instruction: take snapshot\n"
        "  missing_cron:\n"
        "    agent: ops\n"
        "    instruction: noop\n"
    )

    def fake_exists(self):
        return str(self) == target

    def fake_read_text(self):
        if str(self) != target:
            raise FileNotFoundError(str(self))
        return yaml_text

    seen_payloads = []

    def fake_add_cron(schedule: str, agent: str, instruction: str):
        seen_payloads.append({"schedule": schedule, "agent": agent, "instruction": instruction})
        return {
            "status": "ok",
            "action": "added",
            "agent": agent,
            "instruction": instruction,
            "schedule": schedule,
        }

    monkeypatch.setattr(tool_mod.Path, "exists", fake_exists)
    monkeypatch.setattr(tool_mod.Path, "read_text", fake_read_text)
    monkeypatch.setattr(tool_mod, "add_cron", fake_add_cron)

    out = tool_mod.apply_cron_schedules(yaml_path=target)

    assert seen_payloads == [
        {"schedule": "0 2 * * *", "agent": "audit", "instruction": "take snapshot"}
    ]
    assert out["status"] == "ok"
    assert out["applied"] == 2

    by_name = {item["name"]: item for item in out["results"]}
    assert by_name["nightly"]["action"] == "added"
    assert by_name["missing_cron"]["status"] == "skipped"
    assert by_name["missing_cron"]["reason"] == "no cron expression"
