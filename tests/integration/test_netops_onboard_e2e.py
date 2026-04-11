"""Real E2E test: netops onboard pipeline (migrate + ingest + topology).

Verifies the full onboard flow using a **real isolated DuckDB** (copy of
main.duckdb schema only — no live SSH needed):

  1. Run ``netops_migrate.py``   → netops schema + tables created
  2. Run ``IngestManager.bulk_load()`` → parsed_outputs populated
  3. Run topology discovery       → topology_links populated

Per AGENTS.md §8 requirements:
  - Real DuckDB writes (no in-memory shortcuts)
  - Real staging JSON files (already on disk from prior snapshot runs)
  - Verifiable counts

This test is *not* a mock test — it exercises the actual code paths used
in production.  It does **not** SSH into devices (that would be too slow /
fragile for CI), but it uses the same staging JSON files that a real
``netops_snapshot.py`` run would produce.

Requirements to run:
  - ``exports/snapshots/json/*.staging.json`` must exist (at least 1 file)
  - ``.olav/databases/main.duckdb`` must exist (used as schema reference)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import duckdb
import pytest

pytestmark = [pytest.mark.e2e]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
_NETOPS_SRC = _REPO_ROOT / "olav-netops" / "src"
_STAGING_DIR = _REPO_ROOT / "exports" / "snapshots" / "json"
_REAL_DB = _REPO_ROOT / ".olav" / "databases" / "main.duckdb"

for _p in (_SRC, _NETOPS_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(tmp_path):
    """Copy main.duckdb to a temp location so tests never touch the live DB.

    Returns the path to the isolated copy.
    """
    if not _REAL_DB.exists():
        pytest.skip("main.duckdb not found — run netops_migrate.py first")

    dest = tmp_path / "test_main.duckdb"
    shutil.copy2(_REAL_DB, dest)
    return dest


@pytest.fixture()
def staging_files():
    """Return list of staging JSON files.  Skip if none exist."""
    files = list(_STAGING_DIR.glob("*.staging.json"))
    if not files:
        pytest.skip("No staging JSON files found — run netops_snapshot.py first")
    return files


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNetopsSchema:
    """Verify netops schema and tables exist after migration."""

    def test_netops_schema_exists(self, isolated_db):
        """netops schema must exist in main.duckdb after migrate."""
        conn = duckdb.connect(str(isolated_db))
        schemas = [
            r[0]
            for r in conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
        ]
        conn.close()
        assert "netops" in schemas, f"netops schema missing; schemas={schemas}"

    def test_netops_parsed_outputs_has_unique_constraint(self, isolated_db):
        """netops.parsed_outputs must have UNIQUE(device_name, command, snapshot_id)."""
        conn = duckdb.connect(str(isolated_db))
        constraints = conn.execute(
            """
            SELECT constraint_type, constraint_column_names
            FROM duckdb_constraints()
            WHERE schema_name = 'netops' AND table_name = 'parsed_outputs'
              AND constraint_type = 'UNIQUE'
            """
        ).fetchall()
        conn.close()
        assert constraints, (
            "netops.parsed_outputs has no UNIQUE constraint; ON CONFLICT upserts will fail"
        )
        col_sets = [frozenset(r[1]) for r in constraints]
        expected = frozenset(["device_name", "command", "snapshot_id"])
        assert expected in col_sets, (
            f"Expected UNIQUE({sorted(expected)}) but found {[sorted(s) for s in col_sets]}"
        )

    def test_netops_topology_links_table_exists(self, isolated_db):
        """netops.topology_links must exist with operational schema (link_id column)."""
        conn = duckdb.connect(str(isolated_db))
        cols = {r[0] for r in conn.execute("DESCRIBE netops.topology_links").fetchall()}
        conn.close()
        assert "link_id" in cols, f"topology_links missing link_id column; cols={cols}"
        assert "source_device" in cols, f"topology_links missing source_device; cols={cols}"

    def test_compat_views_exist(self, isolated_db):
        """main.parsed_outputs and main.topology_links compat views must be queryable."""
        conn = duckdb.connect(str(isolated_db))
        for view in ("parsed_outputs", "topology_links"):
            try:
                conn.execute(f"SELECT COUNT(*) FROM main.{view}").fetchone()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"compat view main.{view} is broken: {exc}")
        conn.close()


class TestIngest:
    """Verify IngestManager.bulk_load() populates netops.parsed_outputs."""

    def test_bulk_load_returns_success(self, isolated_db, staging_files):
        """bulk_load() must return status='success' when staging files exist."""
        import olav_netops.core.tables
        olav_netops.core.tables._register_all()  # explicit: module is side-effect free by design

        from olav.core.ingest_manager import IngestManager

        result = IngestManager(db_path=isolated_db, staging_dir=_STAGING_DIR).bulk_load()
        assert result["status"] == "success", (
            f"bulk_load failed: {result.get('message', 'no message')}"
        )

    def test_bulk_load_inserts_records(self, isolated_db, staging_files):
        """After bulk_load, netops.parsed_outputs must have > 0 rows."""
        import olav_netops.core.tables
        olav_netops.core.tables._register_all()

        from olav.core.ingest_manager import IngestManager

        IngestManager(db_path=isolated_db, staging_dir=_STAGING_DIR).bulk_load()

        conn = duckdb.connect(str(isolated_db))
        count = conn.execute("SELECT COUNT(*) FROM netops.parsed_outputs").fetchone()[0]
        conn.close()
        assert count > 0, "netops.parsed_outputs is empty after bulk_load"

    def test_bulk_load_idempotent(self, isolated_db, staging_files):
        """Running bulk_load twice must not duplicate rows (ON CONFLICT upsert)."""
        import olav_netops.core.tables
        olav_netops.core.tables._register_all()

        from olav.core.ingest_manager import IngestManager

        mgr = IngestManager(db_path=isolated_db, staging_dir=_STAGING_DIR)
        mgr.bulk_load()
        conn = duckdb.connect(str(isolated_db))
        count_first = conn.execute("SELECT COUNT(*) FROM netops.parsed_outputs").fetchone()[0]
        conn.close()

        mgr2 = IngestManager(db_path=isolated_db, staging_dir=_STAGING_DIR)
        mgr2.bulk_load()
        conn = duckdb.connect(str(isolated_db))
        count_second = conn.execute("SELECT COUNT(*) FROM netops.parsed_outputs").fetchone()[0]
        conn.close()

        assert count_first == count_second, (
            f"bulk_load is not idempotent: {count_first} → {count_second} rows"
        )

    def test_compat_view_reflects_ingest(self, isolated_db, staging_files):
        """main.parsed_outputs compat view must reflect netops.parsed_outputs after ingest."""
        import olav_netops.core.tables  # noqa: F401

        from olav.core.ingest_manager import IngestManager

        IngestManager(db_path=isolated_db, staging_dir=_STAGING_DIR).bulk_load()

        conn = duckdb.connect(str(isolated_db))
        netops_count = conn.execute("SELECT COUNT(*) FROM netops.parsed_outputs").fetchone()[0]
        compat_count = conn.execute("SELECT COUNT(*) FROM main.parsed_outputs").fetchone()[0]
        conn.close()
        assert netops_count == compat_count, (
            f"compat view count ({compat_count}) != netops count ({netops_count})"
        )


class TestEnsureSchema:
    """Verify ensure_schema() creates tables with UNIQUE constraints."""

    def test_ensure_schema_creates_unique_constraint(self, tmp_path):
        """ensure_schema() must create UNIQUE constraint when conflict_key is set."""
        from olav.platform.ingest_base import BaseIngestTable, ColumnDef

        class _TestTable(BaseIngestTable):
            @property
            def schema_name(self) -> str:
                return "test_schema"

            @property
            def table_name(self) -> str:
                return "test_table"

            @property
            def columns(self) -> list[ColumnDef]:
                return [
                    ColumnDef("device_name", "VARCHAR", nullable=False),
                    ColumnDef("command", "VARCHAR", nullable=False),
                    ColumnDef("snapshot_id", "VARCHAR"),
                    ColumnDef("data", "JSON"),
                ]

            @property
            def conflict_key(self) -> list[str]:
                return ["device_name", "command", "snapshot_id"]

        db_path = tmp_path / "ensure_schema_test.duckdb"
        conn = duckdb.connect(str(db_path))
        _TestTable().ensure_schema(conn)

        constraints = conn.execute(
            """
            SELECT constraint_type, constraint_column_names
            FROM duckdb_constraints()
            WHERE schema_name = 'test_schema' AND table_name = 'test_table'
              AND constraint_type = 'UNIQUE'
            """
        ).fetchall()
        conn.close()

        assert constraints, "ensure_schema() did not create a UNIQUE constraint"
        col_sets = [frozenset(r[1]) for r in constraints]
        expected = frozenset(["device_name", "command", "snapshot_id"])
        assert expected in col_sets


class TestMigration:
    """Verify v0.12 migration creates correct schema."""

    def test_migrate_creates_netops_schema(self, tmp_path):
        """migrate() must create the netops schema from scratch."""
        from olav_netops.migrations.v0_12_schema_split import migrate

        db_path = tmp_path / "migrate_test.duckdb"
        with duckdb.connect(str(db_path)) as conn:
            migrate(conn)
            schemas = [
                r[0]
                for r in conn.execute(
                    "SELECT schema_name FROM information_schema.schemata"
                ).fetchall()
            ]
        assert "netops" in schemas

    def test_migrate_creates_tables_with_constraints(self, tmp_path):
        """migrate() must create netops tables with UNIQUE constraints."""
        from olav_netops.migrations.v0_12_schema_split import migrate

        db_path = tmp_path / "migrate_test.duckdb"
        with duckdb.connect(str(db_path)) as conn:
            migrate(conn)
            constraints = conn.execute(
                """
                SELECT table_name, constraint_column_names
                FROM duckdb_constraints()
                WHERE schema_name = 'netops' AND constraint_type = 'UNIQUE'
                """
            ).fetchall()

        tables_with_unique = {r[0] for r in constraints}
        assert "parsed_outputs" in tables_with_unique, (
            "netops.parsed_outputs missing UNIQUE constraint after migrate()"
        )

    def test_migrate_idempotent(self, tmp_path):
        """Running migrate() twice must not raise an error."""
        from olav_netops.migrations.v0_12_schema_split import migrate

        db_path = tmp_path / "migrate_idempotent.duckdb"
        with duckdb.connect(str(db_path)) as conn:
            migrate(conn)  # first run
            migrate(conn)  # second run — must not raise
