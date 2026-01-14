"""Network data importer for structured database tables.

This module imports parsed JSON data from network snapshots into DuckDB tables.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from config.paths import NETWORK_SNAPSHOT_PATH


class NetworkDataImporter:
    """Import parsed network data into structured DuckDB tables."""

    def __init__(self, db_path: str | Path | None = None):
        """Initialize importer with database connection.

        Args:
            db_path: Path to database file (default: network_snapshot.duckdb)
        """
        if db_path is None:
            db_path = str(NETWORK_SNAPSHOT_PATH)

        self.db_path = Path(db_path)
        self.conn = duckdb.connect(str(self.db_path))

        # Ensure tables exist
        from olav.core.database import init_structured_tables

        init_structured_tables(str(self.db_path))

    def import_all_from_snapshot(
        self, snapshot_dir: Path, snapshot_date: str | None = None
    ) -> dict[str, int]:
        """Import all data from a snapshot directory.

        Args:
            snapshot_dir: Path to snapshot directory
            snapshot_date: Snapshot date (YYYY-MM-DD), defaults to directory name

        Returns:
            Dictionary with import statistics per table
        """
        snapshot_dir = Path(snapshot_dir)
        parsed_dir = snapshot_dir / "parsed"

        if not parsed_dir.exists():
            return {"error": f"Parsed directory not found: {parsed_dir}"}

        # Extract date from directory name if not provided
        if snapshot_date is None:
            snapshot_date = snapshot_dir.name

        stats: dict[str, int] = {
            "arp_table": 0,
            "routes": 0,
            "bgp_neighbors": 0,
            "ospf_neighbors": 0,
            "vlans": 0,
            "system_info": 0,
        }

        # Process each device directory
        for device_dir in parsed_dir.iterdir():
            if not device_dir.is_dir():
                continue

            device_name = device_dir.name

            # Import ARP table
            arp_file = device_dir / "show-arp.json"
            if arp_file.exists():
                count = self.import_arp_table(
                    device_name, snapshot_date, arp_file
                )
                stats["arp_table"] += count

            # Import routes
            routes_file = device_dir / "show-ip-route.json"
            if routes_file.exists():
                count = self.import_routes(device_name, snapshot_date, routes_file)
                stats["routes"] += count

            # Import BGP neighbors
            bgp_file = device_dir / "show-ip-bgp-summary.json"
            if bgp_file.exists():
                count = self.import_bgp_neighbors(
                    device_name, snapshot_date, bgp_file
                )
                stats["bgp_neighbors"] += count

            # Import OSPF neighbors
            ospf_file = device_dir / "show-ip-ospf-neighbor.json"
            if ospf_file.exists():
                count = self.import_ospf_neighbors(
                    device_name, snapshot_date, ospf_file
                )
                stats["ospf_neighbors"] += count

            # Import VLANs
            vlan_file = device_dir / "show-vlan.json"
            if vlan_file.exists():
                count = self.import_vlans(device_name, snapshot_date, vlan_file)
                stats["vlans"] += count

            # Import system info
            version_file = device_dir / "show-version.json"
            if version_file.exists():
                count = self.import_system_info(
                    device_name, snapshot_date, version_file
                )
                stats["system_info"] += count

        self.conn.commit()
        return stats

    def import_arp_table(
        self, device: str, snapshot_date: str, json_path: Path
    ) -> int:
        """Import ARP table data.

        Args:
            device: Device name
            snapshot_date: Snapshot date string
            json_path: Path to JSON file

        Returns:
            Number of rows imported
        """
        try:
            with open(json_path, encoding="utf-8") as f:
                parsed = json.load(f)

            data = parsed.get("data", [])
            if not data:
                return 0

            count = 0
            for row in data:
                ip_addr = row.get("ADDRESS")
                mac_addr = row.get("HARDWARE_ADDRESS")
                interface = row.get("INTERFACE")

                if not ip_addr or not mac_addr:
                    continue

                try:
                    # Use INSERT with ON CONFLICT DO UPDATE for proper upsert
                    self.conn.execute(
                        """
                        INSERT INTO arp_table
                        (snapshot_date, device_name, ip_address, mac_address, interface)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, ip_address, mac_address)
                        DO UPDATE SET interface = EXCLUDED.interface
                    """,
                        [snapshot_date, device, ip_addr, mac_addr, interface],
                    )
                    count += 1
                except Exception as e:
                    print(f"Error inserting ARP entry: {e}")
                    pass

            return count

        except Exception as e:
            print(f"Error importing ARP data from {json_path}: {e}")
            return 0

    def import_routes(
        self, device: str, snapshot_date: str, json_path: Path
    ) -> int:
        """Import routing table data.

        Args:
            device: Device name
            snapshot_date: Snapshot date string
            json_path: Path to JSON file

        Returns:
            Number of rows imported
        """
        try:
            with open(json_path, encoding="utf-8") as f:
                parsed = json.load(f)

            data = parsed.get("data", [])
            if not data:
                return 0

            count = 0
            for row in data:
                # Skip invalid entries
                protocol = row.get("protocol", "").strip()
                destination = row.get("destination", "").strip()
                via = row.get("via", "").strip()

                # Skip legend lines and invalid data
                if not destination or destination == "-" or protocol == "Codes:":
                    continue

                # Parse network/mask
                network = destination
                mask = None
                if "/" in destination:
                    network = destination

                # Insert row
                try:
                    self.conn.execute(
                        """
                        INSERT INTO routes
                        (snapshot_date, device_name, network, next_hop, protocol)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, network, next_hop)
                        DO UPDATE SET protocol = EXCLUDED.protocol
                    """,
                        [snapshot_date, device, network, via, protocol],
                    )
                    count += 1
                except Exception as e:
                    print(f"Error inserting route: {e}")
                    pass

            return count

        except Exception as e:
            print(f"Error importing routes from {json_path}: {e}")
            return 0

    def import_bgp_neighbors(
        self, device: str, snapshot_date: str, json_path: Path
    ) -> int:
        """Import BGP neighbor data.

        Args:
            device: Device name
            snapshot_date: Snapshot date string
            json_path: Path to JSON file

        Returns:
            Number of rows imported
        """
        try:
            with open(json_path, encoding="utf-8") as f:
                parsed = json.load(f)

            data = parsed.get("data", [])
            if not data:
                return 0

            # BGP summary has non-standard format, skip for now
            # This will need proper TextFSM template
            return 0

        except Exception as e:
            print(f"Error importing BGP data from {json_path}: {e}")
            return 0

    def import_ospf_neighbors(
        self, device: str, snapshot_date: str, json_path: Path
    ) -> int:
        """Import OSPF neighbor data.

        Args:
            device: Device name
            snapshot_date: Snapshot date string
            json_path: Path to JSON file

        Returns:
            Number of rows imported
        """
        try:
            with open(json_path, encoding="utf-8") as f:
                parsed = json.load(f)

            data = parsed.get("data", [])
            if not data:
                return 0

            # OSPF neighbor format needs proper parsing
            return 0

        except Exception as e:
            print(f"Error importing OSPF data from {json_path}: {e}")
            return 0

    def import_vlans(
        self, device: str, snapshot_date: str, json_path: Path
    ) -> int:
        """Import VLAN data.

        Args:
            device: Device name
            snapshot_date: Snapshot date string
            json_path: Path to JSON file

        Returns:
            Number of rows imported
        """
        try:
            with open(json_path, encoding="utf-8") as f:
                parsed = json.load(f)

            data = parsed.get("data", [])
            if not data:
                return 0

            # VLAN format needs proper parsing
            return 0

        except Exception as e:
            print(f"Error importing VLAN data from {json_path}: {e}")
            return 0

    def import_system_info(
        self, device: str, snapshot_date: str, json_path: Path
    ) -> int:
        """Import system information.

        Args:
            device: Device name
            snapshot_date: Snapshot date string
            json_path: Path to JSON file

        Returns:
            Number of rows imported
        """
        try:
            with open(json_path, encoding="utf-8") as f:
                parsed = json.load(f)

            data = parsed.get("data", [])
            if not data:
                return 0

            # System info format needs proper parsing
            return 0

        except Exception as e:
            print(f"Error importing system info from {json_path}: {e}")
            return 0

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
