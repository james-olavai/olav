"""Tests for cab_config_extractor — snapshot-driven OC config extraction.

Architecture under test:
    Source of truth: parsed_outputs (TextFSM) + schema_catalog (field→OC path)
    Pipeline: parsed_outputs → apply_oc_mapping_cached → _flatten_oc_record → srl_config_renderer
    Topology (topology_links / LLDP) is used only for CLAB YAML, NOT for config.

Tests use an in-memory DuckDB seeded with:
    - devices (name, platform)
    - schema_catalog (platform, source_name, fields)
    - parsed_outputs (raw TextFSM records per device/command)
"""

from __future__ import annotations

import sys
from pathlib import Path
_LAB_SCRIPTS = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab" / "scripts"
if str(_LAB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LAB_SCRIPTS))

import json

import duckdb
import pytest

from cab_config_extractor import CABConfigExtractor, _flatten_oc_record, _flatten_recursive


# ---------------------------------------------------------------------------
# Fixtures: seeded in-memory DuckDB
# ---------------------------------------------------------------------------


def _seed_db(db_path: str) -> None:
    """Seed a DuckDB with devices + schema_catalog + parsed_outputs for tests."""
    con = duckdb.connect(db_path)

    # --- devices ---
    con.execute("""
        CREATE TABLE devices (
            name VARCHAR,
            platform VARCHAR,
            hostname VARCHAR,
            mgmt_ip VARCHAR,
            is_active BOOLEAN DEFAULT TRUE
        )
    """)
    con.execute("""
        INSERT INTO devices VALUES
        ('r1', 'cisco_ios', 'r1.lab', '10.255.0.1', TRUE),
        ('r2', 'cisco_ios', 'r2.lab', '10.255.0.2', TRUE)
    """)

    # --- schema_catalog ---
    con.execute("""
        CREATE TABLE schema_catalog (
            platform VARCHAR,
            source_name VARCHAR,
            source_type VARCHAR,
            fields JSON
        )
    """)
    con.execute("""
        INSERT INTO schema_catalog VALUES
        ('cisco_ios', 'show ip bgp summary', 'cli', '[
            {"name": "neighbor_ip", "openconfig_path": "network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/config/neighbor-address"},
            {"name": "neighbor_as", "openconfig_path": "network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/config/peer-as"},
            {"name": "state",       "openconfig_path": "network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state/session-state"}
        ]'),
        ('cisco_ios', 'show interfaces', 'cli', '[
            {"name": "interface",    "openconfig_path": "interfaces/interface/config/name"},
            {"name": "admin_status", "openconfig_path": "interfaces/interface/state/admin-status"},
            {"name": "ip_address",   "openconfig_path": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/config/ip"}
        ]')
    """)

    # --- parsed_outputs: raw TextFSM records ---
    con.execute("""
        CREATE TABLE parsed_outputs (
            device_name VARCHAR,
            command VARCHAR,
            parsed_data JSON,
            raw_output VARCHAR,
            snapshot_id VARCHAR
        )
    """)
    con.execute("""
        INSERT INTO parsed_outputs VALUES
        ('r1', 'show ip bgp summary',
         '[{"neighbor_ip": "10.0.0.2", "neighbor_as": "65002", "state": "Established"}]',
         '', 'snap1'),
        ('r2', 'show ip bgp summary',
         '[{"neighbor_ip": "10.0.0.1", "neighbor_as": "65001", "state": "Established"}]',
         '', 'snap1'),
        ('r1', 'show interfaces',
         '[{"interface": "GigabitEthernet1", "admin_status": "UP", "ip_address": "10.0.0.1/30"}]',
         '', 'snap1'),
        ('r2', 'show interfaces',
         '[{"interface": "GigabitEthernet2", "admin_status": "UP", "ip_address": "10.0.0.2/30"}]',
         '', 'snap1')
    """)

    # --- topology_links: LLDP only, used for YAML generation, NOT for config ---
    con.execute("""
        CREATE TABLE topology_links (
            source_device VARCHAR,
            destination_device VARCHAR,
            source_interface VARCHAR,
            destination_interface VARCHAR,
            discovery_protocol VARCHAR DEFAULT 'lldp',
            link_type VARCHAR DEFAULT 'L3',
            snapshot_id VARCHAR
        )
    """)
    con.execute("""
        INSERT INTO topology_links VALUES
        ('r1', 'r2', 'GigabitEthernet1', 'GigabitEthernet2', 'lldp', 'L3', 'snap1')
    """)

    con.close()


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "test_cab.duckdb")
    _seed_db(path)
    return path


