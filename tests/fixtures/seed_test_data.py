"""Seed netops tables with synthetic data for Tier 1 LLM E2E tests.

Usage:
    python tests/fixtures/seed_test_data.py

Run from the project directory where .olav/ exists.
"""
import json
import sys
from pathlib import Path

DB_PATH = Path(".olav/databases/main.duckdb")


def seed():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    import duckdb

    with duckdb.connect(str(DB_PATH)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS netops")

        # Create tables directly (no dependency on olav-netops package)
        for ddl in [
            """CREATE TABLE IF NOT EXISTS netops.devices (
                hostname VARCHAR NOT NULL UNIQUE, ip_address VARCHAR, platform VARCHAR,
                site VARCHAR, role VARCHAR, vendor VARCHAR, model VARCHAR,
                os_version VARCHAR, last_seen TIMESTAMP, metadata JSON)""",
            """CREATE TABLE IF NOT EXISTS netops.parsed_outputs (
                device_name VARCHAR NOT NULL, command VARCHAR NOT NULL,
                parsed_data JSON, snapshot_id VARCHAR NOT NULL,
                raw_output TEXT, raw_output_hash VARCHAR, ingested_at TIMESTAMP,
                UNIQUE (device_name, command, snapshot_id))""",
            """CREATE TABLE IF NOT EXISTS netops.raw_output_store (
                device_name VARCHAR NOT NULL, command VARCHAR NOT NULL,
                raw_output TEXT, snapshot_id VARCHAR, updated_at TIMESTAMPTZ,
                UNIQUE (device_name, command))""",
            """CREATE TABLE IF NOT EXISTS netops.topology_links (
                link_id VARCHAR PRIMARY KEY, source_device VARCHAR NOT NULL,
                source_interface VARCHAR NOT NULL, destination_device VARCHAR NOT NULL,
                destination_interface VARCHAR NOT NULL, discovery_protocol VARCHAR,
                link_type VARCHAR, link_status VARCHAR, link_speed VARCHAR,
                first_seen TIMESTAMP NOT NULL, last_seen TIMESTAMP NOT NULL,
                last_verified TIMESTAMP, status_changes INTEGER,
                snapshot_id VARCHAR NOT NULL, platform VARCHAR)""",
            """CREATE TABLE IF NOT EXISTS netops.oc_outputs (
                device_name VARCHAR NOT NULL, oc_module VARCHAR NOT NULL,
                oc_data JSON, snapshot_id VARCHAR NOT NULL,
                UNIQUE (device_name, oc_module, snapshot_id))""",
        ]:
            con.execute(ddl)

        # Seed devices
        devices = [
            ("R1", "192.168.100.101", "juniper_junos", "Juniper", "vsrx", "18.4R3-S3"),
            ("R2", "2.2.2.2", "cisco_ios", "Cisco", "ISRV", "17.1.1"),
            ("R3", "3.3.3.3", "cisco_ios", "Cisco", None, "17.15.1"),
            ("R4", "4.4.4.4", "cisco_ios", "Cisco", None, "17.15.1"),
            ("SW1", "192.168.100.105", "cisco_ios", "Cisco", None, "17.15.1"),
            ("SW2", "192.168.100.106", "cisco_ios", "Cisco", None, "17.15.1"),
        ]
        for hostname, ip, plat, vendor, model, ver in devices:
            con.execute("""
                INSERT INTO netops.devices (hostname, ip_address, platform, vendor, model, os_version, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, NOW())
                ON CONFLICT (hostname) DO NOTHING
            """, [hostname, ip, plat, vendor, model, ver])

        # Seed parsed_outputs
        snap = "snap_test_seed"

        # BGP summary for R2
        bgp_data = json.dumps([
            {"BGP_NEIGH": "4.4.4.4", "NEIGH_AS": "65001", "STATE_PFXRCD": "0", "UP_DOWN": "2w3d"},
            {"BGP_NEIGH": "10.1.12.1", "NEIGH_AS": "65000", "STATE_PFXRCD": "0", "UP_DOWN": "2w3d"},
        ])
        con.execute("""
            INSERT INTO netops.parsed_outputs (device_name, command, parsed_data, snapshot_id)
            VALUES ('R2', 'show ip bgp summary', ?::JSON, ?)
            ON CONFLICT (device_name, command, snapshot_id) DO NOTHING
        """, [bgp_data, snap])

        # Interface brief for R2
        iface_data = json.dumps([
            {"INTF": "GigabitEthernet1", "IPADDR": "10.1.12.2", "STATUS": "up", "PROTO": "up"},
            {"INTF": "Loopback0", "IPADDR": "2.2.2.2", "STATUS": "up", "PROTO": "up"},
            {"INTF": "GigabitEthernet3", "IPADDR": "unassigned", "STATUS": "administratively down", "PROTO": "down"},
        ])
        con.execute("""
            INSERT INTO netops.parsed_outputs (device_name, command, parsed_data, snapshot_id)
            VALUES ('R2', 'show ip interface brief', ?::JSON, ?)
            ON CONFLICT (device_name, command, snapshot_id) DO NOTHING
        """, [iface_data, snap])

        # Topology
        links = [
            ("seed-1", "R1", "ge-0/0/0", "R2", "Gi1", "LLDP"),
            ("seed-2", "R2", "Gi2", "R4", "Eth0/0", "CDP"),
            ("seed-3", "R3", "Eth0/1", "SW1", "Eth0/0", "CDP"),
        ]
        for link_id, src, src_if, dst, dst_if, proto in links:
            con.execute("""
                INSERT INTO netops.topology_links
                    (link_id, source_device, source_interface, destination_device,
                     destination_interface, discovery_protocol, link_type, link_status,
                     first_seen, last_seen, snapshot_id)
                VALUES (?, ?, ?, ?, ?, ?, 'L2', 'up', NOW(), NOW(), ?)
                ON CONFLICT (link_id) DO NOTHING
            """, [link_id, src, src_if, dst, dst_if, proto, snap])

    print(f"Seeded: {len(devices)} devices, 2 parsed_outputs, {len(links)} topology links")


if __name__ == "__main__":
    seed()
