#!/usr/bin/env python3
"""export_netbox_csv — single-shot SQL → NetBox-import CSV.

Wraps the SQL + format conversion + file write into one slash command
so gemma4-nothink-class agents don't have to chain two tool calls
(SQL → format_and_export), which they do unreliably (see
`netbox_csv_export.guide.yaml` for the equivalent multi-step
recipe).  This is the canonical Ch10a path B entrypoint.

Usage::

    olav --agent netops "/export_netbox_csv"
    olav --agent netops "/export_netbox_csv --filename my_export"

Output: ``exports/<filename>.csv`` (default filename ``netbox_devices``)
with the columns and column order described in
``netops/guides/netbox_csv_export.guide.yaml``.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path


# SQL matches netbox_csv_export.guide.yaml exactly so the guide stays
# the single source of truth for column mapping.
#
# site / device_role are required FKs in NetBox but are not part of any
# collected artifact (no CMDB is ingested) — netops.devices ships them NULL.
# They ARE, however, encoded in the fleet's hostname convention
# (``<site>-<role>-<model/id>…``, e.g. ``alpha-core-6807v`` → site=alpha,
# role=core), which is the standard way NetBox seeds sites/roles from a
# naming scheme. Derive them from the hostname when the DB column is NULL so
# the row satisfies NetBox's required FKs; a populated column always wins.
_SQL = """
SELECT
  d.hostname                                          AS name,
  COALESCE(NULLIF(d.role, ''), split_part(d.hostname, '-', 2)) AS device_role,
  d.vendor                                            AS manufacturer,
  d.model                                             AS device_type,
  d.ip_address                                        AS primary_ip4,
  d.platform                                          AS platform,
  COALESCE(NULLIF(d.site, ''), split_part(d.hostname, '-', 1)) AS site,
  'active'                                            AS status,
  ?                                                   AS tenant,
  s.snapshot_id                                       AS snapshot_id,
  ?                                                   AS exported_at
FROM netops.devices d
CROSS JOIN (
  SELECT snapshot_id FROM netops.v_snapshots_auto
  ORDER BY snapshot_id DESC LIMIT 1
) s
ORDER BY d.hostname
"""


def _resolve_tenant() -> str:
    """Try to read the team-tier default tenant from the
    ``netbox_tenant_default`` guide (services/guides).  Falls back to
    ``unset`` if the guide isn't present — operator can edit the CSV
    or re-prime the guide.
    """
    try:
        import yaml
        candidates = list(Path(".olav/workspace").rglob("netbox_tenant*.guide.yaml"))
        for p in candidates:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            body = str(data.get("body", ""))
            for token in body.splitlines():
                if "acme-network-ops" in token:
                    return "acme-network-ops"
                # Generic pattern: pull the first backtick-quoted bareword
                # from the body that looks like a tenant slug.
            # Fallback: scan body for a backtick token like `team-foo`
            import re
            m = re.search(r"`([a-z0-9-]+)`", body)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "unset"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="export_netbox_csv",
        description="Export netops.devices to NetBox-import-compatible CSV.",
    )
    parser.add_argument(
        "--filename", default="netbox_devices",
        help="Basename without extension (default: netbox_devices)",
    )
    parser.add_argument(
        "--tenant", default=None,
        help="Override tenant column.  Default: read from "
             "`netbox_tenant_default` guide, fall back to 'unset'.",
    )
    parser.add_argument(
        "--out-dir", default="exports",
        help="Output directory (default: exports/)",
    )
    args = parser.parse_args()

    tenant = args.tenant or _resolve_tenant()
    exported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    # Locate the main DuckDB
    try:
        from olav.core.config import MAIN_DB_PATH
        db_path = MAIN_DB_PATH
    except Exception:
        db_path = Path(".olav/databases/main.duckdb")

    import duckdb
    with duckdb.connect(str(db_path), read_only=True) as conn:
        cur = conn.execute(_SQL, [tenant, exported_at])
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()

    if not rows:
        print("⚠ no devices in netops.devices — did you run /netops_init?", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.filename}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(r)

    print(f"✓ wrote {out_path} ({len(rows)} devices, tenant={tenant!r})")
    # Surface a tiny preview so the operator immediately sees the shape.
    print(f"  header: {','.join(cols)}")
    print(f"  first:  {','.join(str(v) for v in rows[0])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
