#!/usr/bin/env python3
"""Bulk Ingest Tool - Import staging JSON files into DuckDB.

This tool reads all JSON files from exports/snapshots/json/ and
bulk loads them into the parsed_outputs table in DuckDB.

Use this after running take_snapshot to persist the results.

Usage in DeepAgents:
    from .tools import bulk_ingest
    agent = create_deep_agent(tools=[bulk_ingest.bulk_ingest])
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.tools import tool


def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import MAIN_DB_PATH, SNAPSHOTS_STAGING_JSON
from olav.core.ingest_manager import IngestManager


@tool
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
    try:
        input_str = sys.stdin.read()
        params = {"snapshot_date": None}
        if input_str.strip():
            import json

            params = json.loads(input_str)

        result = bulk_ingest.func(**params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr
        )
        sys.exit(1)
