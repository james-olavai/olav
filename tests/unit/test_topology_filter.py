"""``olav.core.topology.filter`` — adjacency-view query + BFS filter.

Pinned behaviour:
  * center+hops keeps only rows within N hops of the centre
  * roles / sites / name_like filter via SQL JOIN to netops.devices
  * Missing view (BGP/OSPF not ingested) → empty header, no crash
  * snapshot_id filter only applies when the view has the column
"""
from __future__ import annotations

import duckdb
import pytest


def _setup_db(tmp_path):
    """Fresh DB with topology_links + netops.devices populated."""
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute("""
            CREATE TABLE netops.devices (
                hostname VARCHAR PRIMARY KEY,
                model    VARCHAR,
                os_version VARCHAR,
                vendor   VARCHAR,
                ip_address VARCHAR,
                role     VARCHAR,
                site     VARCHAR
            )
        """)
        # 1 border, 3 edges hanging off, 5 APs hanging off the edges.
        conn.execute("""
            INSERT INTO netops.devices VALUES
                ('BORDER-1', 'C9500',     '17.9', 'Cisco', '10.0.0.1', 'border', 'site-A'),
                ('EDGE-1',   'C9300',     '17.9', 'Cisco', '10.0.1.1', 'access', 'site-A'),
                ('EDGE-2',   'C9300',     '17.9', 'Cisco', '10.0.2.1', 'access', 'site-A'),
                ('EDGE-3',   'C9300',     '17.9', 'Cisco', '10.0.3.1', 'access', 'site-B'),
                ('AP-1',     'AP-3802',   '17.6', 'Cisco', '10.0.1.10','wireless','site-A'),
                ('AP-2',     'AP-3802',   '17.6', 'Cisco', '10.0.1.11','wireless','site-A'),
                ('AP-3',     'AP-3802',   '17.6', 'Cisco', '10.0.2.10','wireless','site-A'),
                ('AP-4',     'AP-3802',   '17.6', 'Cisco', '10.0.3.10','wireless','site-B'),
                ('AP-5',     'AP-3802',   '17.6', 'Cisco', '10.0.3.11','wireless','site-B')
        """)
        conn.execute("""
            CREATE TABLE netops.topology_links (
                link_id              VARCHAR PRIMARY KEY,
                source_device        VARCHAR NOT NULL,
                source_interface     VARCHAR NOT NULL,
                destination_device   VARCHAR NOT NULL,
                destination_interface VARCHAR NOT NULL,
                discovery_protocol   VARCHAR,
                link_type            VARCHAR,
                link_status          VARCHAR,
                link_speed           VARCHAR,
                first_seen           TIMESTAMP,
                last_seen            TIMESTAMP,
                last_verified        TIMESTAMP,
                status_changes       INTEGER,
                snapshot_id          VARCHAR,
                platform             VARCHAR
            )
        """)
        # BORDER-1 → EDGE-1/2/3   (3 uplinks)
        # EDGE-1 → AP-1, AP-2
        # EDGE-2 → AP-3
        # EDGE-3 → AP-4, AP-5
        for i, (s, si, d, di) in enumerate([
            ('BORDER-1', 'Te1/1', 'EDGE-1', 'Te1/0/1'),
            ('BORDER-1', 'Te1/2', 'EDGE-2', 'Te1/0/1'),
            ('BORDER-1', 'Te1/3', 'EDGE-3', 'Te1/0/1'),
            ('EDGE-1',   'Gi1/0/1', 'AP-1', 'Gi0'),
            ('EDGE-1',   'Gi1/0/2', 'AP-2', 'Gi0'),
            ('EDGE-2',   'Gi1/0/1', 'AP-3', 'Gi0'),
            ('EDGE-3',   'Gi1/0/1', 'AP-4', 'Gi0'),
            ('EDGE-3',   'Gi1/0/2', 'AP-5', 'Gi0'),
        ], start=1):
            conn.execute(
                "INSERT INTO netops.topology_links VALUES "
                "(?, ?, ?, ?, ?, 'CDP', 'l2', 'up', '1G', "
                " current_timestamp, current_timestamp, current_timestamp, 0, 'snap-1', 'cisco_ios')",
                [f"l{i}", s, si, d, di],
            )
    return db


# ── Center + hops ─────────────────────────────────────────────────────


def _data_rows(table: str) -> list[str]:
    """Strip header + separator from a Markdown table, return data rows."""
    return [
        ln for ln in table.splitlines()
        if ln.startswith("|") and "Source" not in ln and "---" not in ln
    ]


