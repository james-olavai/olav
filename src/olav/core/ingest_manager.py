"""Bulk Ingestion Manager for DuckDB.

Provides high-speed atomic merging of staging JSON files into main.duckdb.

Staging-First flow:
  1. Stage2 writes per-device  tmp/staging/{device}.staging.json
     (overwritten on each snapshot run — no accumulation).
  2. IngestManager.bulk_load() uses DuckDB read_json_auto for a single
     high-speed atomic write, avoiding per-row INSERT overhead.
  3. raw_output is stored in raw_output_store — one row per (device, command),
     always overwritten with the latest snapshot's data. No history, no dedup.
  4. Commands listed in .olav/config/backup_only_commands.yaml are written
     to exports/backup/{snapshot_id}/{device_name}.txt after each ingest.

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

from olav.core.config import BACKUP_DIR, CONFIG_DIR, MAIN_DB_PATH
from olav.platform.ingest_base import TableRegistry


def _load_backup_commands() -> frozenset[str]:
    """Read backup command list from .olav/config/domains/netops/backup_only_commands.yaml.

    Falls back to the legacy .olav/config/backup_only_commands.yaml path for
    installations that have not yet migrated to the domain-scoped layout.
    """
    domain_path = Path(CONFIG_DIR) / "domains" / "netops" / "backup_only_commands.yaml"
    legacy_path = Path(CONFIG_DIR) / "backup_only_commands.yaml"
    yaml_path = domain_path if domain_path.exists() else legacy_path
    try:
        import yaml
        entries = yaml.safe_load(yaml_path.read_text()) or []
        return frozenset(e["command"] for e in entries if isinstance(e, dict) and e.get("command"))
    except Exception as exc:
        logging.getLogger(__name__).warning("Could not load backup_only_commands.yaml: %s", exc)
        return frozenset()

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
            Dict with status, files_processed, records_inserted, snapshot_ids.
        """
        staging_files = list(self.staging_dir.glob("*.staging.json"))

        if not staging_files:
            return {"status": "no_files", "files_processed": 0, "records_inserted": 0}

        staging_pattern = (self.staging_dir / "*.staging.json").as_posix()

        _tbl = TableRegistry.get("parsed_outputs")
        _store_tbl = TableRegistry.get("raw_output_store")
        target_table = _tbl.qualified_name if _tbl else "parsed_outputs"
        store_table = _store_tbl.qualified_name if _store_tbl else "netops.raw_output_store"

        try:
            with duckdb.connect(str(self.db_path), read_only=False) as conn:
                if _tbl is not None:
                    _tbl.ensure_schema(conn)
                if _store_tbl is not None:
                    _store_tbl.ensure_schema(conn)

                # Step 1: Upsert raw_output_store — latest data wins per (device, command)
                conn.execute(f"""
                    INSERT INTO {store_table} (device_name, command, raw_output, snapshot_id, updated_at)
                    SELECT device_name, command, raw_output, snapshot_id, NOW()
                    FROM read_json_auto('{staging_pattern}', format='array', ignore_errors=true)
                    WHERE raw_output IS NOT NULL AND raw_output != ''
                    ON CONFLICT (device_name, command)
                    DO UPDATE SET
                        raw_output  = EXCLUDED.raw_output,
                        snapshot_id = EXCLUDED.snapshot_id,
                        updated_at  = NOW()
                """)

                # Step 2: Upsert parsed_outputs (no inline raw_output)
                conn.execute(f"""
                    INSERT INTO {target_table} (device_name, command, parsed_data, snapshot_id)
                    SELECT device_name, command, parsed_data::JSON, snapshot_id
                    FROM read_json_auto('{staging_pattern}', format='array', ignore_errors=true)
                    WHERE parsed_data IS NOT NULL
                    ON CONFLICT (device_name, command, snapshot_id)
                    DO UPDATE SET parsed_data = EXCLUDED.parsed_data
                """)

                rows_inserted = conn.execute(
                    f"SELECT COUNT(*) FROM read_json_auto('{staging_pattern}', format='array', ignore_errors=true)"
                ).fetchone()
                snapshot_ids = conn.execute(
                    f"SELECT DISTINCT snapshot_id FROM read_json_auto('{staging_pattern}', format='array', ignore_errors=true) WHERE snapshot_id IS NOT NULL"
                ).fetchall()

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
                "snapshot_ids": [r[0] for r in snapshot_ids],
            }

        except Exception as e:
            logger.error("Bulk ingestion failed: %s", e)
            return {
                "status": "error",
                "message": str(e),
                "files_processed": 0,
                "records_inserted": 0,
            }

        try:
            self._backup_commands(result.get("snapshot_ids", []))
        except Exception as exc:
            logger.warning("Command backup failed: %s", exc)

        for hook in self._post_ingest_hooks:
            try:
                hook(result)
            except Exception as hook_exc:  # noqa: BLE001
                logger.warning("post_ingest_hook %r failed: %s", hook, hook_exc)

        return result

    def _backup_commands(self, snapshot_ids: list[str]) -> None:
        """Write raw output for backup_only_commands.yaml entries to disk.

        Output: BACKUP_DIR / {snapshot_id} / {device_name}_{command_slug}.txt
        Reads command list from .olav/config/backup_only_commands.yaml each time
        so changes to the YAML take effect without restart.
        """
        backup_commands = _load_backup_commands()
        if not backup_commands or not snapshot_ids:
            return

        _store_tbl = TableRegistry.get("raw_output_store")
        store_table = _store_tbl.qualified_name if _store_tbl else "netops.raw_output_store"

        cmds_sql = ", ".join(f"'{c}'" for c in backup_commands)

        try:
            with duckdb.connect(str(self.db_path), read_only=True) as conn:
                rows = conn.execute(f"""
                    SELECT device_name, command, raw_output, snapshot_id
                    FROM {store_table}
                    WHERE command IN ({cmds_sql})
                      AND raw_output IS NOT NULL
                """).fetchall()
        except Exception as exc:
            logger.warning("Backup query failed: %s", exc)
            return

        for device_name, command, raw_output, snapshot_id in rows:
            snap = snapshot_id or "unknown"
            out_dir = Path(BACKUP_DIR) / snap
            out_dir.mkdir(parents=True, exist_ok=True)
            slug = command.replace(" ", "_").replace("/", "-")
            out_file = out_dir / f"{device_name}_{slug}.txt"
            out_file.write_text(raw_output, encoding="utf-8")
            logger.debug("Backup written: %s", out_file)

        if rows:
            logger.info("Command backup: %d files written to %s", len(rows), BACKUP_DIR)
