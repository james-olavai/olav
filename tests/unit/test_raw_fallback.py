"""TDD tests for raw_output_store fallback — ISSUE-RAW-01/02/04.

Run: python -m pytest tests/unit/test_raw_fallback.py -v
"""
import duckdb
import pytest


@pytest.fixture
def db():
    """In-memory DuckDB with netops schema + test data."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA netops")

    # parsed_outputs — time-sliced (APPEND)
    con.execute("""
        CREATE TABLE netops.parsed_outputs (
            device_name VARCHAR, command VARCHAR, parsed_data JSON,
            snapshot_id VARCHAR, raw_output TEXT, ingested_at TIMESTAMP
        )
    """)

    # raw_output_store — latest state (UPSERT)
    con.execute("""
        CREATE TABLE netops.raw_output_store (
            device_name VARCHAR, command VARCHAR, raw_output TEXT,
            snapshot_id VARCHAR, updated_at TIMESTAMP,
            PRIMARY KEY (device_name, command)
        )
    """)

    # topology_links
    con.execute("""
        CREATE TABLE netops.topology_links (
            link_id VARCHAR PRIMARY KEY,
            source_device VARCHAR NOT NULL, source_interface VARCHAR NOT NULL,
            destination_device VARCHAR NOT NULL, destination_interface VARCHAR NOT NULL,
            discovery_protocol VARCHAR, link_type VARCHAR, link_status VARCHAR,
            link_speed VARCHAR, first_seen TIMESTAMP NOT NULL, last_seen TIMESTAMP NOT NULL,
            last_verified TIMESTAMP, status_changes INTEGER,
            snapshot_id VARCHAR NOT NULL, platform VARCHAR
        )
    """)

    # devices
    con.execute("""
        CREATE TABLE netops.devices (
            hostname VARCHAR PRIMARY KEY, ip_address VARCHAR,
            platform VARCHAR, vendor VARCHAR
        )
    """)

    # --- Seed data ---

    # R2 (IOS) — parsed LLDP works
    con.execute("""
        INSERT INTO netops.parsed_outputs VALUES
        ('R2', 'show cdp neighbors detail',
         '[{"local_interface":"Gi2","neighbor_name":"R4","neighbor_interface":"Et0/0"}]',
         'snap1', NULL, NOW())
    """)

    # R1 (Junos) — parsed LLDP MISSING (TextFSM failed)
    # But raw exists
    con.execute("""
        INSERT INTO netops.raw_output_store VALUES
        ('R1', 'show lldp neighbors',
         'Local Interface    Parent Interface    Chassis Id          Port info          System Name\nge-0/0/2           -                   50:00:00:03:00:02   to_R1_Gi2          R3.local\nge-0/0/0           -                   aa:bb:cc:dd:ee:ff   Ethernet0/0        WAN',
         'snap1', NOW())
    """)

    # R1 BGP — parsed MISSING, raw EXISTS
    con.execute("""
        INSERT INTO netops.raw_output_store VALUES
        ('R1', 'show bgp summary',
         'Peer                     AS      InPkt     OutPkt    OutQ   Flaps Last Up/Dwn State\n3.3.3.3               65000      98779     100260       0       0 4w3d Establ\n10.1.12.2             65001      64501      65478       0       2 2w6d Establ',
         'snap1', NOW())
    """)

    # Devices
    con.execute("INSERT INTO netops.devices VALUES ('R1','192.168.100.101','juniper_junos','Juniper')")
    con.execute("INSERT INTO netops.devices VALUES ('R2','2.2.2.2','cisco_ios','Cisco')")
    con.execute("INSERT INTO netops.devices VALUES ('R3','3.3.3.3','cisco_ios','Cisco')")
    con.execute("INSERT INTO netops.devices VALUES ('R4','4.4.4.4','cisco_ios','Cisco')")

    yield con
    con.close()


# ═══════════════════════════════════════════════════════════════════
# RAW-01: Topology ETL raw fallback
# ═══════════════════════════════════════════════════════════════════

class TestTopologyRawFallback:
    """Topology ETL should extract links from raw when parsed is missing."""

    def test_parsed_links_extracted(self, db):
        """Baseline: R2→R4 CDP link from parsed_outputs works."""
        from olav.core.topology_engine import extract_lldp_topology
        count = extract_lldp_topology(db)
        links = db.execute("SELECT source_device, destination_device FROM netops.topology_links").fetchall()
        assert any(l[0] == "R2" and l[1] == "R4" for l in links), f"R2→R4 missing: {links}"

    def test_raw_lldp_fallback_extracts_r1_links(self, db):
        """R1 has no parsed LLDP but raw exists — should extract R1→R3 link."""
        from olav.core.topology_engine import extract_lldp_topology
        extract_lldp_topology(db)
        links = db.execute("SELECT source_device, destination_device FROM netops.topology_links").fetchall()
        r1_links = [(s, d) for s, d in links if s == "R1"]
        assert len(r1_links) >= 1, f"R1 should have ≥1 link from raw fallback, got: {r1_links}"
        assert any(d.startswith("R3") for _, d in r1_links), f"R1→R3 link missing: {r1_links}"

    def test_no_duplicate_links_after_fallback(self, db):
        """Running ETL twice should not create duplicate links."""
        from olav.core.topology_engine import extract_lldp_topology
        extract_lldp_topology(db)
        extract_lldp_topology(db)
        count = db.execute("SELECT COUNT(*) FROM netops.topology_links").fetchone()[0]
        unique = db.execute("SELECT COUNT(DISTINCT link_id) FROM netops.topology_links").fetchone()[0]
        assert count == unique, f"Duplicates: {count} rows but {unique} unique"


# ═══════════════════════════════════════════════════════════════════
# RAW-04: raw_output_store UPSERT verification
# ═══════════════════════════════════════════════════════════════════

class TestRawUpsert:
    """raw_output_store should overwrite (UPSERT) not append."""

    def test_upsert_overwrites_same_device_command(self, db):
        """Second insert for same (device, command) should overwrite."""
        db.execute("""
            INSERT OR REPLACE INTO netops.raw_output_store
            VALUES ('R1', 'show bgp summary', 'NEW OUTPUT', 'snap2', NOW())
        """)
        count = db.execute(
            "SELECT COUNT(*) FROM netops.raw_output_store WHERE device_name='R1' AND command='show bgp summary'"
        ).fetchone()[0]
        assert count == 1, f"Expected 1 row after upsert, got {count}"

        raw = db.execute(
            "SELECT raw_output FROM netops.raw_output_store WHERE device_name='R1' AND command='show bgp summary'"
        ).fetchone()[0]
        assert raw == "NEW OUTPUT", f"Should be overwritten, got: {raw[:50]}"

    def test_upsert_does_not_grow(self, db):
        """Multiple upserts should not increase row count."""
        before = db.execute("SELECT COUNT(*) FROM netops.raw_output_store").fetchone()[0]
        for i in range(5):
            db.execute(f"""
                INSERT OR REPLACE INTO netops.raw_output_store
                VALUES ('R1', 'show bgp summary', 'output_{i}', 'snap{i}', NOW())
            """)
        after = db.execute("SELECT COUNT(*) FROM netops.raw_output_store").fetchone()[0]
        assert after == before, f"Row count grew: {before} → {after}"


# ═══════════════════════════════════════════════════════════════════
# RAW-02: execute_sql fallback query pattern
# ═══════════════════════════════════════════════════════════════════

class TestQueryFallback:
    """Fallback SQL pattern should find R1 BGP data in raw when parsed is empty."""

    def test_parsed_bgp_empty_for_r1(self, db):
        """Precondition: R1 has no parsed BGP data."""
        count = db.execute(
            "SELECT COUNT(*) FROM netops.parsed_outputs WHERE device_name='R1' AND command LIKE '%bgp%'"
        ).fetchone()[0]
        assert count == 0

    def test_raw_fallback_finds_r1_bgp(self, db):
        """Fallback query finds R1 BGP in raw_output_store."""
        rows = db.execute("""
            SELECT device_name, command, raw_output
            FROM netops.raw_output_store
            WHERE command LIKE '%bgp%'
              AND device_name NOT IN (
                  SELECT DISTINCT device_name FROM netops.parsed_outputs
                  WHERE command LIKE '%bgp%'
              )
        """).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "R1"
        assert "Establ" in rows[0][2]

    def test_fallback_does_not_return_devices_with_parsed_data(self, db):
        """If R2 has parsed BGP, fallback should NOT return R2."""
        # Add R2 parsed BGP
        db.execute("""
            INSERT INTO netops.parsed_outputs VALUES
            ('R2', 'show ip bgp summary',
             '[{"neighbor":"4.4.4.4","state":"Established"}]',
             'snap1', NULL, NOW())
        """)
        # Also add R2 raw
        db.execute("""
            INSERT OR REPLACE INTO netops.raw_output_store VALUES
            ('R2', 'show ip bgp summary', 'raw R2 bgp', 'snap1', NOW())
        """)

        rows = db.execute("""
            SELECT device_name FROM netops.raw_output_store
            WHERE command LIKE '%bgp%'
              AND device_name NOT IN (
                  SELECT DISTINCT device_name FROM netops.parsed_outputs
                  WHERE command LIKE '%bgp%'
              )
        """).fetchall()
        devices = [r[0] for r in rows]
        assert "R2" not in devices, "R2 has parsed data, should not appear in fallback"
        assert "R1" in devices, "R1 should still appear (no parsed)"