class TestCenterHopsFilter:
    def test_zero_hops_yields_no_edges(self, tmp_path):
        """hops=0 ⇒ in_radius = {center} only; with the 'both endpoints'
        rule, no edges are kept (centre has no in-radius peer)."""
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        table = build_adjacencies_view(db, center="BORDER-1", hops=0)
        assert _data_rows(table) == []

    def test_one_hop_keeps_center_to_neighbors_only(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        table = build_adjacencies_view(db, center="BORDER-1", hops=1)
        # 1-hop in_radius = {BORDER-1, EDGE-1, EDGE-2, EDGE-3}.
        # Edges among them = the 3 BORDER↔EDGE links.  EDGE↔AP edges have
        # AP not in radius → dropped.
        rows = _data_rows(table)
        assert len(rows) == 3
        assert all("BORDER-1" in r and ("EDGE-1" in r or "EDGE-2" in r or "EDGE-3" in r) for r in rows)

    def test_two_hops_pulls_full_local_cluster(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        table = build_adjacencies_view(db, center="BORDER-1", hops=2)
        # 2-hop in_radius = entire graph; all 8 links kept.
        assert len(_data_rows(table)) == 8

    def test_center_not_in_topology_returns_empty(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        table = build_adjacencies_view(db, center="GHOST", hops=2)
        assert _data_rows(table) == []


# ── Role / site / name_like filters ──────────────────────────────────


class TestSqlFilters:
    def test_role_filter(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        # Only source_device with role='border' → just BORDER-1's 3 uplinks.
        table = build_adjacencies_view(db, roles=["border"])
        rows = [ln for ln in table.splitlines() if ln.startswith("| BORDER-1")]
        assert len(rows) == 3
        # No edge-sourced rows leak through.
        edge_rows = [ln for ln in table.splitlines() if ln.startswith("| EDGE-")]
        assert len(edge_rows) == 0

    def test_site_filter(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        # site-A source devices: BORDER-1, EDGE-1, EDGE-2.
        table = build_adjacencies_view(db, sites=["site-A"])
        srcs = {ln.split("|")[1].strip()
                for ln in table.splitlines()
                if ln.startswith("|") and "Source" not in ln and "---" not in ln}
        assert "BORDER-1" in srcs
        assert "EDGE-1" in srcs
        assert "EDGE-2" in srcs
        assert "EDGE-3" not in srcs

    def test_name_like_filter(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        table = build_adjacencies_view(db, name_like="EDGE-%")
        rows = [ln for ln in table.splitlines()
                if ln.startswith("| EDGE-")]
        assert len(rows) == 5  # EDGE-1→AP-1/2 + EDGE-2→AP-3 + EDGE-3→AP-4/5


# ── Snapshot + missing views ─────────────────────────────────────────


class TestSnapshotAndMissingViews:
    def test_snapshot_id_filter(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        # Existing data has snapshot_id='snap-1'; filter for another → empty.
        table = build_adjacencies_view(db, snapshot_id="snap-X")
        rows = [ln for ln in table.splitlines() if ln.startswith("|") and "Source" not in ln and "---" not in ln]
        assert len(rows) == 0

    def test_bgp_missing_view_returns_header_only(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        # v_show_ip_bgp_neighbors_auto doesn't exist in this fixture DB.
        table = build_adjacencies_view(db, protocol="bgp")
        # Header present, no data rows.
        lines = table.strip().splitlines()
        assert len(lines) == 2  # header + separator only
        assert "Source" in lines[0]


# ── device_metadata helper ───────────────────────────────────────────


class TestBuildDeviceMetadata:
    def test_default_returns_full_table(self, tmp_path):
        from olav.core.topology.filter import build_device_metadata
        db = _setup_db(tmp_path)
        m = build_device_metadata(db)
        assert len(m) == 9
        assert m["BORDER-1"]["model"] == "C9500"
        assert m["BORDER-1"]["role"] == "border"
        assert m["BORDER-1"]["ip"] == "10.0.0.1"

    def test_subset_via_hostnames(self, tmp_path):
        from olav.core.topology.filter import build_device_metadata
        db = _setup_db(tmp_path)
        m = build_device_metadata(db, hostnames=["BORDER-1", "EDGE-1", "GHOST"])
        # GHOST isn't in the table → silently dropped.
        assert set(m.keys()) == {"BORDER-1", "EDGE-1"}


# ── Protocol enum sanity ─────────────────────────────────────────────


class TestProtocolEnum:
    def test_unknown_protocol_raises(self, tmp_path):
        from olav.core.topology.filter import build_adjacencies_view
        db = _setup_db(tmp_path)
        import pytest as _pytest
        with _pytest.raises(ValueError, match="unknown protocol"):
            build_adjacencies_view(db, protocol="ip_sla")  # type: ignore[arg-type]
