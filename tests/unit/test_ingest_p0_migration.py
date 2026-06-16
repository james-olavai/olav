"""P0 DDL migration contract — portable snapshot ingest.

Covers:
  * audit.duckdb — ``audit_runs.collection_source`` column added by
    ``olav.core.migrations.v0_22_audit_collection_source``.
  * main.duckdb (netops) — ``netops.raw_output_store`` gains
    ``bundle_id`` / ``bundle_sha256`` / ``ingested_via`` columns, and a
    new ``netops.bundle_ingests`` table appears, both via
    ``olav_netops.migrations.v0_22_portable_ingest``.
  * Backfill — pre-existing ``audit_runs`` rows get
    ``collection_source='live_ssh'``.

Tests use in-memory DuckDB connections so they run with no external
dependency on a real audit/main DB.

See dev_docs/76 §6 + ADR-0008 follow-up for the design.
"""
from __future__ import annotations

import duckdb
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def audit_conn():
    """Fresh in-memory connection seeded with the pre-migration audit_runs schema.

    Mirrors the v0.21.x DDL exactly so the migration's behaviour on a
    real production DB is exercised end-to-end.
    """
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE audit_runs (
            run_id        VARCHAR PRIMARY KEY,
            start_time    TIMESTAMP,
            end_time      TIMESTAMP,
            status        VARCHAR,
            agent_id      VARCHAR,
            session_id    VARCHAR,
            thread_id     VARCHAR,
            user_id       VARCHAR,
            source_channel VARCHAR
        )
    """)
    # Seed two pre-migration rows so we can verify the backfill path.
    conn.execute(
        "INSERT INTO audit_runs (run_id, status, agent_id) VALUES (?, ?, ?)",
        ["r-001", "completed", "netops"],
    )
    conn.execute(
        "INSERT INTO audit_runs (run_id, status, agent_id) VALUES (?, ?, ?)",
        ["r-002", "completed", "core"],
    )
    yield conn
    conn.close()


@pytest.fixture()
def netops_conn():
    """Fresh in-memory connection with pre-migration netops.raw_output_store."""
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA netops")
    conn.execute("""
        CREATE TABLE netops.raw_output_store (
            device_name VARCHAR NOT NULL,
            command     VARCHAR NOT NULL,
            raw_output  TEXT    NOT NULL,
            snapshot_id VARCHAR,
            updated_at  TIMESTAMP,
            platform    VARCHAR,
            UNIQUE (device_name, command)
        )
    """)
    conn.execute(
        "INSERT INTO netops.raw_output_store "
        "(device_name, command, raw_output, snapshot_id, platform) "
        "VALUES (?, ?, ?, ?, ?)",
        ["R2", "show version", "Cisco IOS XE Software, Version 17.01.01\n", "snap_pre", "cisco_ios"],
    )
    yield conn
    conn.close()


def _columns_of(conn, qualified_name: str) -> dict[str, str]:
    if "." in qualified_name:
        schema, table = qualified_name.split(".", 1)
    else:
        schema, table = "main", qualified_name
    rows = conn.execute(
        "SELECT column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchall()
    return {name: dtype for name, dtype in rows}


def _table_exists(conn, qualified_name: str) -> bool:
    schema, table = qualified_name.split(".", 1) if "." in qualified_name else ("main", qualified_name)
    row = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchone()
    return (row[0] if row else 0) > 0


# ── audit.duckdb migration ────────────────────────────────────────────


class TestAuditCollectionSourceMigration:
    def test_collection_source_column_added(self, audit_conn):
        from olav.core.migrations.v0_22_audit_collection_source import apply_migration
        apply_migration(audit_conn)
        cols = _columns_of(audit_conn, "audit_runs")
        assert "collection_source" in cols, f"missing column, have: {sorted(cols)}"
        assert "VARCHAR" in cols["collection_source"].upper()

    def test_existing_rows_backfilled_to_live_ssh(self, audit_conn):
        from olav.core.migrations.v0_22_audit_collection_source import apply_migration
        apply_migration(audit_conn)
        rows = audit_conn.execute(
            "SELECT run_id, collection_source FROM audit_runs ORDER BY run_id"
        ).fetchall()
        assert rows == [("r-001", "live_ssh"), ("r-002", "live_ssh")]

    def test_migration_is_idempotent(self, audit_conn):
        from olav.core.migrations.v0_22_audit_collection_source import apply_migration
        apply_migration(audit_conn)
        # Second application must not raise nor double-backfill.
        apply_migration(audit_conn)
        cols = _columns_of(audit_conn, "audit_runs")
        assert "collection_source" in cols

    def test_post_migration_inserts_set_explicit_value(self, audit_conn):
        from olav.core.migrations.v0_22_audit_collection_source import apply_migration
        apply_migration(audit_conn)
        audit_conn.execute(
            "INSERT INTO audit_runs (run_id, collection_source) VALUES (?, ?)",
            ["r-003", "bundle:olav-collector:0.1.0"],
        )
        val = audit_conn.execute(
            "SELECT collection_source FROM audit_runs WHERE run_id = 'r-003'"
        ).fetchone()
        assert val == ("bundle:olav-collector:0.1.0",)


# ── main.duckdb netops migration ──────────────────────────────────────


class TestNetopsPortableIngestMigration:
    def test_raw_output_store_gains_bundle_columns(self, netops_conn):
        from olav_netops.migrations.v0_22_portable_ingest import apply_migration
        apply_migration(netops_conn)
        cols = _columns_of(netops_conn, "netops.raw_output_store")
        assert "bundle_id" in cols
        assert "bundle_sha256" in cols
        assert "ingested_via" in cols
        for c in ("bundle_id", "bundle_sha256", "ingested_via"):
            assert "VARCHAR" in cols[c].upper(), f"{c} type is {cols[c]}, expected VARCHAR"

    def test_existing_raw_output_rows_preserved(self, netops_conn):
        from olav_netops.migrations.v0_22_portable_ingest import apply_migration
        apply_migration(netops_conn)
        row = netops_conn.execute(
            "SELECT device_name, command, bundle_id "
            "FROM netops.raw_output_store WHERE device_name = 'R2'"
        ).fetchone()
        assert row == ("R2", "show version", None)

    def test_bundle_ingests_table_created(self, netops_conn):
        from olav_netops.migrations.v0_22_portable_ingest import apply_migration
        apply_migration(netops_conn)
        assert _table_exists(netops_conn, "netops.bundle_ingests")
        cols = _columns_of(netops_conn, "netops.bundle_ingests")
        for expected in (
            "bundle_id", "snapshot_id", "bundle_sha256", "collector_name",
            "collector_version", "collected_at", "ingested_at", "ingested_by",
            "pre_scrubbed", "salt_fingerprint", "hosts_count", "commands_count",
            "parser_fill_summary",
        ):
            assert expected in cols, f"bundle_ingests missing column {expected}, have {sorted(cols)}"

    def test_migration_is_idempotent_netops(self, netops_conn):
        from olav_netops.migrations.v0_22_portable_ingest import apply_migration
        apply_migration(netops_conn)
        apply_migration(netops_conn)  # must not raise
        assert _table_exists(netops_conn, "netops.bundle_ingests")

    def test_inserting_a_bundle_row_works(self, netops_conn):
        from olav_netops.migrations.v0_22_portable_ingest import apply_migration
        apply_migration(netops_conn)
        netops_conn.execute(
            """
            INSERT INTO netops.bundle_ingests
            (bundle_id, snapshot_id, bundle_sha256, collector_name,
             collector_version, hosts_count, commands_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ["b-001", "snap_xyz", "deadbeef" * 8, "olav-collector", "0.1.0", 2, 5],
        )
        row = netops_conn.execute(
            "SELECT bundle_id, snapshot_id, hosts_count FROM netops.bundle_ingests"
        ).fetchone()
        assert row == ("b-001", "snap_xyz", 2)
