"""Integration tests for two-table OC design (RED phase).

Tests verify that after the Stage-2 refactor:
- parsed_outputs.parsed_data stores raw flat TextFSM dicts (not OC-nested)
- oc_outputs gets populated when schema_catalog has a mapping
- oc_outputs is empty when schema_catalog has no mapping for a command

These tests are integration-level: they call write_oc_outputs directly
and query the resulting DB state.
"""

import json
import duckdb
import pytest


def _setup_db(tmp_path):
    """Create a minimal two-table DB for integration tests."""
    db_file = str(tmp_path / "integration.duckdb")
    con = duckdb.connect(db_file)
    con.execute("CREATE SCHEMA netops")
    con.execute(
        """
        CREATE TABLE netops.parsed_outputs (
            device_name VARCHAR NOT NULL,
            command     VARCHAR NOT NULL,
            parsed_data JSON,
            snapshot_id VARCHAR,
            raw_output  TEXT,
            ingested_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE netops.oc_outputs (
            device_name VARCHAR NOT NULL,
            snapshot_id VARCHAR NOT NULL,
            oc_module   VARCHAR NOT NULL,
            oc_data     JSON    NOT NULL,
            source_cmd  VARCHAR,
            UNIQUE (device_name, snapshot_id, oc_module)
        )
        """
    )
    con.close()
    return db_file


class TestStage2TwoTableDesign:
    def test_stage2_raw_records_in_parsed_data_not_oc_mapped(self, tmp_path):
        """parsed_outputs.parsed_data must be flat TextFSM dict, not OC-nested.

        The old design stored OC-nested JSON in parsed_data. After Stage-2,
        parsed_data must be the raw TextFSM output (flat dict).
        """
        db_file = _setup_db(tmp_path)
        raw_record = {"interface": "GigabitEthernet0/0", "ip_address": "10.0.0.1"}

        con = duckdb.connect(db_file)
        con.execute(
            "INSERT INTO netops.parsed_outputs (device_name, command, parsed_data, snapshot_id) "
            "VALUES (?, ?, ?, ?)",
            ["r1", "show interfaces", json.dumps(raw_record), "2026-03-28"],
        )
        row = con.execute(
            "SELECT parsed_data FROM netops.parsed_outputs WHERE device_name = 'r1'"
        ).fetchone()
        con.close()

        parsed = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        # Must be flat (no openconfig-* top-level keys)
        assert "interface" in parsed or "ip_address" in parsed
        assert not any(k.startswith("openconfig-") for k in parsed)

    def test_stage2_oc_outputs_populated_when_catalog_exists(self, tmp_path):
        """When schema_catalog has a mapping, write_oc_outputs populates oc_outputs."""
        db_file = _setup_db(tmp_path)

        from olav_netops.core.oc_writer import write_oc_outputs

        catalog = {
            ("cisco_ios", "show interfaces"): {
                "interface": "interfaces/interface/config/name",
                "ip_address": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/config/ip",
            }
        }
        raw_records = [{"interface": "GigabitEthernet0/0", "ip_address": "10.0.0.1"}]

        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=raw_records,
            platform="cisco_ios",
            command="show interfaces",
            oc_catalog_cache=catalog,
            min_leaves=1,  # bypass quality gate — testing integration, not quality
        )

        con = duckdb.connect(db_file)
        rows = con.execute(
            "SELECT oc_module FROM netops.oc_outputs WHERE device_name = 'r1'"
        ).fetchall()
        con.close()

        assert len(rows) >= 1
        modules = [r[0] for r in rows]
        assert "openconfig-interfaces" in modules

    def test_stage2_no_catalog_parsed_outputs_written_oc_outputs_empty(self, tmp_path):
        """If no schema_catalog entry, parsed_outputs has data but oc_outputs stays empty."""
        db_file = _setup_db(tmp_path)
        raw_record = {"neighbor": "10.0.0.1", "custom_field": "value"}

        # Write to parsed_outputs (raw)
        con = duckdb.connect(db_file)
        con.execute(
            "INSERT INTO netops.parsed_outputs (device_name, command, parsed_data, snapshot_id) "
            "VALUES (?, ?, ?, ?)",
            ["r1", "show custom-thing", json.dumps(raw_record), "2026-03-28"],
        )
        con.close()

        from olav_netops.core.oc_writer import write_oc_outputs

        # No catalog entry for this command
        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=[raw_record],
            platform="cisco_ios",
            command="show custom-thing",
            oc_catalog_cache={},  # empty catalog
        )

        con2 = duckdb.connect(db_file)
        parsed_count = con2.execute(
            "SELECT COUNT(*) FROM netops.parsed_outputs WHERE device_name = 'r1'"
        ).fetchone()[0]
        oc_count = con2.execute(
            "SELECT COUNT(*) FROM netops.oc_outputs WHERE device_name = 'r1'"
        ).fetchone()[0]
        con2.close()

        assert parsed_count == 1   # parsed_outputs has data
        assert oc_count == 0       # oc_outputs is empty — gap visible