@pytest.fixture
def extractor(db_path) -> CABConfigExtractor:
    return CABConfigExtractor(db_path=db_path)


# ---------------------------------------------------------------------------
# _flatten_oc_record: pure function unit tests
# ---------------------------------------------------------------------------


def test_flatten_oc_record_skips_unmapped_key():
    oc = {
        "_unmapped": {"some_field": "some_value"},
    }
    result = _flatten_oc_record(oc)
    assert result == []


def test_flatten_oc_record_emits_scalar_leaf():
    oc = {
        "openconfig-bgp": {
            "bgp": {
                "global": {
                    "config": {"as": 65001}
                }
            }
        }
    }
    result = _flatten_oc_record(oc)
    assert any(f["openconfig_path"] == "bgp/global/config/as" for f in result)
    as_field = next(f for f in result if f["openconfig_path"] == "bgp/global/config/as")
    assert as_field["value"] == 65001


def test_flatten_oc_record_extracts_neighbor_context():
    """BGP neighbor list → neighbor-address context propagates to sub-leaf fields."""
    oc = {
        "openconfig-bgp": {
            "bgp": {
                "neighbors": {
                    "neighbor": [{
                        "config": {
                            "neighbor-address": "10.0.0.2",
                            "peer-as": 65002,
                        }
                    }]
                }
            }
        }
    }
    result = _flatten_oc_record(oc)
    peer_as_fields = [f for f in result if f["openconfig_path"].endswith("config/peer-as")]
    assert len(peer_as_fields) == 1
    assert peer_as_fields[0]["neighbor-address"] == "10.0.0.2"
    assert peer_as_fields[0]["value"] == 65002


def test_flatten_oc_record_extracts_interface_context():
    """Interface list → interface context propagates to admin-status sub-leaf."""
    oc = {
        "openconfig-interfaces": {
            "interfaces": {
                "interface": [{
                    "config": {
                        "name": "GigabitEthernet1",
                        "admin-status": "UP",
                    }
                }]
            }
        }
    }
    result = _flatten_oc_record(oc)
    admin_fields = [f for f in result if "admin-status" in f["openconfig_path"]]
    assert len(admin_fields) >= 1
    assert admin_fields[0]["interface"] == "GigabitEthernet1"


def test_flatten_oc_record_none_values_not_emitted():
    oc = {
        "openconfig-bgp": {
            "bgp": {
                "global": {
                    "config": {"as": None, "router-id": "1.1.1.1"}
                }
            }
        }
    }
    result = _flatten_oc_record(oc)
    # None values should not appear
    assert not any(f["value"] is None for f in result)
    assert any(f["value"] == "1.1.1.1" for f in result)


def test_flatten_oc_record_module_prefix_stripped():
    """The openconfig-* module key must NOT appear in output paths."""
    oc = {
        "openconfig-interfaces": {
            "interfaces": {
                "interface": [{"config": {"name": "eth0"}}]
            }
        }
    }
    result = _flatten_oc_record(oc)
    for f in result:
        assert not f["openconfig_path"].startswith("openconfig-")


# ---------------------------------------------------------------------------
# get_schema_catalog
# ---------------------------------------------------------------------------


def test_get_schema_catalog_returns_expected_commands(extractor):
    catalog = extractor.get_schema_catalog()
    assert isinstance(catalog, dict)
    assert "show ip bgp summary" in catalog


def test_get_schema_catalog_values_are_column_lists(extractor):
    catalog = extractor.get_schema_catalog()
    for command, cols in catalog.items():
        assert isinstance(cols, list)
        assert all(isinstance(c, str) for c in cols)


# ---------------------------------------------------------------------------
# _get_device_platforms
# ---------------------------------------------------------------------------


def test_get_device_platforms_returns_platform(extractor):
    result = extractor._get_device_platforms(["r1", "r2"])
    assert result["r1"] == "cisco_ios"
    assert result["r2"] == "cisco_ios"


def test_get_device_platforms_unknown_device_absent(extractor):
    result = extractor._get_device_platforms(["r1", "nonexistent"])
    assert "r1" in result
    assert "nonexistent" not in result


def test_get_device_platforms_empty_input(extractor):
    result = extractor._get_device_platforms([])
    assert result == {}


# ---------------------------------------------------------------------------
# _query_parsed_outputs
# ---------------------------------------------------------------------------


def test_query_parsed_outputs_returns_rows_for_devices(extractor):
    rows = extractor._query_parsed_outputs(["r1"])
    assert any(r["device_name"] == "r1" for r in rows)


def test_query_parsed_outputs_filters_to_requested_devices(extractor):
    rows = extractor._query_parsed_outputs(["r1"])
    assert all(r["device_name"] == "r1" for r in rows)


