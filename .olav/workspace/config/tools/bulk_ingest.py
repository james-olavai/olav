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
from datetime import date
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.ingest_manager import bulk_ingest as _bulk_ingest


@tool
def bulk_ingest(snapshot_date: Optional[str] = None) -> dict:
    """Bulk ingest staging JSON files into DuckDB.

    This tool reads all JSON files from exports/snapshots/json/ and
    bulk loads them into the parsed_outputs table in DuckDB.

    Use this after running take_snapshot to persist the results.

    Args:
        snapshot_date: Optional date string (YYYY-MM-DD) to filter.
                      If not provided, loads all available files.

    Returns:
        {
            "status": "success|no_files",
            "files_processed": 5,
            "records_inserted": 10
        }
    """
    parsed_date = None
    if snapshot_date:
        try:
            parsed_date = date.fromisoformat(snapshot_date)
        except ValueError:
            return {
                "status": "error",
                "message": f"Invalid date format: {snapshot_date}. Use YYYY-MM-DD.",
            }

    result = _bulk_ingest(parsed_date)
    return result


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
