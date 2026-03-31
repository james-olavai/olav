from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

from models import CoverageEntry, CoverageMatrix

# Project-local test history DB — in .agent/ (dev tooling), isolated from production .olav/
E2E_RESULTS_DB = Path(__file__).parent / "references" / "results.duckdb"

_DDL = """
CREATE TABLE IF NOT EXISTS e2e_runs (
    run_id            VARCHAR PRIMARY KEY,
    scenario          VARCHAR,
    topology_file     VARCHAR,
    platforms         VARCHAR[],
    layers_tested     VARCHAR[],
    features_tested   VARCHAR[],
    commands_expected VARCHAR[],
    node_count        INTEGER,
    link_count        INTEGER,
    status            VARCHAR,
    collect_method    VARCHAR,
    evidence_path     VARCHAR,
    run_at            TIMESTAMPTZ DEFAULT now()
)
"""


def _append_to_db(entry: CoverageEntry, db_path: Path = E2E_RESULTS_DB) -> None:
    """Append a test run to the user-local history DuckDB (never modifies production DBs)."""
    try:
        import duckdb
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db_path))
        con.execute(_DDL)
        con.execute(
            """
            INSERT OR REPLACE INTO e2e_runs
                (run_id, scenario, topology_file, platforms, layers_tested,
                 features_tested, commands_expected, node_count, link_count,
                 status, collect_method, evidence_path, run_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry.test_run_id,
                entry.scenario,
                entry.topology_file,
                entry.platforms,
                entry.layers_tested,
                entry.features_tested,
                entry.commands_expected,
                entry.node_count,
                entry.link_count,
                entry.status,
                entry.collect_method,
                entry.evidence_path,
                entry.last_run,
            ],
        )
        con.close()
    except Exception:  # noqa: BLE001 — non-blocking; history is best-effort
        pass


_SESSION_DDL = """
CREATE TABLE IF NOT EXISTS e2e_session_runs (
    run_id        VARCHAR PRIMARY KEY,
    session       VARCHAR,
    status        VARCHAR,
    passed_count  INTEGER,
    failed_count  INTEGER,
    suites_json   VARCHAR,
    run_at        TIMESTAMPTZ DEFAULT now()
)
"""


def _append_session_to_db(result: SessionResult, db_path: Path = E2E_RESULTS_DB) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Persist a SessionResult to the history DB (append-only, best-effort)."""
    try:
        import duckdb
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db_path))
        con.execute(_SESSION_DDL)
        con.execute(
            """
            INSERT OR REPLACE INTO e2e_session_runs
                (run_id, session, status, passed_count, failed_count, suites_json, run_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                result.run_id,
                result.session,
                result.status,
                result.passed_count,
                result.failed_count,
                result.model_dump_json(),
                result.timestamp,
            ],
        )
        con.close()
    except Exception:  # noqa: BLE001
        pass


def _load_existing(coverage_file: Path) -> CoverageMatrix:
    if coverage_file.exists():
        data = json.loads(coverage_file.read_text())
        return CoverageMatrix.model_validate(data)
    return CoverageMatrix(entries=[], updated_at=datetime.now(UTC).isoformat())


def _find_entry_index(entries: list[CoverageEntry], scenario: str) -> int | None:
    """Key is scenario name — summary always reflects the latest run per scenario."""
    for i, e in enumerate(entries):
        if e.scenario == scenario:
            return i
    return None


def track_coverage(
    test_run_id: str,
    scenario_name: str,
    topology_file: str,
    platforms: list[str],
    layers_tested: list[str],
    features_tested: list[str],
    commands_expected: list[str],
    node_count: int,
    link_count: int,
    result: str,
    evidence_path: str,
    collect_method: str = "olav_cli",
    coverage_file: Path | None = None,
    results_db: Path | None = None,
) -> CoverageMatrix:
    """Record a test run in two stores:

    1. ``~/.olav/e2e/results.duckdb`` — append-only history (user-local, dev-isolated).
    2. ``evidence/coverage.json``     — per-scenario summary snapshot (committable).
    """
    cov_path = coverage_file or Path("evidence") / "coverage.json"
    now = datetime.now(UTC).isoformat()

    valid_statuses = {"not_tested", "passed", "failed", "blocked"}
    status = result if result in valid_statuses else "not_tested"

    entry = CoverageEntry(
        scenario=scenario_name,
        topology_file=topology_file,
        platforms=platforms,
        layers_tested=layers_tested,
        features_tested=features_tested,
        commands_expected=commands_expected,
        node_count=node_count,
        link_count=link_count,
        status=status,
        test_run_id=test_run_id,
        last_run=now,
        evidence_path=evidence_path,
        collect_method=collect_method,
    )

    # 1. Append full run to user-local history DB
    _append_to_db(entry, db_path=results_db or E2E_RESULTS_DB)

    # 2. Upsert into committable summary JSON (one row per scenario)
    matrix = _load_existing(cov_path)
    idx = _find_entry_index(matrix.entries, scenario_name)
    if idx is not None:
        matrix.entries[idx] = entry
    else:
        matrix.entries.append(entry)

    matrix.updated_at = now
    cov_path.parent.mkdir(parents=True, exist_ok=True)
    cov_path.write_text(json.dumps(matrix.model_dump(), indent=2))
    return matrix
