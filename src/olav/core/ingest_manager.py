"""Bulk Ingestion Manager for DuckDB.

Provides high-speed atomic merging of staging JSON files into main.duckdb.

Staging-First flow:
  1. Stage2 writes per-device  exports/snapshots/json/{device}.staging.json
     (overwritten on each snapshot run — no accumulation).
  2. IngestManager.bulk_load() uses DuckDB read_json_auto for a single
     high-speed atomic write, avoiding per-row INSERT overhead.
  3. Raw CLI output remains in exports/snapshots/{date}/raw/ only;
     the DB holds only structured (parsed_data JSON) records.

Staging file schema (JSON array):
  [{"device_name": "R1", "command": "show version",
    "parsed_data": [{...}], "snapshot_id": "2026-03-01"}, ...]
"""

import logging
from pathlib import Path

import duckdb

from olav.core.config import MAIN_DB_PATH, SNAPSHOTS_STAGING_JSON

logger = logging.getLogger(__name__)


class IngestManager:
    """Manager for bulk ingesting staging JSON files into DuckDB."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or MAIN_DB_PATH)
        self.staging_dir = Path(SNAPSHOTS_STAGING_JSON)

    def bulk_load(self) -> dict:
        """Load all *.staging.json files into DuckDB via read_json_auto.

        Each staging file is a JSON array produced by _process_sync_stage2.
        Files are NOT deleted after ingest — they are overwritten by the next
        snapshot run (Schema-On-Read, idempotent upsert).

        Returns:
            Dict with status, files_processed, records_inserted.
        """
        staging_files = list(self.staging_dir.glob("*.staging.json"))

        if not staging_files:
            return {"status": "no_files", "files_processed": 0, "records_inserted": 0}

        # Glob pattern for DuckDB — must be a POSIX string
        staging_pattern = (self.staging_dir / "*.staging.json").as_posix()

        try:
            with duckdb.connect(str(self.db_path), read_only=False) as conn:
                # read_json_auto reads all files in one pass.
                # parsed_data is cast to JSON to match the column type.
                # ON CONFLICT upserts — safe to re-run after a partial failure.
                conn.execute(f"""
                    INSERT INTO parsed_outputs (device_name, command, parsed_data, snapshot_id)
                    SELECT
                        device_name,
                        command,
                        parsed_data::JSON,
                        snapshot_id
                    FROM read_json_auto('{staging_pattern}', format='array')
                    ON CONFLICT (device_name, command, snapshot_id)
                    DO UPDATE SET parsed_data = EXCLUDED.parsed_data
                """)
                # DuckDB does not support changes(); count staging records directly
                rows_inserted = conn.execute(
                    f"SELECT COUNT(*) FROM read_json_auto('{staging_pattern}', format='array')"
                ).fetchone()

            inserted = rows_inserted[0] if rows_inserted else len(staging_files)
            logger.info(
                "IngestManager: loaded %d staging files, ~%d records",
                len(staging_files), inserted,
            )
            return {
                "status": "success",
                "files_processed": len(staging_files),
                "records_inserted": inserted,
            }

        except Exception as e:
            logger.error("Bulk ingestion failed: %s", e)
            return {"status": "error", "message": str(e), "files_processed": 0, "records_inserted": 0}


def bulk_ingest() -> dict:
    """Convenience wrapper: run bulk ingestion from default staging directory.

    Returns:
        Dict with status, files_processed, records_inserted.
    """
    return IngestManager().bulk_load()
