#!/usr/bin/env python3
"""Bulk Ingest Tool - Import staging JSON files into DuckDB.

This tool reads all JSON files from exports/snapshots/json/ and
bulk loads them into the parsed_outputs table in DuckDB.

Use this after running take_snapshot to persist the results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import MAIN_DB_PATH, SNAPSHOTS_STAGING_JSON
from olav.core.ingest_manager import IngestManager


def bulk_ingest(snapshot_date: str | None = None) -> dict:
    """Bulk ingest staging JSON files into DuckDB.

    This tool reads all *.staging.json files from exports/snapshots/json/ and
    bulk loads them into the parsed_outputs table in DuckDB using IngestManager.

    Use this after running take_snapshot to persist the results.

    Args:
        snapshot_date: Ignored (kept for API compatibility). All staging files
                       in the staging_json directory are loaded atomically.

    Returns:
        {
            "status": "success|no_files",
            "files_processed": 5,
            "records_inserted": 10
        }
    """
    try:
        mgr = IngestManager(db_path=MAIN_DB_PATH, staging_dir=SNAPSHOTS_STAGING_JSON)
        return mgr.bulk_load()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = bulk_ingest(**_args)
    print(_json.dumps(result, default=str))
