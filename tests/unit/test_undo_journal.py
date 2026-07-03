"""olav.core.undo_journal — generalized undo for agent write-actions
(dev_docs/99 §7.4).

Covers:
1. record + list round-trip (most-recent-first, limited)
2. journal cap pruning (oldest entries dropped past _MAX_ENTRIES)
3. undo file_write: restore previous content / delete newly-created file
4. file restore refuses paths outside the project root
5. undo on empty journal → polite no-op
6. unknown kind → entry kept, not deleted
7. failed revert → entry kept (retryable), reported
8. cron handlers: add→remove, update→restore schedule, remove→re-add
   (via a fake CronTab)
"""

from __future__ import annotations

import json
import time

import pytest

import olav.core.undo_journal as uj


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(uj, "_UNDO_DIR_OVERRIDE", tmp_path / "undo")
    monkeypatch.setattr(uj, "_project_root", lambda: tmp_path)
    yield


def test_record_and_list_round_trip() -> None:
    assert uj.record_action("file_write", "created a.txt", {"path": "a"}) is True
    time.sleep(0.002)
    assert uj.record_action("cron_add", "added job x", {"comment": "x"}) is True

    actions = uj.list_actions()
    assert [a["description"] for a in actions] == ["added job x", "created a.txt"]


def test_journal_cap_prunes_oldest(monkeypatch) -> None:
    monkeypatch.setattr(uj, "_MAX_ENTRIES", 3)
    for i in range(5):
        uj.record_action("file_write", f"write {i}", {"path": str(i)})
        time.sleep(0.002)

    actions = uj.list_actions(limit=10)
    assert len(actions) == 3
    assert actions[0]["description"] == "write 4"
    assert actions[-1]["description"] == "write 2"


def test_undo_file_write_restores_previous_content(tmp_path) -> None:
    target = tmp_path / "ws" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("NEW content", encoding="utf-8")
    uj.record_action(
        "file_write", f"overwrote {target}",
        {"path": str(target), "existed": True, "previous_content": "OLD content"},
    )

    result = uj.undo_last()

    assert result["undone"] is True
    assert target.read_text(encoding="utf-8") == "OLD content"
    # entry consumed — second undo finds nothing
    assert uj.undo_last()["undone"] is False


def test_undo_file_write_deletes_newly_created_file(tmp_path) -> None:
    target = tmp_path / "new_file.yaml"
    target.write_text("fresh", encoding="utf-8")
    uj.record_action(
        "file_write", f"created {target}",
        {"path": str(target), "existed": False, "previous_content": None},
    )

    result = uj.undo_last()

    assert result["undone"] is True
    assert not target.exists()


def test_undo_file_write_refuses_path_outside_project_root(tmp_path) -> None:
    outside = tmp_path.parent / f"outside-{tmp_path.name}.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        uj.record_action(
            "file_write", "created outside",
            {"path": str(outside), "existed": False, "previous_content": None},
        )
        result = uj.undo_last()

        assert result["undone"] is False
        assert outside.exists(), "must not delete files outside the project root"
        assert uj.list_actions(), "failed entry must be kept"
    finally:
        outside.unlink(missing_ok=True)


def test_undo_empty_journal_is_polite_noop() -> None:
    result = uj.undo_last()
    assert result["undone"] is False
    assert "Nothing to undo" in result["message"]


def test_unknown_kind_keeps_entry() -> None:
    uj.record_action("teleport", "moved a mountain", {})
    result = uj.undo_last()
    assert result["undone"] is False
    assert "teleport" in result["message"]
    assert uj.list_actions(), "unknown-kind entry must be kept for manual handling"


class _FakeJob:
    def __init__(self, command="", comment=""):
        self.command = command
        self.comment = comment
        self.slices = ""

    def setall(self, schedule):
        self.slices = schedule


class _FakeCron:
    def __init__(self):
        self.jobs: list[_FakeJob] = []
        self.writes = 0

    def find_comment(self, comment):
        return (j for j in self.jobs if j.comment == comment)

    def new(self, command, comment):
        job = _FakeJob(command, comment)
        self.jobs.append(job)
        return job

    def remove(self, job):
        self.jobs.remove(job)

    def write(self):
        self.writes += 1


def test_undo_cron_add_removes_job(monkeypatch) -> None:
    cron = _FakeCron()
    cron.new("echo hi", "olav:audit|daily check")
    monkeypatch.setattr(uj, "_get_crontab", lambda: cron)
    uj.record_action("cron_add", "added job", {"comment": "olav:audit|daily check"})

    result = uj.undo_last()

    assert result["undone"] is True
    assert cron.jobs == []
    assert cron.writes == 1


def test_undo_cron_update_restores_schedule(monkeypatch) -> None:
    cron = _FakeCron()
    job = cron.new("echo hi", "olav:audit|daily check")
    job.setall("0 4 * * *")  # the "new" schedule being undone
    monkeypatch.setattr(uj, "_get_crontab", lambda: cron)
    uj.record_action(
        "cron_update", "updated job",
        {"comment": "olav:audit|daily check", "previous_schedule": "0 2 * * *"},
    )

    result = uj.undo_last()

    assert result["undone"] is True
    assert job.slices == "0 2 * * *"


def test_undo_cron_remove_re_adds_job(monkeypatch) -> None:
    cron = _FakeCron()
    monkeypatch.setattr(uj, "_get_crontab", lambda: cron)
    uj.record_action(
        "cron_remove", "removed job",
        {"comment": "olav:audit|daily check", "schedule": "0 2 * * *", "command": "echo hi"},
    )

    result = uj.undo_last()

    assert result["undone"] is True
    assert len(cron.jobs) == 1
    assert cron.jobs[0].comment == "olav:audit|daily check"
    assert cron.jobs[0].slices == "0 2 * * *"
