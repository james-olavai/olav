"""Unit tests for olav_netops.core.topology_engine.

Covers the R70 YAML-driven refactor:
  * load_discovery_protocols YAML parsing + cache
  * _pick field coalescing
  * extract_lldp_topology end-to-end on in-memory DuckDB with synthetic
    parsed_outputs rows covering CDP, LLDP, and a user-declared custom protocol
  * _make_link_id determinism + bidirectional collapse
"""
from __future__ import annotations

import json

import duckdb
import pytest

from olav_netops.core import topology_engine as te


@pytest.fixture(autouse=True)
def _clear_cache():
    te._PROTOCOLS_CACHE = None
    yield
    te._PROTOCOLS_CACHE = None


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute("CREATE SCHEMA netops")
    c.execute(
        "CREATE TABLE netops.parsed_outputs ("
        "device_name VARCHAR, command VARCHAR, parsed_data JSON, "
        "snapshot_id VARCHAR)"
    )
    c.execute(
        "CREATE TABLE netops.raw_output_store ("
        "device_name VARCHAR, command VARCHAR, raw_output TEXT, "
        "snapshot_id VARCHAR)"
    )
    c.execute(
        "CREATE TABLE netops.devices ("
        "hostname VARCHAR, platform VARCHAR)"
    )
    yield c
    c.close()


def _prime_protocols(protocols: dict) -> None:
    te._PROTOCOLS_CACHE = protocols


# ──────────────────────────────────────────────────────────────────────────
# _pick
# ──────────────────────────────────────────────────────────────────────────

class TestPick:
    def test_first_field_wins(self):
        assert te._pick({"a": "x", "b": "y"}, ["a", "b"]) == "x"

    def test_falls_through_empty(self):
        assert te._pick({"a": "", "b": "y"}, ["a", "b"]) == "y"

    def test_list_takes_first(self):
        assert te._pick({"a": ["hello"]}, ["a"]) == "hello"

    def test_missing_returns_empty(self):
        assert te._pick({"a": "x"}, ["b", "c"]) == ""

    def test_normalises_whitespace(self):
        assert te._pick({"a": "  spaced  "}, ["a"]) == "spaced"


# ──────────────────────────────────────────────────────────────────────────
# _make_link_id
# ──────────────────────────────────────────────────────────────────────────

class TestMakeLinkId:
    def test_deterministic(self):
        a = te._make_link_id("R1", "Gi0/0", "R2", "Gi0/0")
        b = te._make_link_id("R1", "Gi0/0", "R2", "Gi0/0")
        assert a == b

    def test_bidirectional_collapse(self):
        """A→B and B→A produce the same link_id."""
        a = te._make_link_id("R1", "Gi0/0", "R2", "Gi0/1")
        b = te._make_link_id("R2", "Gi0/1", "R1", "Gi0/0")
        assert a == b

    def test_case_insensitive(self):
        a = te._make_link_id("R1", "GI0/0", "r2", "gi0/1")
        b = te._make_link_id("r1", "gi0/0", "R2", "GI0/1")
        assert a == b


# ──────────────────────────────────────────────────────────────────────────
# extract_lldp_topology — YAML-driven ETL
# ──────────────────────────────────────────────────────────────────────────

