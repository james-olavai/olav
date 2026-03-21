"""Bulk Ingestion Manager for DuckDB.

Provides high-speed atomic merging of staging JSON files into main.duckdb.

Staging-First flow:
  1. Stage2 writes per-device  tmp/staging/{device}.staging.json
     (overwritten on each snapshot run — no accumulation).
  2. IngestManager.bulk_load() uses DuckDB read_json_auto for a single
     high-speed atomic write, avoiding per-row INSERT overhead.
  3. Config backups persist in exports/backup/{date}/{device}/;
     operational raw output goes to tmp/snapshots/{date}/raw/;
     the DB holds only structured (parsed_data JSON) records.

Staging file schema (JSON array):
  [{"device_name": "R1", "command": "show version",
    "parsed_data": [{...}], "snapshot_id": "2026-03-01",
    "raw_output": "<raw CLI text>"}, ...]
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from olav.core.config import MAIN_DB_PATH
from olav.platform.ingest_base import TableRegistry

logger = logging.getLogger(__name__)


class IngestManager:
    """Manager for bulk ingesting staging JSON files into DuckDB."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        staging_dir: str | Path | None = None,
        post_ingest_hooks: list[Callable[[dict[str, Any]], None]] | None = None,
    ) -> None:
        self.db_path = Path(db_path or MAIN_DB_PATH)
        if staging_dir is None:
            raise ValueError(
                "staging_dir is required. Domain packages must pass their own staging path. "
                "(olav-netops convention: EXPORTS_DIR / 'snapshots' / 'json')"
            )
        self.staging_dir = Path(staging_dir)
        # Optional callbacks invoked after a successful bulk_load().
        # Each hook receives the result dict; exceptions are logged, not raised.
        self._post_ingest_hooks: list[Callable[[dict[str, Any]], None]] = list(
            post_ingest_hooks or []
        )

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

        # Resolve target table name via TableRegistry (domain-package aware).
        # If olav-netops (or another domain package) has registered
        # 'parsed_outputs', use its qualified_name (e.g. 'netops.parsed_outputs').
        # Fall back to the legacy flat-table name for backward compatibility.
        _tbl = TableRegistry.get("parsed_outputs")
        target_table = _tbl.qualified_name if _tbl else "parsed_outputs"

        try:
            with duckdb.connect(str(self.db_path), read_only=False) as conn:
                # Ensure schema + table exist if domain package registered the table.
                if _tbl is not None:
                    _tbl.ensure_schema(conn)
                # read_json_auto reads all files in one pass.
                # parsed_data is cast to JSON to match the column type.
                # ON CONFLICT upserts — safe to re-run after a partial failure.
                conn.execute(f"""
                    INSERT INTO {target_table} (device_name, command, parsed_data, snapshot_id, raw_output)
                    SELECT
                        device_name,
                        command,
                        parsed_data::JSON,
                        snapshot_id,
                        TRY_CAST(raw_output AS VARCHAR)
                    FROM read_json_auto('{staging_pattern}', format='array', ignore_errors=true)
                    WHERE parsed_data IS NOT NULL
                    ON CONFLICT (device_name, command, snapshot_id)
                    DO UPDATE SET
                        parsed_data = EXCLUDED.parsed_data,
                        raw_output  = EXCLUDED.raw_output
                """)
                # DuckDB does not support changes(); count staging records directly
                rows_inserted = conn.execute(
                    f"SELECT COUNT(*) FROM read_json_auto('{staging_pattern}', format='array', ignore_errors=true)"
                ).fetchone()

            inserted = rows_inserted[0] if rows_inserted else len(staging_files)
            logger.info(
                "IngestManager: loaded %d staging files, ~%d records",
                len(staging_files),
                inserted,
            )
            result: dict[str, Any] = {
                "status": "success",
                "files_processed": len(staging_files),
                "records_inserted": inserted,
            }

        except Exception as e:
            logger.error("Bulk ingestion failed: %s", e)
            return {
                "status": "error",
                "message": str(e),
                "files_processed": 0,
                "records_inserted": 0,
            }

        for hook in self._post_ingest_hooks:
            try:
                hook(result)
            except Exception as hook_exc:  # noqa: BLE001
                logger.warning("post_ingest_hook %r failed: %s", hook, hook_exc)

        return result
