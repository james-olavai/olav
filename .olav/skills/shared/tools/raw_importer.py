"""Minimal raw data importer for sync workflow.

This module provides direct import of raw command outputs into the raw_outputs
table using DuckDB's Schema-less JSONB approach. No ETL or normalization needed.

Design (v0.9.3):
    Raw CLI Output → raw_outputs table (JSONB) → L1-L4 SQL Views

Usage:
    from .raw_importer import import_sync_data
    result = import_sync_data(sync_dir)
"""

import json
import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


def import_sync_data(sync_dir: Path) -> dict[str, int]:
    """Import raw and parsed data from sync directory to DuckDB.

    Args:
        sync_dir: Path to snapshot directory (e.g., exports/snapshots/2026-01-16/)

    Returns:
        Dictionary with import statistics:
        - raw_imported: Number kept as files only (v0.10.1 - not imported to DB)
        - parsed_imported: Number of parsed JSON files imported to command_outputs

    NOTE (v0.10.1): Raw .txt files are kept in file system only.
    They are NO LONGER imported to raw_outputs table to save database space.
    Use grep/cat for raw data access instead of SQL queries.
    """
    sync_dir = Path(sync_dir)
    snapshot_date = sync_dir.name

    from olav.core.database import get_database

    db = get_database()
    conn = db.conn

    try:
        # v0.10.1: Raw files kept in filesystem only, not imported to DB
        # raw_count = _import_raw_outputs(conn, sync_dir, snapshot_date)
        raw_count = 0  # Files are stored locally, not in database

        parsed_count = _import_parsed_outputs(conn, sync_dir, snapshot_date)
        return {"raw_imported": raw_count, "parsed_imported": parsed_count}
    except Exception as e:
        logger.error(f"Import failed: {e}")
        return {"raw_imported": 0, "parsed_imported": 0}


def _import_parsed_outputs(
    conn: duckdb.DuckDBPyConnection, sync_dir: Path, snapshot_date: str
) -> int:
    """Import parsed JSON files to command_outputs table."""
    parsed_dir = sync_dir / "parsed"
    if not parsed_dir.exists():
        return 0

    imported = 0
    for device_dir in parsed_dir.iterdir():
        if not device_dir.is_dir():
            continue

        device_name = device_dir.name
        for json_file in device_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                command = data.get("command", json_file.stem.replace("-", " "))
                output_data = data.get("data", data)

                conn.execute(
                    """
                    INSERT INTO command_outputs
                    (snapshot_date, device_name, command, output, source_file, parser_used)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_date, device_name, command) DO UPDATE SET
                        output = EXCLUDED.output,
                        source_file = EXCLUDED.source_file,
                        parser_used = EXCLUDED.parser_used
                    """,
                    [
                        snapshot_date,
                        device_name,
                        command,
                        json.dumps(output_data),
                        str(json_file.relative_to(sync_dir.parent.parent)),
                        "textfsm",
                    ],
                )
                imported += 1
            except Exception as e:
                # command_outputs table may not exist in minimal schema
                logger.debug(f"Failed to import parsed {device_name}/{json_file.name}: {e}")

    return imported
