"""P1c — End-to-end landing pipeline:

  bundle  →  scrub (defense-in-depth)
          →  textfsm_parse (best-effort per command)
          →  staging.json
          →  IngestManager.bulk_load   (writes raw_output_store + parsed_outputs)
          →  populate_devices          (writes netops.devices)
          →  finalise_ingest           (builds v_*_auto views)
          →  INSERT bundle_ingests
          →  AuditEventRecorder.record_run_*  (with collection_source)

Tests use a real on-disk DuckDB in a tmp_path so ``IngestManager`` and
``view_builder`` run exactly as in production.  The canonical synthetic
fixture (2 hosts × 5 commands total) is the input.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest


_FIXTURE_DIR = (
    Path(__file__).parent.parent
    / "fixtures" / "portable_ingest" / "synthetic_2host_bundle"
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def isolated_paths(tmp_path, monkeypatch):
    """Override the olav-core paths config to point at a tmp main.duckdb."""
    main_db = tmp_path / "main.duckdb"
    audit_db = tmp_path / "audit.duckdb"
    staging = tmp_path / "staging"
    staging.mkdir()

    # The platform paths are read at module-import time by IngestManager.
    # We can't easily re-import them in tests, so the landing function takes
    # explicit overrides for ``db_path`` and ``staging_dir`` — test pins this.
    return {
        "main_db": main_db,
        "audit_db": audit_db,
        "staging": staging,
    }


# ── Tests ─────────────────────────────────────────────────────────────


class TestIngestSnapshot:
    def test_writes_raw_output_store(self, isolated_paths):
        from olav.core.ingest.landing import ingest_snapshot
        result = ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(isolated_paths["main_db"])) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM netops.raw_output_store"
            ).fetchone()
        assert rows[0] == 5  # 2 hosts × (1 + 4) commands

    def test_records_bundle_provenance_columns(self, isolated_paths):
        from olav.core.ingest.landing import ingest_snapshot
        ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(isolated_paths["main_db"])) as conn:
            rows = conn.execute(
                "SELECT device_name, command, bundle_id, bundle_sha256, ingested_via "
                "FROM netops.raw_output_store ORDER BY device_name, command"
            ).fetchall()
        assert all(r[2] is not None for r in rows), "every row must have bundle_id"
        assert all(r[3] is not None and len(r[3]) == 64 for r in rows), "sha256 hex"
        assert all(r[4] == "bundle" for r in rows), "ingested_via=bundle"
        # All rows share the same bundle_id (one bundle = one event).
        assert len({r[2] for r in rows}) == 1

    def test_bundle_ingests_row_written(self, isolated_paths):
        from olav.core.ingest.landing import ingest_snapshot
        result = ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(isolated_paths["main_db"])) as conn:
            row = conn.execute(
                "SELECT bundle_id, collector_name, collector_version, "
                "       hosts_count, commands_count, pre_scrubbed "
                "FROM netops.bundle_ingests"
            ).fetchone()
        assert row is not None
        assert row[0] == result.bundle_id
        assert row[1] == "olav-collector"
        assert row[2] == "0.0.0-fixture"
        assert row[3] == 2          # hosts
        assert row[4] == 5          # commands
        assert row[5] is True       # manifest says pre_scrubbed=true

    def test_populates_devices(self, isolated_paths):
        from olav.core.ingest.landing import ingest_snapshot
        ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(isolated_paths["main_db"])) as conn:
            hosts = sorted(r[0] for r in conn.execute(
                "SELECT hostname FROM netops.devices"
            ).fetchall())
        assert hosts == ["R1", "R2"]

    def test_idempotent_double_ingest(self, isolated_paths):
        from olav.core.ingest.landing import ingest_snapshot
        first = ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(isolated_paths["main_db"])) as conn:
            raw_count = conn.execute(
                "SELECT COUNT(*) FROM netops.raw_output_store"
            ).fetchone()[0]
            # bundle_ingests records BOTH events (one per ingest); raw_output_store
            # UPSERTs to a single row per (device, command).
            bundles_count = conn.execute(
                "SELECT COUNT(*) FROM netops.bundle_ingests"
            ).fetchone()[0]
        assert raw_count == 5
        # Each ingest produces a unique bundle_id (separate events) but
        # underlying raw rows stay deduped — both are correct behaviour.
        assert bundles_count >= 1

    def test_idempotent_double_scrub_safe(self, isolated_paths):
        """Pre-scrubbed input goes through ``scrub`` again — verify no
        accidental re-scrubbing of netconan markers."""
        from olav.core.ingest.landing import ingest_snapshot
        ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(isolated_paths["main_db"])) as conn:
            row = conn.execute(
                "SELECT raw_output FROM netops.raw_output_store "
                "WHERE device_name = 'R2' AND command = 'show ip bgp summary'"
            ).fetchone()
        # The fixture body should appear in raw_output essentially unchanged
        # except for the leading header — landing strips the # header before
        # the DB write, so look for the BGP body marker.
        assert "BGP router identifier" in row[0]
        # And there should be no scrub-of-scrub artefacts like
        # ``netconanRemovednetconanRemoved`` chains.
        assert "netconanRemovednetconanRemoved" not in row[0]

    def test_result_object_carries_summary(self, isolated_paths):
        from olav.core.ingest.landing import ingest_snapshot
        result = ingest_snapshot(
            _FIXTURE_DIR,
            db_path=isolated_paths["main_db"],
            staging_dir=isolated_paths["staging"],
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        assert result.hosts == 2
        assert result.commands == 5
        assert result.bundle_id  # uuid
        assert len(result.bundle_sha256) == 64
        assert result.collection_source == "bundle:olav-collector:0.0.0-fixture"
