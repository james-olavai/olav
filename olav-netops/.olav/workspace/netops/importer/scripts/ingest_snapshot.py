#!/usr/bin/env python3
"""`ingest_snapshot` — land a portable bundle into raw_output_store.

Wraps ``olav_netops.core.ingest.landing.ingest_snapshot``.  Defaults
``db_path`` and ``staging_dir`` from the platform paths config so the
agent does not have to plumb them.
"""
from __future__ import annotations

from pathlib import Path


def ingest_snapshot(
    path: str,
    collection_source: str | None = None,
    host_platforms: dict[str, str] | None = None,
    db_path: str | None = None,
) -> dict:
    """Land an offline snapshot bundle into the netops DB.

    Args:
        path:               Directory or zip file containing a canonical
                            portable-snapshot bundle.
        collection_source:  Optional override for
                            ``audit_runs.collection_source``.  When
                            omitted, defaults to
                            ``"bundle:<manifest.collector.name>:<version>"``
                            read from the bundle's manifest.
        host_platforms:     Optional ``{hostname: platform_key}`` map
                            from the sub-agent's Tier 3 LLM fallback
                            (see ``discover_platform_for_host``).  Most
                            ingests leave this empty — Python's Tier 1+2
                            cascade resolves 99% of hosts.
        db_path:            Override the DuckDB file path.  Falls back to
                            the ``OLAV_DB_PATH`` environment variable, then
                            the platform default (``MAIN_DB_PATH``).  The
                            file and its parent directory are created on
                            first use if they do not exist.

    Returns:
        Summary dict with keys:

          - ``bundle_id``         (uuid)
          - ``snapshot_id``       ("snap_<ts>_<workspace_id>")
          - ``bundle_sha256``     (64-hex)
          - ``collection_source`` (echoed)
          - ``hosts``             (int)
          - ``commands``          (int)
          - ``parser_fills``      ({command: rows_parsed, ...})
          - ``parse_report``      (what did NOT parse, and why — counts by
                                  reason, devices with no structured data)
          - ``report_path``       (markdown breakdown under
                                  ``exports/import_reports/``)
          - ``audit_run_id``      (uuid or None)
    """
    import os
    from pathlib import Path

    from olav.core.config import MAIN_DB_PATH, get_paths_config
    from olav.core.ingest.bundle_reader import BundleReader
    from olav_netops.core.ingest.landing import ingest_snapshot as _do_ingest

    effective_db_path = Path(
        db_path
        or os.environ.get("OLAV_DB_PATH")
        or str(MAIN_DB_PATH)
    )

    # If caller omitted collection_source, derive from manifest.
    if not collection_source:
        try:
            reader = BundleReader.open(path)
            mc = reader.manifest.collector
            collection_source = f"bundle:{mc.name}:{mc.version}"
        except Exception:  # noqa: BLE001
            collection_source = "bundle:unknown:unknown"

    paths = get_paths_config()
    staging_dir = paths.project_root / "exports" / "snapshots" / "json"

    result = _do_ingest(
        path,
        db_path=effective_db_path,
        staging_dir=staging_dir,
        collection_source=collection_source,
        host_platforms=host_platforms,
    )
    return {
        "bundle_id": result.bundle_id,
        "snapshot_id": result.snapshot_id,
        "bundle_sha256": result.bundle_sha256,
        "collection_source": result.collection_source,
        "hosts": result.hosts,
        "commands": result.commands,
        "parser_fills": result.parser_fills,
        "audit_run_id": result.audit_run_id,
        # What did NOT reach structured form, and why. Surface it — an ingest
        # that only reports successes hides ~74% of the command outputs it
        # landed (dev_docs/116). ``report_path`` is the full markdown breakdown.
        "parse_report": result.parse_report,
        "report_path": result.report_path,
    }


if __name__ == "__main__":
    import contextlib as _ctx
    import json as _json
    import sys as _sys

    _args = _json.loads(_sys.stdin.read() or "{}")
    # Keep stdout PURE JSON: the ingest impl (IngestManager.bulk_load,
    # view_builder, topology_engine) logs progress to stdout.  Route that to
    # stderr so machine consumers can `json.loads(stdout)` reliably — the demo
    # e2e wrapper choked on log-polluted stdout for 4/5 bundles (dev_docs/93 #1).
    with _ctx.redirect_stdout(_sys.stderr):
        result = ingest_snapshot(**_args)
    print(_json.dumps(result, default=str))
