"""olav.core.config_snapshot — last-known-good snapshot + explicit rollback
(dev_docs/99 §3.5).

Covers:
1. snapshot_api_json() copies the current file to the snapshot slot
2. snapshot_api_json() is a no-op (returns False) when there's nothing yet
3. restore_last_known_good() copies the snapshot back over api.json
4. restore_last_known_good() reports "nothing to restore" when no snapshot exists
"""

from __future__ import annotations

import json

import olav.core.config_snapshot as snap


def test_snapshot_copies_current_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(snap, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(snap, "API_JSON_PATH", tmp_path / "api.json")
    monkeypatch.setattr(snap, "SNAPSHOT_PATH", tmp_path / "api.json.lastgood")

    (tmp_path / "api.json").write_text(json.dumps({"llm": {"model": "gpt-4o"}}), encoding="utf-8")

    assert snap.snapshot_api_json() is True
    assert (tmp_path / "api.json.lastgood").exists()
    assert json.loads((tmp_path / "api.json.lastgood").read_text()) == {"llm": {"model": "gpt-4o"}}


def test_snapshot_noop_when_no_api_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(snap, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(snap, "API_JSON_PATH", tmp_path / "api.json")
    monkeypatch.setattr(snap, "SNAPSHOT_PATH", tmp_path / "api.json.lastgood")

    assert snap.snapshot_api_json() is False
    assert not (tmp_path / "api.json.lastgood").exists()


def test_restore_copies_snapshot_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(snap, "API_JSON_PATH", tmp_path / "api.json")
    monkeypatch.setattr(snap, "SNAPSHOT_PATH", tmp_path / "api.json.lastgood")

    (tmp_path / "api.json.lastgood").write_text(
        json.dumps({"llm": {"model": "old-good-model"}}), encoding="utf-8"
    )
    (tmp_path / "api.json").write_text(json.dumps({"llm": {"model": "broken-model"}}), encoding="utf-8")

    result = snap.restore_last_known_good()

    assert result["restored"] is True
    assert json.loads((tmp_path / "api.json").read_text()) == {"llm": {"model": "old-good-model"}}


def test_restore_reports_nothing_when_no_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(snap, "API_JSON_PATH", tmp_path / "api.json")
    monkeypatch.setattr(snap, "SNAPSHOT_PATH", tmp_path / "api.json.lastgood")

    result = snap.restore_last_known_good()

    assert result["restored"] is False
    assert "No last-known-good snapshot" in result["message"]
