"""Importer archive + raw-collector-dump support (survey_bundle / _bundle_prepare).

Guards the fix for "advertising vs reality" mismatch: the importer SKILL.md
advertises "directory or **zip file** / rancid backup / vendor dump", but
survey_bundle used to reject anything that wasn't an already-extracted
canonical directory (`{"error": "not a directory — zip not yet supported"}`),
which sent the agent into an extract-by-hand loop.

These tests exercise the real script modules (no LLM) via the scripts dir on
sys.path, mirroring how execute_skill_script runs them (sys.path[0] = scripts).
"""
from __future__ import annotations

import importlib
import sys
import tarfile
from pathlib import Path

import pytest

_IMPORTER_SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / ".olav" / "workspace" / "netops" / "importer" / "scripts"
)


@pytest.fixture()
def prep_modules(monkeypatch):
    """Import _bundle_prepare + survey_bundle from the importer scripts dir."""
    monkeypatch.syspath_prepend(str(_IMPORTER_SCRIPTS))
    for name in ("_bundle_prepare", "survey_bundle"):
        sys.modules.pop(name, None)
    bp = importlib.import_module("_bundle_prepare")
    sb = importlib.import_module("survey_bundle")
    yield bp, sb
    for name in ("_bundle_prepare", "survey_bundle"):
        sys.modules.pop(name, None)


def _make_collector_dump(root: Path) -> Path:
    """Command-major raw dump: network_data/<command>/<host_file>."""
    nd = root / "network_data"
    hosts = ["r1.net.demo.internal", "r2.net.demo.internal"]
    (nd / "show_version").mkdir(parents=True)
    (nd / "show_ip_interface_brief").mkdir(parents=True)
    for h in hosts:
        (nd / "show_version" / h).write_text(
            "Cisco IOS Software, Version 15.2\n", encoding="utf-8"
        )
        (nd / "show_ip_interface_brief" / h).write_text(
            "Interface  IP-Address  OK?\nGi0/0  10.0.0.1  YES\n", encoding="utf-8"
        )
    return nd


def test_collector_dump_dir_normalises_to_canonical(prep_modules, tmp_path):
    _bp, sb = prep_modules
    _make_collector_dump(tmp_path / "dump")

    result = sb.survey_bundle(str(tmp_path / "dump"))

    assert result["format"] == "canonical"
    assert result["normalized_from"] == "collector_dump"
    assert result["ingest_supported"] is True
    assert len(result["hosts"]) == 2
    # The returned path is the NEW canonical location and holds a manifest.
    assert (Path(result["path"]) / "manifest.yaml").is_file()
    assert result["source_path"].endswith("dump")


def test_targz_archive_is_extracted_and_normalised(prep_modules, tmp_path):
    _bp, sb = prep_modules
    _make_collector_dump(tmp_path / "src")
    archive = tmp_path / "network_data_backup_2026-02-15.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(tmp_path / "src", arcname="home/admin/x")  # nested wrapper dirs

    result = sb.survey_bundle(str(archive))

    assert result["ingest_supported"] is True
    assert result["normalized_from"] == "collector_dump"
    assert "extracted" in result["prepare_note"]
    assert (Path(result["path"]) / "manifest.yaml").is_file()


def test_normalisation_is_idempotent(prep_modules, tmp_path):
    _bp, sb = prep_modules
    _make_collector_dump(tmp_path / "dump")
    p1 = sb.survey_bundle(str(tmp_path / "dump"))["path"]
    p2 = sb.survey_bundle(str(tmp_path / "dump"))["path"]
    assert p1 == p2  # stable digest, not per-process hash()


def test_canonical_dir_passes_through_unchanged(prep_modules, tmp_path):
    _bp, sb = prep_modules
    # A real canonical bundle already has a manifest — must not be re-normalised.
    canon = tmp_path / "bundle"
    (canon / "devices" / "r1").mkdir(parents=True)
    (canon / "manifest.yaml").write_text(
        "schema_version: 1\nhosts:\n  r1:\n    platform: cisco_ios\n", encoding="utf-8"
    )
    result = sb.survey_bundle(str(canon))
    assert result["format"] == "canonical"
    assert result["normalized_from"] is None
    assert Path(result["path"]) == canon.resolve()


def test_missing_path_fails_fast_with_notes(prep_modules, tmp_path):
    _bp, sb = prep_modules
    result = sb.survey_bundle(str(tmp_path / "nope.tar.gz"))
    assert result["ingest_supported"] is False
    assert result.get("error")
    # Structured note tells the agent to STOP, not a bare error dict.
    assert "stop" in result["notes"].lower()


def test_unsupported_file_type_fails_fast(prep_modules, tmp_path):
    _bp, sb = prep_modules
    bad = tmp_path / "report.pdf"
    bad.write_bytes(b"%PDF-1.4")
    result = sb.survey_bundle(str(bad))
    assert result["ingest_supported"] is False
    assert "not a directory and not a supported archive" in result["error"]


def test_zip_traversal_is_rejected(prep_modules, tmp_path):
    """A zip member escaping the extract dir must raise, not write outside."""
    _bp, _sb = prep_modules
    import zipfile

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escape.txt", "pwned")
    out = _bp.prepare_input(str(evil))
    assert out.get("error") and "extract" in out["error"].lower()
