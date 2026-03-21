from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timezone
from pathlib import Path

from models import ArtifactEntry, ArtifactsResult


def _classify_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    if path.suffix == ".duckdb":
        return "database"
    return "file"


def _scan_evidence_dir(evidence_dir: Path) -> list[ArtifactEntry]:
    entries: list[ArtifactEntry] = []
    for root, dirs, files in os.walk(evidence_dir):
        root_path = Path(root)
        for d in sorted(dirs):
            dir_path = root_path / d
            entries.append(
                ArtifactEntry(
                    name=str(dir_path.relative_to(evidence_dir)),
                    path=str(dir_path),
                    type="directory",
                    size_bytes=None,
                )
            )
        for f in sorted(files):
            file_path = root_path / f
            entries.append(
                ArtifactEntry(
                    name=str(file_path.relative_to(evidence_dir)),
                    path=str(file_path),
                    type=_classify_type(file_path),
                    size_bytes=file_path.stat().st_size if file_path.is_file() else None,
                )
            )
    return entries


def _scan_extra_paths(test_run_id: str, base_dir: Path | None = None) -> list[ArtifactEntry]:
    entries: list[ArtifactEntry] = []
    root = base_dir or Path(".")

    raw_glob = root / "exports" / "snapshots"
    if raw_glob.exists():
        for raw_dir in sorted(raw_glob.glob("*/raw")):
            for f in sorted(raw_dir.rglob("*")):
                if f.is_file():
                    entries.append(
                        ArtifactEntry(
                            name=str(f.relative_to(root)),
                            path=str(f),
                            type=_classify_type(f),
                            size_bytes=f.stat().st_size,
                        )
                    )

    json_glob = root / "exports" / "snapshots" / "json"
    if json_glob.exists():
        for f in sorted(json_glob.glob("*.json")):
            entries.append(
                ArtifactEntry(
                    name=str(f.relative_to(root)),
                    path=str(f),
                    type="file",
                    size_bytes=f.stat().st_size,
                )
            )

    db_path = root / ".olav" / "databases" / f"test_{test_run_id}.duckdb"
    if db_path.exists():
        entries.append(
            ArtifactEntry(
                name=str(db_path.relative_to(root)),
                path=str(db_path),
                type="database",
                size_bytes=db_path.stat().st_size,
            )
        )

    return entries


def collect_artifacts(
    test_run_id: str, evidence_dir: Path, base_dir: Path | None = None
) -> ArtifactsResult:
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    artifacts = _scan_evidence_dir(evidence_dir)
    extra = _scan_extra_paths(test_run_id, base_dir)

    seen_paths: set[str] = {a.path for a in artifacts}
    for entry in extra:
        if entry.path not in seen_paths:
            artifacts.append(entry)
            seen_paths.add(entry.path)

    result = ArtifactsResult(
        test_run_id=test_run_id,
        artifacts=artifacts,
        evidence_dir=str(evidence_dir),
        timestamp=datetime.now(UTC).isoformat(),
    )

    output_path = evidence_dir / "artifacts.json"
    output_path.write_text(json.dumps(result.model_dump(), indent=2))

    return result
