"""Network data importer for structured database tables.

This module imports parsed JSON data from network snapshots into DuckDB tables.
"""

import json
from pathlib import Path

import duckdb

from config.paths import NETWORK_SNAPSHOT_PATH


class NetworkDataImporter:
    """Import parsed network data into structured DuckDB tables."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialize importer with database connection.

        Args:
            db_path: Path to database file (default: network_snapshot.duckdb)
        """
        if db_path is None:
            db_path = str(NETWORK_SNAPSHOT_PATH)

        self.db_path = Path(db_path)
        self.conn = duckdb.connect(str(self.db_path))

        # Ensure tables exist
        from olav.core.database import init_structured_tables, init_topology_db

        init_structured_tables(str(self.db_path))
        # Also ensure command_outputs table exists
        init_topology_db(str(self.db_path))

    def import_raw_command_outputs(
        self, snapshot_dir: Path, snapshot_date: str | None = None
    ) -> dict[str, int | str]:
        """Import raw command outputs from raw/ directory to raw_outputs table.

        Args:
            snapshot_dir: Path to snapshot directory (e.g., exports/snapshots/2026-01-16/)
            snapshot_date: Snapshot date (YYYY-MM-DD), defaults to directory name

        Returns:
            Dictionary with import statistics
        """
        snapshot_dir = Path(snapshot_dir)
        raw_dir = snapshot_dir / "raw"

        if not raw_dir.exists():
            return {"error": "Raw directory not found", "imported": 0, "failed": 0}

        if snapshot_date is None:
            snapshot_date = snapshot_dir.name

        imported = 0
        failed = 0

        # Process each device directory
        for device_dir in raw_dir.iterdir():
            if not device_dir.is_dir():
                continue

            device_name = device_dir.name

            # Process all .txt files
            for txt_file in device_dir.glob("*.txt"):
                try:
                    # Extract command from filename
                    command = txt_file.stem.replace("-", " ")

                    # Read raw output
                    raw_output = txt_file.read_text(encoding="utf-8", errors="ignore")

                    # Insert into database (use INSERT OR IGNORE to skip duplicates)
                    self.conn.execute(
                        """
                        INSERT INTO raw_outputs
                        (snapshot_date, device_name, command, raw_output, output_file, command_status)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, command) DO UPDATE SET
                            raw_output = EXCLUDED.raw_output,
                            output_file = EXCLUDED.output_file,
                            command_status = EXCLUDED.command_status
                        """,
                        [
                            snapshot_date,
                            device_name,
                            command,
                            raw_output,
                            str(txt_file.relative_to(snapshot_dir.parent.parent)),
                            "success",
                        ],
                    )
                    imported += 1
                except Exception as e:
                    failed += 1
                    print(f"Failed to import {txt_file}: {e}")

        return {"imported": imported, "failed": failed}

    def import_command_outputs(
        self, snapshot_dir: Path, snapshot_date: str | None = None
    ) -> dict[str, int | str]:
        """Import all parsed command outputs to unified command_outputs table.

        This is the new unified import method that replaces individual import_xxx() methods.
        It scans the parsed/ directory and imports all JSON files into command_outputs table.

        Args:
            snapshot_dir: Path to snapshot directory (e.g., exports/snapshots/2026-01-14/)
            snapshot_date: Snapshot date (YYYY-MM-DD), defaults to directory name

        Returns:
            Dictionary with import statistics:
            - total_files: Number of JSON files found
            - imported: Number of successfully imported files
            - failed: Number of failed imports
            - total_rows: Total number of data rows imported
        """
        snapshot_dir = Path(snapshot_dir)
        parsed_dir = snapshot_dir / "parsed"

        if not parsed_dir.exists():
            return {
                "error": f"Parsed directory not found: {parsed_dir}",
                "total_files": 0,
                "imported": 0,
                "failed": 0,
                "total_rows": 0,
            }

        # Extract date from directory name if not provided
        if snapshot_date is None:
            snapshot_date = snapshot_dir.name

        stats = {"total_files": 0, "imported": 0, "failed": 0, "total_rows": 0}

        # Process each device directory
        for device_dir in parsed_dir.iterdir():
            if not device_dir.is_dir():
                continue

            device_name = device_dir.name

            # Process all JSON files in the device directory
            for json_file in device_dir.glob("*.json"):
                stats["total_files"] += 1

                try:
                    # Read parsed JSON data
                    with open(json_file, encoding="utf-8") as f:
                        parsed_data = json.load(f)

                    # Extract command from filename (e.g., "show-ip-bgp-summary.json" -> "show ip bgp summary")
                    command = json_file.stem.replace("-", " ")

                    # Determine platform (could be extracted from inventory, default to cisco_ios)
                    platform = "cisco_ios"  # TODO: Get from device inventory

                    # Count rows
                    row_count = len(parsed_data) if isinstance(parsed_data, list) else 1
                    parse_success = True

                    # Check if raw file exists (for reference)
                    raw_file = snapshot_dir / "raw" / device_name / f"{json_file.stem}.txt"
                    raw_output = raw_file.read_text(encoding="utf-8") if raw_file.exists() else None

                    # Insert into command_outputs table
                    from datetime import datetime

                    now = datetime.now().isoformat()

                    self.conn.execute(
                        """
                        INSERT INTO command_outputs
                        (snapshot_date, device_name, platform, command, raw_output, 
                         parsed_data, row_count, parse_success, collected_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, command)
                        DO UPDATE SET
                            platform = EXCLUDED.platform,
                            raw_output = EXCLUDED.raw_output,
                            parsed_data = EXCLUDED.parsed_data,
                            row_count = EXCLUDED.row_count,
                            parse_success = EXCLUDED.parse_success,
                            collected_at = EXCLUDED.collected_at
                        """,
                        [
                            snapshot_date,
                            device_name,
                            platform,
                            command,
                            raw_output,
                            json.dumps(parsed_data),  # Store as JSON string
                            row_count,
                            parse_success,
                            now,
                        ],
                    )

                    stats["imported"] += 1
                    stats["total_rows"] += row_count

                except Exception as e:
                    stats["failed"] += 1
                    # Log error but continue
                    print(f"Failed to import {json_file}: {e}")

        return stats  # type: ignore[return-value]

    def import_all_from_snapshot(
        self, snapshot_dir: Path, snapshot_date: str | None = None
    ) -> dict[str, int | str]:
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
            "interfaces": 0,
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

            # Import interfaces (support multiple interface commands)
            for intf_file in device_dir.glob("show*interface*.json"):
                count = self.import_interfaces(device_name, snapshot_date, intf_file)
                stats["interfaces"] += count

            # Import ARP table
            arp_file = device_dir / "show-arp.json"
            if arp_file.exists():
                count = self.import_arp_table(device_name, snapshot_date, arp_file)
                stats["arp_table"] += count

            # Import routes
            routes_file = device_dir / "show-ip-route.json"
            if routes_file.exists():
                count = self.import_routes(device_name, snapshot_date, routes_file)
                stats["routes"] += count

            # Import BGP neighbors
            bgp_file = device_dir / "show-ip-bgp-summary.json"
            if bgp_file.exists():
                count = self.import_bgp_neighbors(device_name, snapshot_date, bgp_file)
                stats["bgp_neighbors"] += count

            # Import OSPF neighbors
            ospf_file = device_dir / "show-ip-ospf-neighbor.json"
            if ospf_file.exists():
                count = self.import_ospf_neighbors(device_name, snapshot_date, ospf_file)
                stats["ospf_neighbors"] += count

            # Import VLANs
            vlan_file = device_dir / "show-vlan.json"
            if vlan_file.exists():
                count = self.import_vlans(device_name, snapshot_date, vlan_file)
                stats["vlans"] += count

            # Import system info
            version_file = device_dir / "show-version.json"
            if version_file.exists():
                count = self.import_system_info(device_name, snapshot_date, version_file)
                stats["system_info"] += count

        self.conn.commit()
        return stats  # type: ignore[return-value]

    def import_interfaces(self, device: str, snapshot_date: str, json_path: Path) -> int:
        """Import interface data from show-interface*.json.

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

            # Support both {"data": [...]} and direct list format
            if isinstance(parsed, list):
                data = parsed
            else:
                data = parsed.get("data", [])

            if not data:
                return 0

            count = 0
            for row in data:
                # Support both uppercase and lowercase field names
                interface_name = row.get("INTERFACE") or row.get("interface")
                ip_address = row.get("IP_ADDRESS") or row.get("ip_address", "unassigned")
                status = row.get("STATUS") or row.get("status", "")
                protocol = row.get("PROTO") or row.get("proto", "")

                if not interface_name:
                    continue

                # For show ip interface brief, STATUS and PROTO are separate
                # STATUS = admin status, PROTO = protocol status
                admin_status = status if status else "down"
                oper_status = protocol if protocol else "down"

                # Skip unassigned
                if ip_address == "unassigned":
                    ip_address = None

                try:
                    self.conn.execute(
                        """
                        INSERT INTO interfaces
                        (snapshot_date, device_name, interface_name, ip_address,
                         admin_status, oper_status, protocol_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, interface_name)
                        DO UPDATE SET
                            ip_address = EXCLUDED.ip_address,
                            admin_status = EXCLUDED.admin_status,
                            oper_status = EXCLUDED.oper_status,
                            protocol_status = EXCLUDED.protocol_status
                    """,
                        [
                            snapshot_date,
                            device,
                            interface_name,
                            ip_address,
                            admin_status,
                            oper_status,
                            protocol,
                        ],
                    )
                    count += 1
                except Exception as e:
                    print(f"Error inserting interface {interface_name}: {e}")

            return count

        except Exception as e:
            print(f"Error importing interface data from {json_path}: {e}")
            return 0

    def import_arp_table(self, device: str, snapshot_date: str, json_path: Path) -> int:
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

            # Support both {"data": [...]} and direct list format
            if isinstance(parsed, list):
                data = parsed
            else:
                data = parsed.get("data", [])

            if not data:
                return 0

            count = 0
            for row in data:
                # Support both uppercase and lowercase field names
                ip_addr = row.get("ADDRESS") or row.get("address")
                mac_addr = row.get("HARDWARE_ADDRESS") or row.get("hardware_address")
                interface = row.get("INTERFACE") or row.get("interface")

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

    def import_routes(self, device: str, snapshot_date: str, json_path: Path) -> int:
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

            # Support both {"data": [...]} and direct list format
            if isinstance(parsed, list):
                data = parsed
            else:
                data = parsed.get("data", [])

            if not data:
                return 0

            count = 0
            for row in data:
                # Support both field naming conventions
                protocol = (row.get("PROTOCOL") or row.get("protocol", "")).strip()
                # Network can be from "network" field or "destination"
                network = (
                    row.get("NETWORK") or row.get("network") or row.get("destination", "")
                ).strip()
                prefix_len = row.get("prefix_length", "")
                # Next hop can be from "nexthop_ip", "next_hop", or "via"
                next_hop = (
                    row.get("NEXTHOP_IP")
                    or row.get("nexthop_ip")
                    or row.get("next_hop")
                    or row.get("via", "")
                ).strip()

                # Build full network with prefix if available
                if prefix_len and prefix_len.strip():
                    full_network = f"{network}/{prefix_len}"
                else:
                    full_network = network

                # Skip legend lines and invalid data
                if not network or network == "-" or protocol == "Codes:":
                    continue

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
                        [snapshot_date, device, full_network, next_hop, protocol],
                    )
                    count += 1
                except Exception as e:
                    print(f"Error inserting route: {e}")
                    pass

            return count

        except Exception as e:
            print(f"Error importing routes from {json_path}: {e}")
            return 0

    def import_bgp_neighbors(self, device: str, snapshot_date: str, json_path: Path) -> int:
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

            # Support both {"data": [...]} and direct list format
            if isinstance(parsed, list):
                data = parsed
            else:
                data = parsed.get("data", [])

            if not data:
                return 0

            count = 0
            for row in data:
                # Support both uppercase and snake_case field names
                neighbor = (row.get("NEIGHBOR") or row.get("bgp_neighbor", "")).strip()
                remote_as = (row.get("AS") or row.get("neighbor_as", "")).strip()
                state = (row.get("STATE") or row.get("state_or_prefixes_received", "")).strip()
                pfx_rcd = (row.get("PFX_RCD") or row.get("state_or_prefixes_received", "")).strip()
                uptime = (row.get("UP_DOWN") or row.get("up_down", "")).strip()

                # Skip invalid entries
                if not neighbor or not remote_as:
                    continue

                # Convert prefix count
                try:
                    prefix_count = int(pfx_rcd) if pfx_rcd else 0
                except ValueError:
                    prefix_count = 0

                # Insert row
                try:
                    self.conn.execute(
                        """
                        INSERT INTO bgp_neighbors
                        (snapshot_date, device_name, neighbor_ip, remote_as, state,
                         prefixes_received, uptime)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, neighbor_ip)
                        DO UPDATE SET
                            remote_as = EXCLUDED.remote_as,
                            state = EXCLUDED.state,
                            prefixes_received = EXCLUDED.prefixes_received,
                            uptime = EXCLUDED.uptime
                    """,
                        [snapshot_date, device, neighbor, remote_as, state, prefix_count, uptime],
                    )
                    count += 1
                except Exception as e:
                    print(f"Error inserting BGP neighbor: {e}")

            return count

        except Exception as e:
            print(f"Error importing BGP data from {json_path}: {e}")
            return 0

    def import_ospf_neighbors(self, device: str, snapshot_date: str, json_path: Path) -> int:
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

            # Support both {"data": [...]} and direct list format
            if isinstance(parsed, list):
                data = parsed
            else:
                data = parsed.get("data", [])

            if not data:
                return 0

            count = 0
            for row in data:
                # Support both uppercase and snake_case field names
                neighbor_id = (row.get("NEIGHBOR_ID") or row.get("neighbor_id", "")).strip()
                priority = (row.get("PRIORITY") or row.get("priority", "")).strip()
                state = (row.get("STATE") or row.get("state", "")).strip()
                ip_address = (row.get("IP_ADDRESS") or row.get("address", "")).strip()
                interface = (row.get("INTERFACE") or row.get("interface", "")).strip()

                # Skip invalid entries
                if not neighbor_id or not interface:
                    continue

                # Convert priority to int
                try:
                    priority_val = int(priority) if priority else 0
                except ValueError:
                    priority_val = 0

                # Insert row
                try:
                    self.conn.execute(
                        """
                        INSERT INTO ospf_neighbors
                        (snapshot_date, device_name, neighbor_id, neighbor_ip,
                         interface, state, priority)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, neighbor_id, interface)
                        DO UPDATE SET
                            neighbor_ip = EXCLUDED.neighbor_ip,
                            state = EXCLUDED.state,
                            priority = EXCLUDED.priority
                    """,
                        [
                            snapshot_date,
                            device,
                            neighbor_id,
                            ip_address,
                            interface,
                            state,
                            priority_val,
                        ],
                    )
                    count += 1
                except Exception as e:
                    print(f"Error inserting OSPF neighbor: {e}")

            return count

        except Exception as e:
            print(f"Error importing OSPF data from {json_path}: {e}")
            return 0

    def import_vlans(self, device: str, snapshot_date: str, json_path: Path) -> int:
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

            # Support both {"data": [...]} and direct list format
            if isinstance(parsed, list):
                data = parsed
            else:
                data = parsed.get("data", [])

            if not data:
                return 0

            count = 0
            for row in data:
                vlan_id = row.get("vlan_id", "").strip()
                vlan_name = row.get("vlan_name", "").strip()
                status = row.get("status", "").strip()

                # Skip invalid entries
                if not vlan_id:
                    continue

                # Insert row
                try:
                    self.conn.execute(
                        """
                        INSERT INTO vlans
                        (snapshot_date, device_name, vlan_id, vlan_name, status)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, device_name, vlan_id)
                        DO UPDATE SET
                            vlan_name = EXCLUDED.vlan_name,
                            status = EXCLUDED.status
                    """,
                        [snapshot_date, device, vlan_id, vlan_name, status],
                    )
                    count += 1
                except Exception as e:
                    print(f"Error inserting VLAN: {e}")

            return count

        except Exception as e:
            print(f"Error importing VLAN data from {json_path}: {e}")
            return 0

    def import_system_info(self, device: str, snapshot_date: str, json_path: Path) -> int:
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

            # Support both {"data": [...]} and direct list format
            if isinstance(parsed, list):
                data = parsed
            else:
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


def import_all_sync_data(sync_dir: Path) -> dict[str, int | str]:
    """Import all data from a sync directory (convenience wrapper).

    This function provides a simple interface for importing both raw and parsed
    data from a snapshot directory. It handles:
    1. Raw command outputs → raw_outputs table
    2. Parsed JSON files → command_outputs table

    Args:
        sync_dir: Path to snapshot directory (e.g., exports/snapshots/2026-01-16/)

    Returns:
        Dictionary with import statistics
    """
    importer = NetworkDataImporter()
    try:
        # Import raw command outputs
        raw_stats = importer.import_raw_command_outputs(sync_dir)

        # Import parsed data if available
        parsed_dir = Path(sync_dir) / "parsed"
        if parsed_dir.exists():
            parsed_stats = importer.import_command_outputs(sync_dir)
            return {
                "raw_imported": raw_stats.get("imported", 0),
                "parsed_files": parsed_stats.get("total_files", 0),
                "parsed_imported": parsed_stats.get("imported", 0),
                "total_rows": parsed_stats.get("total_rows", 0),
            }
        else:
            return {
                "raw_imported": raw_stats.get("imported", 0),
                "parsed_files": 0,
                "parsed_imported": 0,
                "total_rows": 0,
            }
    finally:
        importer.close()
