"""migrate_add_platform_column.py — add ``platform`` column to
``netops.raw_output_store`` and ``netops.parsed_outputs`` and backfill
from ``netops.devices.platform``.

R-VERTICAL-SLICE 2026-05-09 (dev_docs/74).  Snapshot writes already
know the device platform (Nornir host.platform).  Denormalising it
into the fact tables eliminates the JOIN-to-devices that every
cross-vendor view / inspector currently does.

Idempotent — safe to run multiple times.  Adds the column only if
missing, then UPDATEs every NULL row from devices.

Usage:
  python -m olav_netops.scripts.migrate_add_platform_column
  python -m olav_netops.scripts.migrate_add_platform_column --dry-run
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb

logger = logging.getLogger("migrate_platform")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _resolve_db_path() -> Path:
    cwd_db = Path.cwd() / ".olav" / "databases" / "main.duckdb"
    if cwd_db.exists():
        return cwd_db
    from olav.core.config import MAIN_DB_PATH
    return Path(MAIN_DB_PATH)


def _has_column(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    schema, name = table.split(".") if "." in table else ("main", table)
    rows = conn.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ? AND column_name = ?
        """,
        [schema, name, column],
    ).fetchall()
    return len(rows) > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change; don't write")
    args = parser.parse_args()

    db_path = _resolve_db_path()
    logger.info("DB: %s", db_path)

    conn = duckdb.connect(str(db_path), read_only=args.dry_run)

    for tbl in ("netops.raw_output_store", "netops.parsed_outputs"):
        has = _has_column(conn, tbl, "platform")
        logger.info("%s: platform column %s",
                    tbl, "ALREADY EXISTS" if has else "MISSING")
        if not has and not args.dry_run:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN platform VARCHAR")
            logger.info("  → ALTER TABLE %s ADD COLUMN platform VARCHAR", tbl)

        # Backfill — we run this even when the column already existed,
        # to cover rows added between schema-migration and writer-update
        # deployments.
        before = conn.execute(
            f"SELECT count(*) FROM {tbl} WHERE platform IS NULL"
        ).fetchone()[0]
        logger.info("  rows with NULL platform: %d", before)
        if before == 0:
            continue
        if args.dry_run:
            sample = conn.execute(
                f"""
                SELECT t.device_name, t.command, d.platform
                FROM {tbl} t LEFT JOIN netops.devices d
                  ON d.hostname = t.device_name
                WHERE t.platform IS NULL LIMIT 5
                """
            ).fetchall()
            logger.info("  sample (dry-run, would backfill):")
            for r in sample:
                logger.info("    %s/%s → %r", r[0], r[1], r[2])
            continue
        conn.execute(
            f"""
            UPDATE {tbl} AS t
            SET platform = d.platform
            FROM netops.devices d
            WHERE t.device_name = d.hostname
              AND t.platform IS NULL
              AND d.platform IS NOT NULL
            """
        )
        after = conn.execute(
            f"SELECT count(*) FROM {tbl} WHERE platform IS NULL"
        ).fetchone()[0]
        logger.info("  rows still NULL after backfill: %d (filled %d)",
                    after, before - after)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
