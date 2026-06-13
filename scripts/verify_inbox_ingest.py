"""Read-only verification queries for an inbox-tarball ingest.

Invoke after ``ingest_snapshot`` lands a bundle::

    uv run python scripts/verify_inbox_ingest.py --db /tmp/full_db/main.duckdb

Prints a structured report:
  * raw_output_store row count + distinct devices
  * parsed_outputs fill rate (commands with non-NULL parsed_data)
  * netops.devices entries
  * netops.bundle_ingests provenance (collector, sha256, ingested_at)
  * Sample view freshness (v_show_version_auto)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


def _q1(conn, sql: str):
    return conn.execute(sql).fetchone()


def _qall(conn, sql: str, limit: int = 10):
    return conn.execute(sql).fetchall()[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--snapshot-id", default=None,
                    help="Filter raw_output_store / parsed_outputs to this snapshot")
    args = ap.parse_args()

    if not args.db.is_file():
        print(f"!! db not found: {args.db}", file=sys.stderr)
        return 1

    with duckdb.connect(str(args.db), read_only=True) as conn:
        print("=" * 60)
        print(f"  INGEST VERIFY  —  {args.db}")
        print("=" * 60)

        # raw_output_store
        if args.snapshot_id:
            n_raw = _q1(conn,
                f"SELECT COUNT(*) FROM netops.raw_output_store "
                f"WHERE snapshot_id = '{args.snapshot_id}'")[0]
            n_hosts = _q1(conn,
                f"SELECT COUNT(DISTINCT device_name) FROM netops.raw_output_store "
                f"WHERE snapshot_id = '{args.snapshot_id}'")[0]
        else:
            n_raw = _q1(conn, "SELECT COUNT(*) FROM netops.raw_output_store")[0]
            n_hosts = _q1(conn, "SELECT COUNT(DISTINCT device_name) FROM netops.raw_output_store")[0]
        print(f"\n  raw_output_store rows : {n_raw}")
        print(f"  distinct devices      : {n_hosts}")

        # parsed_outputs fill rate
        n_parsed = _q1(conn,
            "SELECT COUNT(*) FROM netops.parsed_outputs "
            "WHERE parsed_data IS NOT NULL")[0]
        print(f"  parsed_outputs non-NULL rows: {n_parsed}")

        # netops.devices
        n_dev = _q1(conn, "SELECT COUNT(*) FROM netops.devices")[0]
        n_dev_with_vendor = _q1(conn,
            "SELECT COUNT(*) FROM netops.devices WHERE vendor IS NOT NULL")[0]
        print(f"  netops.devices rows   : {n_dev} "
              f"({n_dev_with_vendor} with vendor)")

        # bundle_ingests provenance
        print("\n  bundle_ingests:")
        for row in _qall(conn,
                "SELECT bundle_id, collector_name, collector_version, "
                "hosts_count, commands_count, ingested_at "
                "FROM netops.bundle_ingests ORDER BY ingested_at DESC"):
            print(f"    {row[0][:8]}  {row[1]}/{row[2]}  hosts={row[3]} cmds={row[4]} "
                  f"ingested={row[5]}")

        # view freshness — pick one likely-built view
        try:
            n_view = _q1(conn,
                "SELECT COUNT(*) FROM netops.v_show_version_auto")[0]
            print(f"\n  v_show_version_auto rows: {n_view}")
        except duckdb.Error as e:
            print(f"\n  v_show_version_auto: not built ({e})")

        # Sample 5 hosts and their command coverage
        print("\n  Sample hosts (top 5 by command count):")
        for row in _qall(conn,
                "SELECT device_name, COUNT(*) as ncmds "
                "FROM netops.raw_output_store GROUP BY device_name "
                "ORDER BY ncmds DESC LIMIT 5"):
            print(f"    {row[0]}: {row[1]} commands")

        # Vendor breakdown
        print("\n  Vendor breakdown:")
        for row in _qall(conn,
                "SELECT COALESCE(vendor, '<unknown>'), COUNT(*) "
                "FROM netops.devices GROUP BY 1 ORDER BY 2 DESC"):
            print(f"    {row[0]}: {row[1]}")

        # Auto-discovery delta — model + os_version populated?
        print("\n  Auto-discovery effectiveness:")
        n_model = _q1(conn,
            "SELECT COUNT(*) FROM netops.devices WHERE model IS NOT NULL")[0]
        n_os    = _q1(conn,
            "SELECT COUNT(*) FROM netops.devices WHERE os_version IS NOT NULL")[0]
        n_total = _q1(conn, "SELECT COUNT(*) FROM netops.devices")[0]
        if n_total:
            print(f"    model populated   : {n_model}/{n_total} ({100*n_model/n_total:.1f}%)")
            print(f"    os_version filled : {n_os}/{n_total} ({100*n_os/n_total:.1f}%)")

        # Distinct models seen
        print("\n  Distinct models seen (top 10):")
        for row in _qall(conn,
                "SELECT COALESCE(model, '<null>'), COUNT(*) "
                "FROM netops.devices GROUP BY 1 ORDER BY 2 DESC LIMIT 10"):
            print(f"    {row[0]}: {row[1]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
