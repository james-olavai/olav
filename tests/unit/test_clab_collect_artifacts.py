import json
import sys
from pathlib import Path

_SKILL_DIR = (
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab"
)
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from collect_artifacts import collect_artifacts
from models import ArtifactEntry, ArtifactsResult


def test_collect_artifacts_empty_dir(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    result = collect_artifacts("run-001", evidence, base_dir=tmp_path)
    assert isinstance(result, ArtifactsResult)
    assert result.test_run_id == "run-001"
    assert result.artifacts == []
    assert (evidence / "artifacts.json").exists()


def test_collect_artifacts_creates_evidence_dir(tmp_path):
    evidence = tmp_path / "nonexistent" / "evidence"
    result = collect_artifacts("run-002", evidence)
    assert evidence.exists()
    assert result.evidence_dir == str(evidence)


def test_collect_artifacts_single_file(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "test.log").write_text("log data")
    result = collect_artifacts("run-003", evidence, base_dir=tmp_path)
    assert len(result.artifacts) == 1
    entry = result.artifacts[0]
    assert entry.name == "test.log"
    assert entry.type == "file"
    assert entry.size_bytes == 8


def test_collect_artifacts_duckdb_classified_as_database(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "test.duckdb").write_bytes(b"\x00" * 64)
    result = collect_artifacts("run-004", evidence)
    db_entries = [a for a in result.artifacts if a.type == "database"]
    assert len(db_entries) == 1
    assert db_entries[0].name == "test.duckdb"
    assert db_entries[0].size_bytes == 64


def test_collect_artifacts_subdirectory_listed(tmp_path):
    evidence = tmp_path / "evidence"
    sub = evidence / "subdir"
    sub.mkdir(parents=True)
    (sub / "nested.txt").write_text("hello")
    result = collect_artifacts("run-005", evidence)
    types = {a.type for a in result.artifacts}
    assert "directory" in types
    assert "file" in types
    dir_entries = [a for a in result.artifacts if a.type == "directory"]
    assert any(e.name == "subdir" for e in dir_entries)


def test_collect_artifacts_directory_has_no_size(tmp_path):
    evidence = tmp_path / "evidence"
    (evidence / "subdir").mkdir(parents=True)
    result = collect_artifacts("run-006", evidence)
    dir_entries = [a for a in result.artifacts if a.type == "directory"]
    assert all(e.size_bytes is None for e in dir_entries)


def test_collect_artifacts_writes_valid_json(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "a.txt").write_text("aaa")
    (evidence / "b.json").write_text("{}")
    collect_artifacts("run-007", evidence)
    data = json.loads((evidence / "artifacts.json").read_text())
    parsed = ArtifactsResult.model_validate(data)
    assert parsed.test_run_id == "run-007"
    artifact_names = {a.name for a in parsed.artifacts}
    assert "a.txt" in artifact_names
    assert "b.json" in artifact_names


def test_collect_artifacts_has_timestamp(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    result = collect_artifacts("run-008", evidence)
    assert result.timestamp
    assert "T" in result.timestamp


def test_collect_artifacts_extra_exports_raw(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    raw = tmp_path / "exports" / "snapshots" / "2025-01-01" / "raw"
    raw.mkdir(parents=True)
    (raw / "device1.txt").write_text("show version")
    result = collect_artifacts("run-009", evidence, base_dir=tmp_path)
    extra_names = [a.name for a in result.artifacts if "exports" in a.name]
    assert len(extra_names) >= 1


def test_collect_artifacts_extra_exports_json(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    json_dir = tmp_path / "exports" / "snapshots" / "json"
    json_dir.mkdir(parents=True)
    (json_dir / "parsed.json").write_text('{"key": "value"}')
    result = collect_artifacts("run-010", evidence, base_dir=tmp_path)
    json_names = [
        a.name for a in result.artifacts if a.name.endswith(".json") and "exports" in a.name
    ]
    assert len(json_names) >= 1


def test_collect_artifacts_extra_duckdb_file(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    db_dir = tmp_path / ".olav" / "databases"
    db_dir.mkdir(parents=True)
    (db_dir / "test_run-011.duckdb").write_bytes(b"\x00" * 128)
    result = collect_artifacts("run-011", evidence, base_dir=tmp_path)
    db_entries = [a for a in result.artifacts if a.type == "database"]
    assert len(db_entries) == 1
    assert "test_run-011.duckdb" in db_entries[0].path


def test_collect_artifacts_no_duplicates(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "file.txt").write_text("data")
    result = collect_artifacts("run-012", evidence, base_dir=tmp_path)
    paths = [a.path for a in result.artifacts]
    assert len(paths) == len(set(paths))


def test_collect_artifacts_multiple_nested_files(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for i in range(5):
        sub = evidence / f"level_{i}"
        sub.mkdir()
        (sub / f"file_{i}.txt").write_text(f"content {i}")
    result = collect_artifacts("run-013", evidence, base_dir=tmp_path)
    file_entries = [a for a in result.artifacts if a.type == "file"]
    dir_entries = [a for a in result.artifacts if a.type == "directory"]
    assert len(file_entries) == 5
    assert len(dir_entries) == 5
