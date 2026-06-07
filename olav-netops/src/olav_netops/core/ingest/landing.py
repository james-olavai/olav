"""End-to-end landing driver for a portable snapshot bundle.

Sequence (mirrors ``netops_init/run.py:_run_collection`` for the post-SSH
phase, but driven from disk instead of live netmiko sessions)::

  BundleReader.open(path)
    → for each CommandRecord:
        body = scrub(body) if not record.pre_scrubbed else body  # defense-in-depth
        parsed = textfsm_parse(platform, command, body)
        staging.append({snapshot_id, device_name, command,
                        raw_output, parsed_data, platform})
  → write staging.json to staging_dir
  → ensure netops migration applied (idempotent ALTER + CREATE)
  → IngestManager.bulk_load()           # raw_output_store + parsed_outputs
  → populate_devices(db_path, snapshot_id)
  → extract_lldp_topology(conn)
  → finalise_ingest(conn)               # v_*_auto views
  → INSERT netops.bundle_ingests
  → UPDATE raw_output_store rows for this snapshot: set bundle_id/sha256/ingested_via
  → AuditEventRecorder.record_run_*     # with collection_source

Returns an ``IngestResult`` summarising what landed.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from olav.core.ingest.bundle_reader import BundleReader
from olav.core.ingest.validators import validate_bundle


# ── Public result type ────────────────────────────────────────────────


@dataclass(slots=True)
class IngestResult:
    """Summary returned by ``ingest_snapshot``."""

    bundle_id: str
    snapshot_id: str
    bundle_sha256: str
    collection_source: str
    hosts: int
    commands: int
    parser_fills: dict[str, int]
    audit_run_id: str | None = None


# ── Internal helpers ──────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_text_for_db(text: str) -> str:
    """Defense-in-depth scrub via netconan; fail-open."""
    try:
        from olav.core.redaction import scrub
        out, _ = scrub(text)
        return out
    except Exception:  # noqa: BLE001
        return text


def _parse_one(platform: str, command: str, body: str) -> str | None:
    """Try to TextFSM-parse a single (platform, command, body); return
    JSON-encoded list-of-dicts or None."""
    try:
        from olav_netops.tools.textfsm_parse import parse_output
        parsed = parse_output(platform, command, body)
    except Exception:  # noqa: BLE001 — best-effort
        return None
    if not parsed:
        return None
    return json.dumps(parsed)


# ── Public entry point ────────────────────────────────────────────────


def ingest_snapshot(
    path: str | Path,
    *,
    db_path: str | Path,
    staging_dir: str | Path,
    collection_source: str,
    audit_recorder: Any | None = None,
    snapshot_id: str | None = None,
    host_platforms: dict[str, str] | None = None,
) -> IngestResult:
    """Land an offline bundle into the netops DB.

    Args:
        path:               Bundle root (directory or .zip).
        db_path:            Main DuckDB file.  Tests use a tmp_path file;
                            production passes ``MAIN_DB_PATH``.
        staging_dir:        Directory used by ``IngestManager`` for the
                            transient ``*.staging.json`` artefact.
        collection_source:  Goes into ``audit_runs.collection_source``,
                            e.g. ``"bundle:olav-collector:0.1.0"``.
        audit_recorder:     Optional ``AuditEventRecorder`` instance.  When
                            None the run is not audited (useful for tests
                            that already own an in-memory connection).
        snapshot_id:        Override; default
                            ``"snap_<utc-ts>_<workspace_id>"``.
        host_platforms:     Optional ``{hostname: platform_key}`` map.
                            Authoritative for those hosts — typically
                            supplied by the ingest sub-agent after the
                            Tier 3 LLM fallback identified platforms that
                            the Tier 1/2 TextFSM cascade could not.

    Returns:
        ``IngestResult``.

    Raises:
        FileNotFoundError:   bundle missing or invalid layout
        ValueError:          validate_bundle returned a hard error (sha256,
                             manifest schema, etc.)
    """
    bundle_path = Path(path)
    db_path = Path(db_path)
    staging_dir = Path(staging_dir)
    host_platforms = dict(host_platforms or {})

    # 1. Validate (sha256 + manifest schema).  Cheap, no DB touch.
    report = validate_bundle(bundle_path)
    if not report.ok:
        raise ValueError(f"bundle validation failed: {report.errors}")

    # 2. Read.
    reader = BundleReader.open(bundle_path)
    manifest = reader.manifest

    sid = snapshot_id or (
        f"snap_{_now().strftime('%Y%m%d_%H%M%S')}_{manifest.workspace_id or 'unknown'}"
    )
    bundle_id = str(uuid.uuid4())

    # 2.5 Tier 1+2 platform discovery for every host whose ``_meta.platform``
    # is missing / ``unknown``.  Caller-supplied host_platforms wins.  This
    # is the ADR-0007 Python-first path: deterministic TextFSM cascade
    # before any per-row work; LLM (Tier 3) only fills in what we couldn't.
    if bundle_path.is_dir():
        from olav.core.ingest.platform_discovery import discover_platform
        devices_root = bundle_path / "devices"
        if devices_root.is_dir():
            for host_dir in devices_root.iterdir():
                if not host_dir.is_dir():
                    continue
                host = host_dir.name
                if host in host_platforms:
                    continue
                disc = discover_platform(host_dir)
                if disc.platform:
                    host_platforms[host] = disc.platform

    # 3. Build staging rows.
    _skip_scrub = manifest.redaction.pre_scrubbed

    rows: list[dict[str, Any]] = []
    parser_fills: dict[str, int] = {}
    hosts: set[str] = set()

    for rec in reader.iter_command_outputs():
        body = rec.body
        if not _skip_scrub:
            body = _safe_text_for_db(body)
        effective_platform = host_platforms.get(rec.host) or rec.platform
        parsed_json = _parse_one(effective_platform, rec.command, body)
        if parsed_json:
            parser_fills[rec.command] = parser_fills.get(rec.command, 0) + 1
        rows.append({
            "snapshot_id": sid,
            "device_name": rec.host,
            "command": rec.command,
            "raw_output": body,
            "parsed_data": parsed_json,
            "platform": effective_platform,
        })
        hosts.add(rec.host)

    # 4. Apply migrations (additive ALTER + CREATE) on the target DB.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as conn:
        from olav_netops.core.tables import (
            BundleIngestsTable,
            DevicesTable,
            ParsedOutputsTable,
            RawOutputStoreTable,
            TopologyLinksTable,
        )
        for table in (
            ParsedOutputsTable(),
            RawOutputStoreTable(),
            DevicesTable(),
            TopologyLinksTable(),
            BundleIngestsTable(),
        ):
            table.ensure_schema(conn)
        from olav_netops.migrations.v0_22_portable_ingest import apply_migration
        apply_migration(conn)

    # 5. Write staging JSON + bulk_load via IngestManager.
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_file = staging_dir / f"{sid}.staging.json"
    staging_file.write_text(json.dumps(rows), encoding="utf-8")

    from olav.core.ingest_manager import IngestManager
    ingest = IngestManager(db_path=db_path, staging_dir=staging_dir)
    ingest.bulk_load()

    # 6. Devices / topology / views.
    from olav_netops.core.device_etl import populate_devices
    from olav_netops.core.topology_engine import extract_lldp_topology
    from olav_netops.core.view_builder import finalise_ingest

    populate_devices(db_path, sid)
    with duckdb.connect(str(db_path)) as conn:
        try:
            extract_lldp_topology(conn)
        except Exception:  # noqa: BLE001 — non-fatal
            pass
        try:
            finalise_ingest(conn)
        except Exception:  # noqa: BLE001 — non-fatal
            pass

    # 7. Stamp bundle provenance on the freshly-landed rows + record the
    # bundle_ingests event.
    bundle_sha256 = report.content_sha256_observed or manifest.content_sha256
    ingested_at = _now()
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE netops.raw_output_store "
            "SET bundle_id = ?, bundle_sha256 = ?, ingested_via = 'bundle' "
            "WHERE snapshot_id = ?",
            [bundle_id, bundle_sha256, sid],
        )
        conn.execute(
            """
            INSERT INTO netops.bundle_ingests
              (bundle_id, snapshot_id, bundle_sha256, collector_name,
               collector_version, collected_at, ingested_at, ingested_by,
               pre_scrubbed, salt_fingerprint, hosts_count, commands_count,
               parser_fill_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                bundle_id, sid, bundle_sha256,
                manifest.collector.name, manifest.collector.version,
                _parse_iso_or_none(manifest.collected_at),
                ingested_at,
                os.environ.get("USER") or getpass.getuser(),
                manifest.redaction.pre_scrubbed,
                manifest.redaction.salt_fingerprint,
                len(hosts), len(rows),
                json.dumps(parser_fills),
            ],
        )

    # 8. Audit.
    audit_run_id: str | None = None
    if audit_recorder is not None:
        try:
            audit_run_id = str(uuid.uuid4())
            audit_recorder.record_run_start(
                run_id=audit_run_id,
                agent_id="ingest",
                source_channel=collection_source,
            )
            try:
                _stamp_collection_source(audit_recorder, audit_run_id, collection_source)
            except Exception:  # noqa: BLE001
                pass
            audit_recorder.record_run_end(run_id=audit_run_id, status="completed")
        except Exception:  # noqa: BLE001 — non-fatal
            pass

    return IngestResult(
        bundle_id=bundle_id,
        snapshot_id=sid,
        bundle_sha256=bundle_sha256,
        collection_source=collection_source,
        hosts=len(hosts),
        commands=len(rows),
        parser_fills=parser_fills,
        audit_run_id=audit_run_id,
    )


def _parse_iso_or_none(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stamp_collection_source(recorder, run_id: str, collection_source: str) -> None:
    """Set ``audit_runs.collection_source`` for the given run_id."""
    db_path = getattr(recorder, "_db_path", None)
    if db_path is None:
        return
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE audit_runs SET collection_source = ? WHERE run_id = ?",
            [collection_source, run_id],
        )