def test_query_parsed_outputs_unknown_device_returns_empty(extractor):
    rows = extractor._query_parsed_outputs(["nonexistent_xyz"])
    assert rows == []


def test_query_parsed_outputs_empty_input(extractor):
    rows = extractor._query_parsed_outputs([])
    assert rows == []


# ---------------------------------------------------------------------------
# extract_oc_fields_from_snapshot
# ---------------------------------------------------------------------------


def test_extract_oc_fields_from_snapshot_produces_oc_paths(extractor):
    result = extractor.extract_oc_fields_from_snapshot(["r1"])
    assert "r1" in result
    fields = result["r1"]
    assert len(fields) > 0
    for f in fields:
        assert "openconfig_path" in f
        assert "value" in f


def test_extract_oc_fields_from_snapshot_bgp_has_neighbor_context(extractor):
    result = extractor.extract_oc_fields_from_snapshot(["r1"])
    fields = result["r1"]
    peer_as_fields = [
        f for f in fields
        if "peer-as" in f.get("openconfig_path", "")
    ]
    assert len(peer_as_fields) >= 1
    assert peer_as_fields[0].get("neighbor-address") == "10.0.0.2"


def test_extract_oc_fields_from_snapshot_interface_has_context(extractor):
    result = extractor.extract_oc_fields_from_snapshot(["r1"])
    fields = result["r1"]
    ip_fields = [
        f for f in fields
        if "config/ip" in f.get("openconfig_path", "")
    ]
    assert len(ip_fields) >= 1
    assert ip_fields[0].get("interface") == "GigabitEthernet1"


def test_extract_oc_fields_from_snapshot_no_platform_skipped(db_path):
    """Device with no entry in devices table → its parsed_outputs rows skipped."""
    import duckdb
    con = duckdb.connect(db_path)
    con.execute("INSERT INTO parsed_outputs VALUES ('unknown_dev', 'show interfaces', '[]', '', 'snap1')")
    con.close()
    extractor = CABConfigExtractor(db_path=db_path)
    result = extractor.extract_oc_fields_from_snapshot(["unknown_dev"])
    assert result.get("unknown_dev", []) == []


def test_extract_oc_fields_from_snapshot_returns_all_devices(extractor):
    result = extractor.extract_oc_fields_from_snapshot(["r1", "r2"])
    assert "r1" in result
    assert "r2" in result


# ---------------------------------------------------------------------------
# render_all_devices (full pipeline)
# ---------------------------------------------------------------------------


def test_render_all_devices_produces_srl_commands(extractor):
    result = extractor.render_all_devices(
        change_intent="Verify BGP baseline between r1 and r2",
        blast_radius_devices=["r1", "r2"],
        iface_map={"GigabitEthernet1": "ethernet-1/1", "GigabitEthernet2": "ethernet-1/1"},
    )
    assert "r1" in result
    assert "r2" in result
    assert "set /" in result["r1"]
    assert "set /" in result["r2"]


def test_render_all_devices_r1_has_bgp_peer_as(extractor):
    result = extractor.render_all_devices(
        change_intent="BGP peer-as config",
        blast_radius_devices=["r1"],
        iface_map={},
    )
    assert "65002" in result["r1"]


def test_render_all_devices_r2_has_bgp_peer_as(extractor):
    result = extractor.render_all_devices(
        change_intent="BGP peer-as config",
        blast_radius_devices=["r2"],
        iface_map={},
    )
    assert "65001" in result["r2"]


def test_render_all_devices_r1_has_interface_ip(extractor):
    result = extractor.render_all_devices(
        change_intent="Interface IP config",
        blast_radius_devices=["r1"],
        iface_map={"GigabitEthernet1": "ethernet-1/1"},
    )
    assert "10.0.0.1/30" in result["r1"]
    assert "ethernet-1/1" in result["r1"]


def test_render_all_devices_empty_blast_radius(extractor):
    result = extractor.render_all_devices(
        change_intent="anything",
        blast_radius_devices=[],
    )
    assert result == {}


def test_render_all_devices_iface_map_whitelist_applied(extractor):
    """When iface_map is non-empty, interfaces absent from it are skipped."""
    result = extractor.render_all_devices(
        change_intent="Interface config",
        blast_radius_devices=["r1"],
        iface_map={"GigabitEthernet99": "ethernet-1/99"},  # GigabitEthernet1 not in map
    )
    # GigabitEthernet1 interface commands should be absent (whitelist excludes it)
    r1_cfg = result["r1"]
    assert "ethernet-1/1" not in r1_cfg
