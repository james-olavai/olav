"""TDD tests for OcOutputsTable (RED phase).

All tests should FAIL until OcOutputsTable is added to tables.py.
"""

import duckdb
import pytest


class TestOcOutputsTableDeclaration:
    def test_table_name(self):
        from olav_netops.core.tables import OcOutputsTable

        t = OcOutputsTable()
        assert t.table_name == "oc_outputs"

    def test_schema_name(self):
        from olav_netops.core.tables import OcOutputsTable

        t = OcOutputsTable()
        assert t.schema_name == "netops"

    def test_columns(self):
        from olav_netops.core.tables import OcOutputsTable

        t = OcOutputsTable()
        col_names = [c.name for c in t.columns]
        assert "device_name" in col_names
        assert "snapshot_id" in col_names
        assert "oc_module" in col_names
        assert "oc_data" in col_names
        assert "source_cmd" in col_names

    def test_conflict_key(self):
        from olav_netops.core.tables import OcOutputsTable

        t = OcOutputsTable()
        assert set(t.conflict_key) == {"device_name", "snapshot_id", "oc_module"}

    def test_qualified_name(self):
        from olav_netops.core.tables import OcOutputsTable

        t = OcOutputsTable()
        assert t.qualified_name == "netops.oc_outputs"

    def test_ensure_schema_creates_table_idempotently(self):
        from olav_netops.core.tables import OcOutputsTable

        con = duckdb.connect(":memory:")
        t = OcOutputsTable()
        t.ensure_schema(con)
        # second call must not raise
        t.ensure_schema(con)
        result = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'netops' AND table_name = 'oc_outputs'"
        ).fetchone()
        assert result is not None

    def test_registered_in_table_registry(self):
        from olav.platform.ingest_base import TableRegistry
        import olav_netops.core.tables  # ensure registration side-effect runs  # noqa: F401

        assert "oc_outputs" in TableRegistry._tables