class TestExtractTopology:
    def test_no_protocols_returns_zero(self, conn):
        _prime_protocols({})
        assert te.extract_lldp_topology(conn) == 0

    def test_cdp_and_lldp_ingest(self, conn):
        _prime_protocols({
            "cdp": {
                "name": "CDP",
                "link_type": "L2",
                "commands": ["show cdp neighbors detail"],
                "local_interface_fields": ["local_interface"],
                "neighbor_device_fields": ["NEIGHBOR_NAME"],
                "neighbor_interface_fields": ["NEIGHBOR_INTERFACE"],
            },
            "lldp": {
                "name": "LLDP",
                "link_type": "L2",
                "commands": ["show lldp neighbors detail"],
                "local_interface_fields": ["local_interface"],
                "neighbor_device_fields": ["NEIGHBOR_NAME"],
                "neighbor_interface_fields": ["NEIGHBOR_INTERFACE"],
            },
        })
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R1", "show cdp neighbors detail",
             json.dumps([{
                 "local_interface": "Gi0/0",
                 "NEIGHBOR_NAME": "R2",
                 "NEIGHBOR_INTERFACE": "Gi0/0",
             }]),
             "snap-1"],
        )
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R2", "show lldp neighbors detail",
             json.dumps([{
                 "local_interface": "Gi0/1",
                 "NEIGHBOR_NAME": "R3",
                 "NEIGHBOR_INTERFACE": "Gi0/2",
             }]),
             "snap-1"],
        )
        n = te.extract_lldp_topology(conn)
        assert n == 2
        rows = conn.execute(
            "SELECT discovery_protocol, link_type, source_device, destination_device "
            "FROM netops.topology_links ORDER BY source_device"
        ).fetchall()
        assert rows == [
            ("CDP", "L2", "R1", "R2"),
            ("LLDP", "L2", "R2", "R3"),
        ]

    def test_custom_protocol_is_extracted(self, conn):
        """A brand-new protocol added only in YAML — no code changes."""
        _prime_protocols({
            "isis": {
                "name": "ISIS",
                "link_type": "L3",
                "commands": ["show isis adjacency"],
                "local_interface_fields": ["interface"],
                "neighbor_device_fields": ["system_id"],
                "neighbor_interface_fields": ["neighbor_interface"],
            },
        })
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R1", "show isis adjacency",
             json.dumps([{
                 "interface": "ge-0/0/1",
                 "system_id": "R2.iso",
                 "neighbor_interface": "ge-0/0/2",
             }]),
             "snap-1"],
        )
        assert te.extract_lldp_topology(conn) == 1
        row = conn.execute(
            "SELECT discovery_protocol, link_type FROM netops.topology_links"
        ).fetchone()
        assert row == ("ISIS", "L3")

    def test_self_link_skipped(self, conn):
        _prime_protocols({
            "cdp": {
                "name": "CDP", "link_type": "L2",
                "commands": ["show cdp neighbors detail"],
                "local_interface_fields": ["local_interface"],
                "neighbor_device_fields": ["NEIGHBOR_NAME"],
                "neighbor_interface_fields": ["NEIGHBOR_INTERFACE"],
            },
        })
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R1", "show cdp neighbors detail",
             json.dumps([{
                 "local_interface": "Gi0/0",
                 "NEIGHBOR_NAME": "R1",  # self
                 "NEIGHBOR_INTERFACE": "Gi0/1",
             }]),
             "snap-1"],
        )
        assert te.extract_lldp_topology(conn) == 0

    def test_field_coalesce_across_versions(self, conn):
        """ntc-templates changed field case between versions — _pick handles both."""
        _prime_protocols({
            "cdp": {
                "name": "CDP", "link_type": "L2",
                "commands": ["show cdp neighbors detail"],
                "local_interface_fields": ["local_interface", "LOCAL_INTERFACE"],
                "neighbor_device_fields": ["NEIGHBOR_NAME", "neighbor_name"],
                "neighbor_interface_fields": ["NEIGHBOR_INTERFACE", "neighbor_interface"],
            },
        })
        # Use lowercase keys only — old-style ntc-templates
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R1", "show cdp neighbors detail",
             json.dumps([{
                 "local_interface": "Gi0/0",
                 "neighbor_name": "R2",
                 "neighbor_interface": "Gi0/1",
             }]),
             "snap-1"],
        )
        assert te.extract_lldp_topology(conn) == 1

    def test_bidirectional_collapse_via_link_id(self, conn):
        _prime_protocols({
            "lldp": {
                "name": "LLDP", "link_type": "L2",
                "commands": ["show lldp neighbors detail"],
                "local_interface_fields": ["local_interface"],
                "neighbor_device_fields": ["NEIGHBOR_NAME"],
                "neighbor_interface_fields": ["NEIGHBOR_INTERFACE"],
            },
        })
        # R1 sees R2, R2 sees R1 — should end up as ONE link row, not two
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R1", "show lldp neighbors detail",
             json.dumps([{
                 "local_interface": "Gi0/0",
                 "NEIGHBOR_NAME": "R2", "NEIGHBOR_INTERFACE": "Gi0/1",
             }]), "snap-1"],
        )
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R2", "show lldp neighbors detail",
             json.dumps([{
                 "local_interface": "Gi0/1",
                 "NEIGHBOR_NAME": "R1", "NEIGHBOR_INTERFACE": "Gi0/0",
             }]), "snap-1"],
        )
        te.extract_lldp_topology(conn)
        assert conn.execute("SELECT COUNT(*) FROM netops.topology_links").fetchone()[0] == 1

    def test_empty_parsed_data_skipped(self, conn):
        _prime_protocols({
            "cdp": {
                "name": "CDP", "link_type": "L2",
                "commands": ["show cdp neighbors detail"],
                "local_interface_fields": ["local_interface"],
                "neighbor_device_fields": ["NEIGHBOR_NAME"],
                "neighbor_interface_fields": ["NEIGHBOR_INTERFACE"],
            },
        })
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
            ["R1", "show cdp neighbors detail", json.dumps([]), "snap-1"],
        )
        assert te.extract_lldp_topology(conn) == 0


# ──────────────────────────────────────────────────────────────────────────
# load_discovery_protocols
# ──────────────────────────────────────────────────────────────────────────

class TestLoadDiscoveryProtocols:
    def test_missing_file_returns_empty(self, monkeypatch):
        from pathlib import Path
        monkeypatch.setattr(te, "_protocols_path", lambda: Path("/nope/nowhere.yaml"))
        assert te.load_discovery_protocols(force_reload=True) == {}

    def test_valid_yaml(self, monkeypatch, tmp_path):
        p = tmp_path / "discovery_protocols.yaml"
        p.write_text(
            "protocols:\n"
            "  cdp:\n"
            "    name: CDP\n"
            "    commands: [show cdp neighbors detail]\n"
        )
        monkeypatch.setattr(te, "_protocols_path", lambda: p)
        result = te.load_discovery_protocols(force_reload=True)
        assert "cdp" in result
        assert result["cdp"]["name"] == "CDP"

    def test_wrong_top_level_shape_returns_empty(self, monkeypatch, tmp_path):
        p = tmp_path / "discovery_protocols.yaml"
        p.write_text("protocols: [not, a, mapping]\n")
        monkeypatch.setattr(te, "_protocols_path", lambda: p)
        assert te.load_discovery_protocols(force_reload=True) == {}
