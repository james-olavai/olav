"""§7.4 wiring — the acting scripts journal their writes, and
undo_last_action reverts them end-to-end (dev_docs/99 §7.4).

Loads the deployed runtime scripts by file path (the same copies
execute_skill_script runs) rather than importing modules directly.
Covers:
1. write_workspace_file journals an overwrite → undo restores prior bytes
2. write_workspace_file journals a create → undo deletes the file
3. write result carries undo_recorded=True
4. manage_cron add/update/remove journal the right kinds with the right data
5. undo_last_action script: list_only preview + actual revert
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import olav.core.undo_journal as uj

REPO = Path(__file__).resolve().parents[2]
_EDITOR_SCRIPTS = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts"
_OPS_SCRIPTS = REPO / ".olav" / "workspace" / "admin" / "ops" / "scripts"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if name == "manage_cron_under_test":
        # crontab may be unimportable in CI containers; stub before exec
        import types

        sys.modules.setdefault("crontab", types.SimpleNamespace(CronTab=object))
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(uj, "_UNDO_DIR_OVERRIDE", tmp_path / "undo")
    monkeypatch.setattr(uj, "_project_root", lambda: tmp_path)
    yield


# ---------------------------------------------------------------------------
# write_workspace_file → journal → undo
# ---------------------------------------------------------------------------


def test_overwrite_then_undo_restores_previous_content(tmp_path, monkeypatch) -> None:
    mod = _load(_EDITOR_SCRIPTS / "write_workspace_file.py", "wwf_under_test")
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)

    target = tmp_path / "notes.md"
    target.write_text("original", encoding="utf-8")

    result = mod.write_workspace_file("notes.md", "changed")
    assert result["success"] is True
    assert result["undo_recorded"] is True
    assert target.read_text(encoding="utf-8") == "changed"

    undo = uj.undo_last()
    assert undo["undone"] is True
    assert target.read_text(encoding="utf-8") == "original"


def test_create_then_undo_deletes_file(tmp_path, monkeypatch) -> None:
    mod = _load(_EDITOR_SCRIPTS / "write_workspace_file.py", "wwf_under_test2")
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)

    result = mod.write_workspace_file("brand_new.yaml", "content")
    assert result["success"] is True
    assert result["undo_recorded"] is True
    assert (tmp_path / "brand_new.yaml").exists()

    undo = uj.undo_last()
    assert undo["undone"] is True
    assert not (tmp_path / "brand_new.yaml").exists()


# ---------------------------------------------------------------------------
# manage_cron → journal (fake crontab)
# ---------------------------------------------------------------------------


class _FakeJob:
    def __init__(self, command="", comment=""):
        self.command = command
        self.comment = comment
        self.slices = ""

    def setall(self, schedule):
        self.slices = schedule

    def is_enabled(self):
        return True


class _FakeCron:
    def __init__(self):
        self.jobs = []

    def __iter__(self):
        return iter(self.jobs)

    def find_comment(self, comment):
        return (j for j in self.jobs if j.comment == comment)

    def new(self, command, comment):
        job = _FakeJob(command, comment)
        self.jobs.append(job)
        return job

    def remove(self, job):
        self.jobs.remove(job)

    def write(self):
        pass


def test_cron_add_update_remove_journal_kinds(tmp_path, monkeypatch) -> None:
    mod = _load(_OPS_SCRIPTS / "manage_cron.py", "manage_cron_under_test")
    cron = _FakeCron()
    monkeypatch.setattr(mod, "_get_crontab", lambda: cron)

    r = mod.add_cron("0 2 * * *", "audit", "daily check")
    assert r["action"] == "added" and r["undo_recorded"] is True

    r = mod.add_cron("0 4 * * *", "audit", "daily check")
    assert r["action"] == "updated" and r["undo_recorded"] is True

    r = mod.remove_cron("audit", "daily check")
    assert r["action"] == "removed" and r["undo_recorded"] is True

    kinds = [a["kind"] for a in uj.list_actions()]
    assert kinds == ["cron_remove", "cron_update", "cron_add"]

    # And the remove entry holds enough to re-add the job
    entries = sorted(uj._undo_dir().glob("*.json"), reverse=True)
    import json

    newest = json.loads(entries[0].read_text(encoding="utf-8"))
    assert newest["data"]["schedule"] == "0 4 * * *"
    assert "olav:audit|daily check" in newest["data"]["comment"]


# ---------------------------------------------------------------------------
# undo_last_action script (what the editor sub-agent actually calls)
# ---------------------------------------------------------------------------


def test_undo_last_action_script_preview_and_revert(tmp_path, monkeypatch) -> None:
    wwf = _load(_EDITOR_SCRIPTS / "write_workspace_file.py", "wwf_under_test3")
    monkeypatch.setattr(wwf, "PROJECT_ROOT", tmp_path)
    ula = _load(_EDITOR_SCRIPTS / "undo_last_action.py", "ula_under_test")

    wwf.write_workspace_file("a.txt", "hello")

    preview = ula.undo_last_action(list_only=True)
    assert len(preview["actions"]) == 1
    assert "a.txt" in preview["actions"][0]["description"]
    assert (tmp_path / "a.txt").exists(), "preview must not revert anything"

    result = ula.undo_last_action()
    assert result["undone"] is True
    assert not (tmp_path / "a.txt").exists()

    assert ula.undo_last_action()["undone"] is False  # journal now empty
