"""Minimal raw data importer for sync workflow.

This module provides direct import of raw command outputs into the raw_outputs
table using DuckDB's Schema-less JSONB approach. No ETL or normalization needed.

Design (v0.9.3):
    Raw CLI Output → raw_outputs table (JSONB) → L1-L4 SQL Views

Usage:
    from olav.tools.raw_importer import import_sync_data
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


def _import_raw_outputs(conn: duckdb.DuckDBPyConnection, sync_dir: Path, snapshot_date: str) -> int:
    """[DEPRECATED v0.10.1] Import raw .txt files to raw_outputs table.

    DEPRECATED: This function is no longer called by import_sync_data().
    Raw data is kept in the file system only, not imported to database.

    Rationale (v0.10.1):
    - Saves ~10M database space (11M -> 1M)
    - Raw files in exports/snapshots/{date}/raw/{device}/*.txt are directly accessible
    - Use grep/cat for quick access instead of SQL queries
    - Simplifies concurrent write control (one less large write)

    If you need to restore this functionality, uncomment the call in import_sync_data().
    """
    raw_dir = sync_dir / "raw"
    if not raw_dir.exists():
        return 0

    # Import ntc-templates parser
    try:
        from olav.core.registry import CommandRegistry
        registry = CommandRegistry()
        has_parser = True
    except Exception as e:
        logger.warning(f"Failed to load parser: {e}, storing raw text only")
        has_parser = False

    imported = 0
    for device_dir in raw_dir.iterdir():
        if not device_dir.is_dir():
            continue

        device_name = device_dir.name
        for txt_file in device_dir.glob("*.txt"):
            try:
                command = txt_file.stem.replace("-", " ")
                raw_output = txt_file.read_text(encoding="utf-8", errors="ignore")

                # Parse CLI output to JSON if parser available
                parsed_json = None
                parser_name = None
                if has_parser and raw_output.strip():
                    try:
                        parsed_data = registry.parse(
                            platform="cisco_ios",  # TODO: get from device metadata
                            command=command,
                            output=raw_output
                        )
                        if parsed_data:
                            parsed_json = json.dumps(parsed_data)
                            parser_name = "ntc_templates"
                    except Exception as e:
                        logger.debug(f"Failed to parse {device_name}/{command}: {e}")

                # NOTE (v0.10.1): This INSERT is disabled to save database space
                # Raw text is kept in file system only
                #
                # conn.execute(
                #     """
                #     INSERT INTO raw_outputs (sync_date, device, command, output, parsed_output, parser_used)
                #     VALUES (?, ?, ?, ?, ?, ?)
                #     ON CONFLICT (device, command, sync_date) DO UPDATE SET
                #         output = EXCLUDED.output,
                #         parsed_output = EXCLUDED.parsed_output,
                #         parser_used = EXCLUDED.parser_used
                #     """,
                #     [
                #         snapshot_date,
                #         device_name,
                #         command,
                #         raw_output,
                #         parsed_json,
                #         parser_name,
                #     ],
                # )
                # imported += 1
            except Exception as e:
                # Log import failures for debugging
                logger.debug(f"Failed to import {device_name}/{txt_file.name}: {e}")

    return imported


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
