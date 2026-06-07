"""Tests for olav_netops.core.tables.

Verifies table definitions, schema names, column definitions, conflict keys,
and schema creation via in-memory DuckDB.
"""
from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")


class TestTableDefinitions:
    """Verify static table metadata."""

    def test_parsed_outputs_schema_name(self):
        from olav_netops.core.tables import ParsedOutputsTable
        assert ParsedOutputsTable.schema_name == "netops"

    def test_parsed_outputs_table_name(self):
        from olav_netops.core.tables import ParsedOutputsTable
        assert ParsedOutputsTable.table_name == "parsed_outputs"

    def test_parsed_outputs_has_required_columns(self):
        from olav_netops.core.tables import ParsedOutputsTable
        names = {c.name for c in ParsedOutputsTable.columns}
        assert {"device_name", "command", "parsed_data", "snapshot_id"}.issubset(names)

    def test_parsed_outputs_conflict_key(self):
        from olav_netops.core.tables import ParsedOutputsTable
        assert ParsedOutputsTable.conflict_key == ["device_name", "command", "snapshot_id"]

    def test_devices_schema_name(self):
        from olav_netops.core.tables import DevicesTable
        assert DevicesTable.schema_name == "netops"

    def test_devices_table_name(self):
        from olav_netops.core.tables import DevicesTable
        assert DevicesTable.table_name == "devices"

    def test_devices_conflict_key(self):
        from olav_netops.core.tables import DevicesTable
        assert DevicesTable.conflict_key == ["hostname"]

    def test_topology_links_schema_name(self):
        from olav_netops.core.tables import TopologyLinksTable
        assert TopologyLinksTable.schema_name == "netops"

    def test_topology_links_table_name(self):
        from olav_netops.core.tables import TopologyLinksTable
        assert TopologyLinksTable.table_name == "topology_links"

    def test_topology_links_has_link_id(self):
        from olav_netops.core.tables import TopologyLinksTable
        names = {c.name for c in TopologyLinksTable.columns}
        assert "link_id" in names

    def test_oc_outputs_schema_name(self):
        from olav_netops.core.tables import OcOutputsTable
        assert OcOutputsTable.schema_name == "netops"

    def test_oc_outputs_conflict_key(self):
        from olav_netops.core.tables import OcOutputsTable
        assert "oc_module" in OcOutputsTable.conflict_key

    def test_all_table_classes_have_columns(self):
        from olav_netops.core.tables import (
            DevicesTable,
            OcOutputsTable,
            ParsedOutputsTable,
            TopologyLinksTable,
        )
        for cls in [ParsedOutputsTable, DevicesTable, TopologyLinksTable, OcOutputsTable]:
            assert len(cls.columns) > 0, f"{cls.__name__} must have columns"


class TestEnsureSchema:
    """Verify ensure_schema() creates tables in DuckDB."""

    def _in_memory_conn(self):
        conn = duckdb.connect(":memory:")
        conn.execute("CREATE SCHEMA netops")
        return conn

    def _table_exists(self, conn, schema: str, table: str) -> bool:
        result = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=? AND table_name=?",
            [schema, table],
        ).fetchone()
        return bool(result and result[0] > 0)

    def test_ensure_schema_creates_parsed_outputs(self):
        from olav_netops.core.tables import ParsedOutputsTable
        conn = self._in_memory_conn()
        ParsedOutputsTable().ensure_schema(conn)
        assert self._table_exists(conn, "netops", "parsed_outputs")

    def test_ensure_schema_creates_devices(self):
        from olav_netops.core.tables import DevicesTable
        conn = self._in_memory_conn()
        DevicesTable().ensure_schema(conn)
        assert self._table_exists(conn, "netops", "devices")

    def test_ensure_schema_creates_topology_links(self):
        from olav_netops.core.tables import TopologyLinksTable
        conn = self._in_memory_conn()
        TopologyLinksTable().ensure_schema(conn)
        assert self._table_exists(conn, "netops", "topology_links")

    def test_ensure_schema_idempotent(self):
        """Calling ensure_schema twice must not raise."""
        from olav_netops.core.tables import DevicesTable
        conn = self._in_memory_conn()
        DevicesTable().ensure_schema(conn)
        DevicesTable().ensure_schema(conn)  # second call — should not raise

    def test_parsed_outputs_has_device_name_column(self):
        from olav_netops.core.tables import ParsedOutputsTable
        conn = self._in_memory_conn()
        ParsedOutputsTable().ensure_schema(conn)
        cols = [
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='netops' AND table_name='parsed_outputs'"
            ).fetchall()
        ]
        assert "device_name" in cols
        assert "command" in cols
