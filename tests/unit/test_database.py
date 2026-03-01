import pytest
import duckdb
from pathlib import Path
from olav.core.database import OlavDatabase

# ---------------------------------------------------------------------------
# Schema DDL (mirrors .olav/workspace/config/sync/tools/sync_schemas.py)
# OlavDatabase does NOT auto-create schema — must be done explicitly in tests.
# ---------------------------------------------------------------------------

_DDL_DEVICES = """
CREATE TABLE IF NOT EXISTS devices (
    device_id   VARCHAR PRIMARY KEY,
    name        VARCHAR,
    hostname    VARCHAR,
    platform    VARCHAR,
    mgmt_ip     VARCHAR,
    device_type VARCHAR,
    device_role VARCHAR,
    site        VARCHAR,
    location    VARCHAR,
    vendor      VARCHAR,
    model       VARCHAR,
    site_id     VARCHAR,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active   BOOLEAN DEFAULT TRUE
)
"""

_DDL_PARSED_SEQ = "CREATE SEQUENCE IF NOT EXISTS parsed_outputs_id_seq START 1"

_DDL_PARSED_OUTPUTS = """
CREATE TABLE IF NOT EXISTS parsed_outputs (
    id          INTEGER PRIMARY KEY DEFAULT nextval('parsed_outputs_id_seq'),
    device_name VARCHAR NOT NULL,
    command     VARCHAR NOT NULL,
    parsed_data JSON    NOT NULL,
    raw_output  VARCHAR,
    snapshot_id VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_name, command, snapshot_id)
)
"""

_DDL_TOPOLOGY = """
CREATE TABLE IF NOT EXISTS topology_links (
    link_id               VARCHAR PRIMARY KEY,
    source_device         VARCHAR NOT NULL,
    source_interface      VARCHAR NOT NULL,
    destination_device    VARCHAR NOT NULL,
    destination_interface VARCHAR NOT NULL,
    discovery_protocol    VARCHAR,
    first_seen            TIMESTAMP NOT NULL,
    last_seen             TIMESTAMP NOT NULL,
    snapshot_id           VARCHAR NOT NULL,
    UNIQUE(source_device, source_interface,
           destination_device, destination_interface, snapshot_id)
)
"""


def _init_schema(conn):
    """Create the core schema on a fresh DuckDB connection."""
    conn.execute(_DDL_DEVICES)
    conn.execute(_DDL_PARSED_SEQ)
    conn.execute(_DDL_PARSED_OUTPUTS)
    conn.execute(_DDL_TOPOLOGY)


class TestDatabaseComprehensive:
    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "test.duckdb"
        db = OlavDatabase(db_path=db_path)
        _init_schema(db.conn)
        yield db
        db.close()

    def test_schema_initialization(self, db):
        tables = db.conn.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]
        assert "devices" in table_names
        assert "topology_links" in table_names
        assert "parsed_outputs" in table_names

    def test_devices_table_columns(self, db):
        columns = db.conn.execute("PRAGMA table_info('devices')").fetchall()
        col_names = [c[1] for c in columns]
        assert "device_id" in col_names
        assert "name" in col_names
        assert "is_active" in col_names

    def test_parsed_outputs_sequence(self, db):
        db.conn.execute(
            "INSERT INTO parsed_outputs (device_name, command, parsed_data, snapshot_id) VALUES ('R1', 'show version', '{}', '2026-02-24')"
        )
        db.conn.execute(
            "INSERT INTO parsed_outputs (device_name, command, parsed_data, snapshot_id) VALUES ('R2', 'show version', '{}', '2026-02-24')"
        )

        ids = db.conn.execute("SELECT id FROM parsed_outputs ORDER BY id").fetchall()
        assert ids[0][0] == 1
        assert ids[1][0] == 2

    def test_topology_links_unique_constraint(self, db):
        db.conn.execute(
            "INSERT INTO topology_links (link_id, source_device, source_interface, destination_device, destination_interface, first_seen, last_seen, snapshot_id) VALUES ('L1', 'R1', 'Gi0/1', 'R2', 'Gi0/1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '2026-02-24')"
        )

        with pytest.raises(duckdb.ConstraintException):
            db.conn.execute(
                "INSERT INTO topology_links (link_id, source_device, source_interface, destination_device, destination_interface, first_seen, last_seen, snapshot_id) VALUES ('L2', 'R1', 'Gi0/1', 'R2', 'Gi0/1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '2026-02-24')"
            )

    def test_read_only_mode(self, tmp_path):
        db_path = tmp_path / "readonly.duckdb"
        rw = OlavDatabase(db_path=db_path)
        _init_schema(rw.conn)
        rw.close()

        db_ro = OlavDatabase(db_path=db_path, read_only=True)
        with pytest.raises(
            duckdb.InvalidInputException, match="attached in read-only mode"
        ):
            db_ro.conn.execute("INSERT INTO devices (device_id) VALUES ('D1')")
        db_ro.close()
