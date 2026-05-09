"""reparse_unparsed.py — re-run textFSM parsers on rows that exist in
``netops.raw_output_store`` but are missing from ``netops.parsed_outputs``.

Use case: a textfsm template is fixed (e.g. juniper_junos
``show_bgp_summary`` UPTIME regex) AFTER a snapshot was taken.  The
old run wrote raw output to ``raw_output_store`` but the parser
returned no rows, so ``parsed_outputs`` is empty for that
``(device, command)``.  Re-running take_snapshot would re-collect
from a live device — often impossible (snapshot is historical) and
unnecessary (we already have the bytes).

This tool:
1. Scans ``raw_output_store`` for rows that have no matching
   ``parsed_outputs`` row at the same ``(device, command, snapshot_id)``.
2. Calls ``olav_netops.tools.textfsm_parse.parse_output`` on each one
   using the device's platform from ``netops.devices``.
3. INSERTs successful parses into ``parsed_outputs``.
4. Reports counts: scanned / re-parsed / written / still-failed.

Usage:
  python -m olav_netops.scripts.reparse_unparsed
  python -m olav_netops.scripts.reparse_unparsed --device R1
  python -m olav_netops.scripts.reparse_unparsed --command "show bgp summary"
  python -m olav_netops.scripts.reparse_unparsed --device R1 --command "show bgp summary" --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import duckdb

logger = logging.getLogger("reparse_unparsed")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _resolve_db_path() -> Path:
    """Find main.duckdb relative to current working directory.

    Mirrors the netops convention: olav CLI runs from a workspace
    root that contains ``.olav/databases/main.duckdb``.
    """
    cwd_db = Path.cwd() / ".olav" / "databases" / "main.duckdb"
    if cwd_db.exists():
        return cwd_db
    # Fall back to olav.core.config when imported in-context
    try:
        from olav.core.config import MAIN_DB_PATH
        return Path(MAIN_DB_PATH)
    except Exception as e:
        raise RuntimeError(f"Cannot locate main.duckdb: {e}") from e


def find_unparsed_rows(
    conn: duckdb.DuckDBPyConnection,
    device_filter: str | None = None,
    command_filter: str | None = None,
) -> list[tuple]:
    """Return ``(device, command, snapshot_id, raw_output, platform)``
    rows present in ``raw_output_store`` but missing from
    ``parsed_outputs``.
    """
    where = []
    params: list = []
    if device_filter:
        where.append("r.device_name = ?")
        params.append(device_filter)
    if command_filter:
        where.append("r.command = ?")
        params.append(command_filter)
    where_clause = " AND ".join(where) if where else "1=1"
    sql = f"""
        SELECT r.device_name, r.command, r.snapshot_id, r.raw_output,
               d.platform
        FROM netops.raw_output_store r
        LEFT JOIN netops.parsed_outputs p
          ON p.device_name = r.device_name
         AND p.command     = r.command
         AND p.snapshot_id = r.snapshot_id
        LEFT JOIN netops.devices d
          ON d.hostname = r.device_name
        WHERE p.device_name IS NULL
          AND r.raw_output IS NOT NULL AND length(r.raw_output) > 0
          AND r.snapshot_id IS NOT NULL
          AND {where_clause}
        ORDER BY r.device_name, r.command
    """
    return conn.execute(sql, params).fetchall()


def reparse_one(
    device: str,
    command: str,
    snapshot_id: str,
    raw_output: str,
    platform: str | None,
) -> list[dict] | None:
    """Try parse_output; return list of parsed dicts or None on miss."""
    if not platform:
        logger.warning("  %s/%s: no platform in netops.devices — skipping",
                       device, command)
        return None
    try:
        from olav_netops.tools.textfsm_parse import parse_output
        return parse_output(platform, command, raw_output)
    except Exception as e:
        logger.warning("  %s/%s: parse_output raised: %s",
                       device, command, e)
        return None


def insert_parsed(
    conn: duckdb.DuckDBPyConnection,
    device: str,
    command: str,
    snapshot_id: str,
    raw_output: str,
    parsed: list[dict],
    platform: str | None,
) -> None:
    """INSERT into parsed_outputs.  Uses ON CONFLICT DO NOTHING because
    UNIQUE(device, command, snapshot_id) is the table constraint."""
    import hashlib
    raw_hash = hashlib.sha256(raw_output.encode("utf-8", "ignore")).hexdigest()[:16]
    conn.execute(
        """
        INSERT INTO netops.parsed_outputs
            (device_name, command, parsed_data, snapshot_id,
             raw_output, raw_output_hash, ingested_at, platform)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        [device, command, json.dumps(parsed), snapshot_id,
         raw_output, raw_hash, datetime.now(), platform],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--device", help="Restrict to one hostname")
    parser.add_argument("--command", help="Restrict to one command")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be written; don't INSERT")
    args = parser.parse_args()

    db_path = _resolve_db_path()
    logger.info("DB: %s", db_path)

    # First pass: discover unparsed rows (read-only conn).
    with duckdb.connect(str(db_path), read_only=True) as ro:
        rows = find_unparsed_rows(ro, args.device, args.command)
    logger.info("Found %d unparsed (raw_output_store \\ parsed_outputs) rows",
                len(rows))
    if not rows:
        return 0

    # Second pass: reparse + insert (read-write conn).
    n_parsed = 0
    n_failed = 0
    n_no_platform = 0
    write_conn: duckdb.DuckDBPyConnection | None = None
    if not args.dry_run:
        write_conn = duckdb.connect(str(db_path), read_only=False)

    for device, command, snapshot_id, raw_output, platform in rows:
        parsed = reparse_one(device, command, snapshot_id, raw_output, platform)
        if not platform:
            n_no_platform += 1
        elif parsed:
            n_parsed += 1
            preview = parsed[0] if parsed else {}
            logger.info("  ✓ %-12s %-30s → %d row(s) parsed (sample: %.80s)",
                        device, command, len(parsed), str(preview))
            if write_conn is not None:
                insert_parsed(write_conn, device, command, snapshot_id,
                              raw_output, parsed, platform)
        else:
            n_failed += 1
            logger.info("  ✗ %-12s %-30s → still 0 rows (parser miss)",
                        device, command)

    if write_conn is not None:
        write_conn.close()

    logger.info("")
    logger.info("Summary:")
    logger.info("  scanned:     %d", len(rows))
    logger.info("  re-parsed:   %d", n_parsed)
    logger.info("  no platform: %d", n_no_platform)
    logger.info("  still fail:  %d", n_failed)
    if args.dry_run:
        logger.info("  DRY-RUN — nothing written")
    else:
        logger.info("  written to netops.parsed_outputs: %d", n_parsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
