"""TDD tests for oc_writer.py (RED phase).

All tests should FAIL until oc_writer.py is created.
"""

import json
import duckdb
import pytest


def _make_db_with_oc_outputs():
    """Create in-memory DuckDB with netops.oc_outputs table."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA netops")
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
    return con


def _make_catalog_cache(platform, command, field_name, oc_path):
    # platform is ignored — cache is now keyed by command only
    return {command: {field_name: oc_path}}


class TestWriteOcOutputs:
    def test_write_oc_outputs_with_valid_catalog_writes_rows(self, tmp_path):
        db_file = str(tmp_path / "test.duckdb")
        con = duckdb.connect(db_file)
        con.execute("CREATE SCHEMA netops")
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

        from olav_netops.core.oc_writer import write_oc_outputs

        catalog = {"show interfaces": {"interface": "interfaces/interface/config/name"}}
        records = [{"interface": "GigabitEthernet0/0"}]

        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=records,
            platform="cisco_ios",
            command="show interfaces",
            oc_catalog_cache=catalog,
            min_leaves=1,  # bypass quality gate — this test checks write behavior
        )

        con2 = duckdb.connect(db_file)
        rows = con2.execute("SELECT * FROM netops.oc_outputs").fetchall()
        con2.close()
        assert len(rows) == 1
        assert rows[0][0] == "r1"  # device_name
        assert rows[0][2] == "openconfig-interfaces"  # oc_module

    def test_write_oc_outputs_no_catalog_entry_writes_nothing(self, tmp_path):
        """Silent skip when no catalog entry — must not raise."""
        db_file = str(tmp_path / "test.duckdb")
        con = duckdb.connect(db_file)
        con.execute("CREATE SCHEMA netops")
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

        from olav_netops.core.oc_writer import write_oc_outputs

        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=[{"interface": "Gi0/0"}],
            platform="cisco_ios",
            command="show something_unknown",
            oc_catalog_cache={},  # empty — no entry
        )

        con2 = duckdb.connect(db_file)
        rows = con2.execute("SELECT COUNT(*) FROM netops.oc_outputs").fetchone()
        con2.close()
        assert rows[0] == 0

    def test_write_oc_outputs_partial_mapping_writes_mapped_modules_only(self, tmp_path):
        """Fields without OC mapping stay out of oc_outputs; mapped fields write."""
        db_file = str(tmp_path / "test.duckdb")
        con = duckdb.connect(db_file)
        con.execute("CREATE SCHEMA netops")
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

        from olav_netops.core.oc_writer import write_oc_outputs

        catalog = {
            "show bgp": {
                "neighbor": "bgp/neighbors/neighbor/config/neighbor-address",
                # "as_number" has no oc mapping — not in catalog field_map
            }
        }
        records = [{"neighbor": "10.0.0.1", "as_number": "65001"}]

        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=records,
            platform="cisco_ios",
            command="show bgp",
            oc_catalog_cache=catalog,
            min_leaves=1,  # bypass quality gate — this test checks partial-mapping behavior
        )

        con2 = duckdb.connect(db_file)
        rows = con2.execute("SELECT oc_module FROM netops.oc_outputs").fetchall()
        con2.close()
        assert len(rows) == 1
        assert rows[0][0] == "openconfig-bgp"

    def test_write_oc_outputs_upserts_on_conflict(self, tmp_path):
        """Second call with same (device, snapshot, module) updates, not duplicates."""
        db_file = str(tmp_path / "test.duckdb")
        con = duckdb.connect(db_file)
        con.execute("CREATE SCHEMA netops")
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

        from olav_netops.core.oc_writer import write_oc_outputs

        catalog = {"show interfaces": {"interface": "interfaces/interface/config/name"}}

        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=[{"interface": "Gi0/0"}],
            platform="cisco_ios",
            command="show interfaces",
            oc_catalog_cache=catalog,
            min_leaves=1,  # bypass quality gate — this test checks upsert behavior
        )
        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=[{"interface": "Gi0/1"}],
            platform="cisco_ios",
            command="show interfaces",
            oc_catalog_cache=catalog,
            min_leaves=1,
        )

        con2 = duckdb.connect(db_file)
        count = con2.execute("SELECT COUNT(*) FROM netops.oc_outputs").fetchone()[0]
        con2.close()
        assert count == 1  # upserted, not duplicated

    def test_write_oc_outputs_failure_does_not_raise(self, tmp_path):
        """DB errors are caught and logged, not re-raised."""
        from olav_netops.core.oc_writer import write_oc_outputs

        # Use nonexistent DB path — will fail to write but must not raise
        catalog = {"show interfaces": {"interface": "interfaces/interface/config/name"}}
        write_oc_outputs(
            db_path=str(tmp_path / "nonexistent_dir" / "db.duckdb"),
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=[{"interface": "Gi0/0"}],
            platform="cisco_ios",
            command="show interfaces",
            oc_catalog_cache=catalog,
        )
        # If we get here without exception, test passes


class TestExportOcSnapshot:
    def _populate_db(self, tmp_path):
        db_file = str(tmp_path / "test.duckdb")
        con = duckdb.connect(db_file)
        con.execute("CREATE SCHEMA netops")
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
        # Insert OC data for r1
        con.execute(
            "INSERT INTO netops.oc_outputs VALUES (?, ?, ?, ?, ?)",
            ["r1", "2026-03-28", "openconfig-interfaces", '{"interfaces": {}}', "show interfaces"],
        )
        con.execute(
            "INSERT INTO netops.oc_outputs VALUES (?, ?, ?, ?, ?)",
            ["r1", "2026-03-28", "openconfig-bgp", '{"bgp": {}}', "show bgp summary"],
        )
        # Parsed outputs for r1 — 3 commands, 2 have OC coverage
        con.execute(
            "INSERT INTO netops.parsed_outputs (device_name, command, snapshot_id) VALUES (?, ?, ?)",
            ["r1", "show interfaces", "2026-03-28"],
        )
        con.execute(
            "INSERT INTO netops.parsed_outputs (device_name, command, snapshot_id) VALUES (?, ?, ?)",
            ["r1", "show bgp summary", "2026-03-28"],
        )
        con.execute(
            "INSERT INTO netops.parsed_outputs (device_name, command, snapshot_id) VALUES (?, ?, ?)",
            ["r1", "show custom-thing", "2026-03-28"],  # no OC mapping
        )
        con.close()
        return db_file

    def test_export_oc_snapshot_returns_oc_data_and_coverage_gaps(self, tmp_path):
        db_file = self._populate_db(tmp_path)

        from olav_netops.core.oc_writer import export_oc_snapshot

        con = duckdb.connect(db_file)
        result = export_oc_snapshot(con, devices=["r1"], snapshot_id="2026-03-28")
        con.close()

        assert "r1" in result
        assert "openconfig-interfaces" in result["r1"]
        assert "openconfig-bgp" in result["r1"]
        assert "coverage_gaps" in result
        # r1 has 3 parsed commands but only 2 OC modules — has a gap
        gaps = result["coverage_gaps"]
        assert any(g["device"] == "r1" for g in gaps)
        r1_gap = next(g for g in gaps if g["device"] == "r1")
        assert r1_gap["commands_in_parsed"] == 3
        assert r1_gap["oc_modules"] == 2


class TestQualityGate:
    def _make_db(self, tmp_path):
        db_file = str(tmp_path / "test.duckdb")
        con = duckdb.connect(db_file)
        con.execute("CREATE SCHEMA netops")
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

    def test_write_oc_outputs_skips_module_below_quality_threshold(self, tmp_path):
        """Modules with fewer than min_leaves meaningful leaves are not written."""
        db_file = self._make_db(tmp_path)
        from olav_netops.core.oc_writer import write_oc_outputs

        # 'platform' maps to an interfaces OC path but value "cisco" is garbage
        catalog = {
            "show version": {
                "platform": "interfaces/interface/state/last-change",
            }
        }
        records = [{"platform": "cisco"}]  # single garbage leaf

        write_oc_outputs(
            db_path=db_file,
            device_name="r1",
            snapshot_id="2026-03-28",
            raw_records=records,
            platform="cisco_ios",
            command="show version",
            oc_catalog_cache=catalog,
        )

        con = duckdb.connect(db_file)
        count = con.execute("SELECT COUNT(*) FROM netops.oc_outputs").fetchone()[0]
        con.close()
        assert count == 0, "sparse module below min_leaves threshold must not be written"

    def test_count_meaningful_leaves_ignores_none_and_empty(self):
        from olav_netops.core.oc_writer import _count_meaningful_leaves

        data = {"interfaces": {"interface": [{"state": {"last-change": None, "name": ""}}]}}
        assert _count_meaningful_leaves(data) == 0

    def test_count_meaningful_leaves_ignores_platform_names(self):
        from olav_netops.core.oc_writer import _count_meaningful_leaves

        # Known garbage values — platform name strings should not count as meaningful
        data = {"interfaces": {"interface": [{"state": {"last-change": "cisco"}}]}}
        assert _count_meaningful_leaves(data) == 0

    def test_count_meaningful_leaves_counts_real_values(self):
        from olav_netops.core.oc_writer import _count_meaningful_leaves

        data = {
            "bgp": {
                "neighbors": {
                    "neighbor": [
                        {
                            "config": {"neighbor-address": "10.0.0.1", "peer-as": 65001},
                            "state": {"session-state": "ESTABLISHED"},
                        }
                    ]
                }
            }
        }
        assert _count_meaningful_leaves(data) >= 3
