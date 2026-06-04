#!/usr/bin/env python3
"""Seed demo database from Parquet fixtures.

Restores the 5 core netops tables from Parquet+zstd files in this directory
into the OLAV main.duckdb. Used by e2e-nightly CI to provide demo data without
needing a full 5.9GB bundle import (~2 min → ~5 sec).

Usage:
    uv run python tests/fixtures/demo_db/seed.py

    # Or with explicit DB path:
    OLAV_DB_PATH=/path/to/main.duckdb uv run python tests/fixtures/demo_db/seed.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

PARQUET_FILES = {
    "netops.devices":          HERE / "devices.parquet",
    "netops.raw_output_store": HERE / "raw_output_store.parquet",
    "netops.parsed_outputs":   HERE / "parsed_outputs.parquet",
    "netops.topology_links":   HERE / "topology_links.parquet",
    "netops.bundle_ingests":   HERE / "bundle_ingests.parquet",
}


def seed(db_path: str | None = None) -> dict:
    """Restore demo tables from Parquet fixtures into main.duckdb.

    Returns:
        dict with status, tables_loaded, rows_total
    """
    import duckdb

    # Resolve DB path
    if db_path is None:
        db_path = os.environ.get("OLAV_DB_PATH")
    if db_path is None:
        try:
            sys.path.insert(0, str(HERE.parents[2] / "src"))
            from olav.core.config import MAIN_DB_PATH
            db_path = str(MAIN_DB_PATH)
        except Exception:
            db_path = str(HERE.parents[2] / ".olav" / "databases" / "main.duckdb")

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Verify all parquet files exist
    missing = [t for t, p in PARQUET_FILES.items() if not p.exists()]
    if missing:
        return {
            "status": "error",
            "message": f"Parquet files missing: {missing}. "
                       "Run scripts/export_demo_parquet.py to regenerate.",
        }

    t0 = time.time()
    rows_total = 0
    tables_loaded = []

    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS netops")

        for table, parquet_path in PARQUET_FILES.items():
            schema, name = table.split(".", 1)
            # Ensure schema exists (already created above for netops)
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

            # Apply migrations so schema matches current version
            try:
                from olav_netops.core.tables import (
                    DevicesTable, RawOutputStoreTable,
                    ParsedOutputsTable, TopologyLinksTable, BundleIngestsTable,
                )
                table_map = {
                    "devices": DevicesTable(),
                    "raw_output_store": RawOutputStoreTable(),
                    "parsed_outputs": ParsedOutputsTable(),
                    "topology_links": TopologyLinksTable(),
                    "bundle_ingests": BundleIngestsTable(),
                }
                if name in table_map:
                    table_map[name].ensure_schema(conn)
            except ImportError:
                pass  # olav_netops not installed — create table from parquet schema

            # Drop + recreate from parquet (idempotent)
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(
                f"CREATE TABLE {table} AS "
                f"SELECT * FROM read_parquet('{parquet_path}')"
            )

            rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            rows_total += rows
            tables_loaded.append(f"{table}={rows:,}")
            print(f"  ✓ {table}: {rows:,} rows", flush=True)

    elapsed = time.time() - t0
    print(f"\n  总计: {rows_total:,} 行, {elapsed:.1f}s → {db_path}")
    return {
        "status": "success",
        "db_path": str(db_path),
        "tables_loaded": tables_loaded,
        "rows_total": rows_total,
        "elapsed_sec": round(elapsed, 1),
    }


if __name__ == "__main__":
    print("=== OLAV demo DB seed (Parquet → DuckDB) ===")
    result = seed()
    if result.get("status") != "success":
        print(f"ERROR: {result.get('message')}", file=sys.stderr)
        sys.exit(1)
