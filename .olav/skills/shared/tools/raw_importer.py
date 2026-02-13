"""Simple JSON importer for parsed command outputs.

This module imports TextFSM-parsed JSON files into parsed_outputs table.
v0.13.0: Simplified design - only JSON parsing results, no raw text storage.

Design (v0.13.0):
    TextFSM JSON → parsed_outputs table (JSON) → User queries

Usage:
    from .raw_importer import import_sync_data
    result = import_sync_data(sync_dir)
"""

import json
import logging
from pathlib import Path
from datetime import datetime

import duckdb

logger = logging.getLogger(__name__)


def import_sync_data(sync_dir: Path) -> dict[str, int]:
    """Import parsed JSON files to parsed_outputs table.

    Args:
        sync_dir: Path to snapshot directory (e.g., exports/snapshots/2026-01-16/)

    Returns:
        Dictionary with import statistics (v0.13.0 - only parsed JSON)
    """
    sync_dir = Path(sync_dir)
    snapshot_date = sync_dir.name  # Directory name as date

    from olav.core.database import get_database

    db = get_database()
    conn = db.conn

    try:
        parsed_count = _import_parsed_outputs(conn, sync_dir, snapshot_date)
        return {"parsed_imported": parsed_count}
    except Exception as e:
        logger.error(f"Import failed: {e}")
        return {"parsed_imported": 0}


def _import_parsed_outputs(
    conn: duckdb.DuckDBPyConnection, sync_dir: Path, snapshot_date: str
) -> int:
    """Import parsed JSON files to parsed_outputs table (v0.13.0).
    
    Simple and clean: Just insert JSON results, no raw text storage.
    """
    parsed_dir = sync_dir / "parsed"
    if not parsed_dir.exists():
        logger.debug(f"No parsed directory at {parsed_dir}")
        return 0

    imported = 0
    for device_dir in parsed_dir.iterdir():
        if not device_dir.is_dir():
            continue

        device_name = device_dir.name

        for json_file in device_dir.glob("*.json"):
            try:
                # Read JSON file
                data = json.loads(json_file.read_text(encoding="utf-8"))
                command = data.get("command", json_file.stem)

                # Insert into parsed_outputs
                conn.execute(
                    """
                    INSERT INTO parsed_outputs
                    (device_name, command, parsed_data, snapshot_date)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        device_name,
                        command,
                        json.dumps(data),  # Store entire JSON
                        snapshot_date,
                    ],
                )
                imported += 1
                logger.debug(f"✓ Imported {device_name}/{command}")

            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {device_name}/{json_file.name}: {e}")
            except Exception as e:
                logger.debug(f"Failed to import {device_name}/{json_file.name}: {e}")

    logger.info(f"Imported {imported} parsed commands for snapshot {snapshot_date}")
    return imported
