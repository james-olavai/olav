"""Raw snapshot data importer with TextFSM parsing.

This module imports raw CLI data from exports/snapshots/{date}/raw/ and:
1. Parses with TextFSM to extract structured data
2. Directly stores to parsed_outputs table as JSON

Design (v2.0):
    Raw CLI output → TextFSM Parse → parsed_outputs table (JSON)
    • show-interfaces.txt → TextFSM → parsed_outputs (JSON)
    • show-version.txt → TextFSM → parsed_outputs (JSON)

Usage:
    from .raw_importer import import_sync_data
    result = import_sync_data(sync_dir)
"""

import json
import logging
from pathlib import Path
from datetime import datetime

import duckdb

logger = logging.getLogger(__name__)


def import_sync_data(sync_dir: Path) -> dict[str, int]:
    """Import snapshot data: raw files → TextFSM parse → parsed_outputs table.

    Stage 1: Parse raw CLI data with TextFSM, insert to parsed_outputs as JSON
    Stage 2: Legacy - import pre-parsed JSON if present

    Args:
        sync_dir: Path to snapshot directory (e.g., exports/snapshots/2026-02-13/)

    Returns:
        Dictionary with import statistics
    """
    sync_dir = Path(sync_dir)
    snapshot_date = sync_dir.name  # Directory name as date
    raw_dir = sync_dir / "raw"

    if not raw_dir.exists():
        logger.warning(f"No raw directory found at {raw_dir}")
        return {"raw_imported": 0, "parsed_imported": 0}

    from olav.core.database import get_database

    db = get_database()
    conn = db.conn

    try:
        # Stage 1: Parse raw data directly into specific tables
        parsed_count = _import_parsed_raw_data(conn, raw_dir, snapshot_date)
        
        # Stage 2: Legacy - import pre-parsed JSON if present  
        parsed_dir = sync_dir / "parsed"
        json_count = 0
        if parsed_dir.exists():
            json_count = _import_parsed_outputs(conn, sync_dir, snapshot_date)
        
        # 🔧 CRITICAL: Commit transaction to persist data to disk
        conn.commit()
        
        return {
            "raw_imported": parsed_count,
            "parsed_imported": json_count
        }
    except Exception as e:
        logger.error(f"Import failed: {e}")
        return {"raw_imported": 0, "parsed_imported": 0}


def _import_parsed_raw_data(
    conn: duckdb.DuckDBPyConnection, 
    raw_dir: Path, 
    snapshot_date: str,
) -> int:
    """Parse raw CLI files with TextFSM and insert to parsed_outputs table.
    
    v2.0 simplified path: Raw → TextFSM → parsed_outputs (JSON) or topology_links
    
    Returns:
        Number of successfully parsed commands
    """
    from olav.core.registry import get_command_registry
    
    registry = get_command_registry()
    parsed_count = 0
    
    # Iterate through device directories
    for device_dir in sorted(raw_dir.iterdir()):
        if not device_dir.is_dir():
            continue
        
        device_name = device_dir.name
        
        # Parse each raw file
        for raw_file in sorted(device_dir.glob("*.txt")):
            try:
                # Determine command from filename
                # Example: "show-interfaces.txt" → "show interfaces"
                command_base = raw_file.stem  # Remove .txt
                command = command_base.replace("-", " ")  # "show-interfaces" → "show interfaces"
                
                # Read raw output
                raw_output = raw_file.read_text(encoding="utf-8", errors="ignore")
                
                # Detect platform (basic: assume Cisco IOS based on output patterns)
                # In production, use device inventory
                platform = _detect_platform_from_output(raw_output)
                
                # Try to parse with TextFSM
                parsed_data = registry.parse(platform, command, raw_output)
                
                # Check parsing success (both None and empty list are failures)
                if parsed_data and len(parsed_data) > 0:
                    # TextFSM parsing succeeded - insert to parsed_outputs
                    _insert_parsed_data(
                        conn, 
                        device_name, 
                        command, 
                        parsed_data, 
                        snapshot_date
                    )
                    parsed_count += 1
                    logger.debug(f"✓ Parsed {device_name}/{command} ({len(parsed_data)} records)")
                else:
                    # No template or parsing failed - skip (no raw_outputs table in v2.0)
                    logger.debug(f"⚠ No template for {device_name}/{command}, skipped")
                    
            except Exception as e:
                logger.warning(f"Failed to parse {device_name}/{raw_file.name}: {e}")
                continue
    
    logger.info(f"Imported {parsed_count} parsed commands for snapshot {snapshot_date}")
    return parsed_count


def _detect_platform_from_output(output: str) -> str:
    """Detect platform from CLI output (basic heuristics).
    
    In production, should query device inventory instead.
    """
    output_lower = output.lower()
    
    if "cisco" in output_lower:
        if "nxos" in output_lower or "nexus" in output_lower:
            return "cisco_nxos"
        else:
            return "cisco_ios"
    elif "arista" in output_lower:
        return "arista_eos"
    elif "juniper" in output_lower:
        return "juniper_junos"
    else:
        return "cisco_ios"  # Default


def _insert_parsed_data(
    conn: duckdb.DuckDBPyConnection,
    device_name: str,
    command: str,
    parsed_data: list[dict],
    snapshot_date: str,
) -> None:
    """Insert TextFSM-parsed data with simplified routing.
    
    Simplified Architecture (3 tables only):
    - devices table: From Nornir inventory (not from commands)
    - topology_links table: CDP/LLDP neighbor discovery
    - parsed_outputs table: Everything else (JSON)
    
    Design rationale:
    - Avoids LLM table selection confusion
    - Single source of truth for network data
    - Multi-vendor support without code changes
    - DuckDB JSON functions handle queries efficiently
    """
    print(f"[DEBUG] _insert_parsed_data called: {device_name}/{command}, {len(parsed_data)} records")
    
    if not parsed_data or len(parsed_data) == 0:
        print(f"[DEBUG] No data to insert")
        return
    
    command_lower = command.lower()
    
    # Simplified routing: Only topology gets special treatment
    if "cdp" in command_lower or "lldp" in command_lower:
        print(f"[DEBUG] Routing to topology_links: {device_name}/{command}")
        _insert_topology(conn, device_name, parsed_data, snapshot_date, command)
    else:
        # Everything else goes to parsed_outputs as JSON
        print(f"[DEBUG] Routing to parsed_outputs: {device_name}/{command}")
        _insert_parsed_output_json(conn, device_name, command, parsed_data, snapshot_date)


# Note: _insert_interfaces() removed - interface data stored in parsed_outputs as JSON
# Interface queries should use parsed_outputs table or live CLI execution

# Note: _insert_routes(), _insert_devices(), _insert_arp_table(), _insert_vlans() removed
# All structured data should go to parsed_outputs as JSON or specific tables like topology_links


def _insert_topology(
    conn: duckdb.DuckDBPyConnection,
    device_name: str,
    parsed_data: list[dict],
    snapshot_date: str,
    command: str,
) -> None:
    """Insert topology discovery data into topology_links table.
    
    Handles CDP and LLDP neighbor data.
    
    Expected TextFSM fields:
    - NEIGHBOR_NAME: Destination device name
    - LOCAL_INTERFACE: Source interface
    - NEIGHBOR_INTERFACE: Destination interface
    - PLATFORM: Device platform (optional)
    - CAPABILITIES: Device capabilities (optional)
    """
    from datetime import datetime
    import hashlib
    
    # Determine discovery protocol from command
    protocol = "CDP" if "cdp" in command.lower() else "LLDP" if "lldp" in command.lower() else "UNKNOWN"
    
    inserted_count = 0
    for record in parsed_data:
        try:
            # Extract neighbor information (case-insensitive)
            neighbor_name = None
            local_intf = None
            remote_intf = None
            platform = None
            
            for key, value in record.items():
                key_upper = key.upper()
                if key_upper in ("NEIGHBOR_NAME", "NEIGHBOR", "DEST_HOST", "DESTINATION_HOST"):
                    neighbor_name = value
                elif key_upper in ("LOCAL_INTERFACE", "LOCAL_PORT", "INTF", "INTERFACE"):
                    local_intf = value
                elif key_upper in ("NEIGHBOR_INTERFACE", "NEIGHBOR_PORT", "REMOTE_PORT", "PORT_ID"):
                    remote_intf = value
                elif key_upper == "PLATFORM":
                    platform = value
            
            # Validate required fields
            if not neighbor_name or not local_intf or not remote_intf:
                continue
            
            # Clean device names (remove domain suffixes)
            neighbor_clean = neighbor_name.split(".")[0] if "." in neighbor_name else neighbor_name
            
            # Normalize interface names (handle abbreviations)
            local_intf_clean = _normalize_interface_name(local_intf)
            remote_intf_clean = _normalize_interface_name(remote_intf)
            
            # Generate deterministic link_id
            link_data = f"{device_name}|{local_intf_clean}|{neighbor_clean}|{remote_intf_clean}|{snapshot_date}"
            link_id = hashlib.md5(link_data.encode()).hexdigest()[:16]
            
            # Get current timestamp
            now = datetime.now().isoformat()
            
            # Insert into topology_links
            conn.execute(
                """
                INSERT INTO topology_links (
                    link_id, source_device, source_interface,
                    destination_device, destination_interface,
                    discovery_protocol, link_status, platform,
                    first_seen, last_seen, last_verified,
                    sync_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_device, source_interface, destination_device, destination_interface, sync_date)
                DO UPDATE SET
                    last_seen = EXCLUDED.last_seen,
                    last_verified = EXCLUDED.last_verified
                """,
                [
                    link_id,
                    device_name,
                    local_intf_clean,
                    neighbor_clean,
                    remote_intf_clean,
                    protocol,
                    "up",  # Assume up if discovered
                    platform,
                    now,  # first_seen
                    now,  # last_seen
                    now,  # last_verified
                    snapshot_date,
                ],
            )
            inserted_count += 1
            print(f"  ✅ Inserted topology link: {device_name}.{local_intf_clean} <-> {neighbor_clean}.{remote_intf_clean}")
            
        except Exception as e:
            print(f"  ❌ Failed to insert topology link {device_name}/{neighbor_name}: {e}")
            continue
    
    if inserted_count > 0:
        print(f"✅ Inserted {inserted_count} topology links for {device_name}")


def _normalize_interface_name(intf: str) -> str:
    """Normalize interface name abbreviations to full names.
    
    Examples:
    - "Gig 2" → "GigabitEthernet2"
    - "Eth 0/0" → "Ethernet0/0"
    - "Uni Eth 0/1" → "Ethernet0/1"
    """
    if not intf:
        return intf
    
    # Skip if already in full form (avoid double-expansion)
    full_forms = ["GigabitEthernet", "FastEthernet", "TenGigabitEthernet", "Ethernet"]
    for full in full_forms:
        if intf.startswith(full):
            return intf  # Already normalized
    
    # Remove common prefixes
    intf = intf.replace("Uni ", "").replace("Unidirectional ", "")
    
    # Expand abbreviations (order matters - check longer patterns first)
    replacements = [
        ("Gig ", "GigabitEthernet"),
        ("Gi", "GigabitEthernet"),
        ("Eth ", "Ethernet"),
        ("Et", "Ethernet"),
        ("Fa ", "FastEthernet"),
        ("Fa", "FastEthernet"),
        ("Te ", "TenGigabitEthernet"),
        ("Te", "TenGigabitEthernet"),
    ]
    
    for abbr, full in replacements:
        if intf.startswith(abbr):
            return intf.replace(abbr, full, 1)
    
    return intf


def _insert_vlans(
    conn: duckdb.DuckDBPyConnection,
    device_name: str,
    parsed_data: list[dict],
    snapshot_date: str,
) -> None:
    """Insert VLAN data."""
    logger.debug(f"VLAN data stored as JSON for {device_name}")


def _insert_parsed_output_json(
    conn: duckdb.DuckDBPyConnection,
    device_name: str,
    command: str,
    parsed_data: list[dict],
    snapshot_date: str,
) -> None:
    """Store parsed data as JSON for commands without specific tables."""
    try:
        # Ensure parsed_outputs table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS parsed_outputs (
                device_name VARCHAR,
                command VARCHAR,
                parsed_data JSON,
                snapshot_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (device_name, command, snapshot_date)
            )
        """)
        
        conn.execute("""
            INSERT INTO parsed_outputs
            (device_name, command, parsed_data, snapshot_date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT DO NOTHING
        """, [
            device_name,
            command,
            json.dumps(parsed_data),
            snapshot_date,
        ])
    except Exception as e:
        logger.warning(f"Failed to insert JSON for {device_name}/{command}: {e}")


# Note: _insert_raw_output() removed in v2.0 - no raw_outputs table
# Commands without TextFSM templates are skipped


def _import_parsed_outputs(
    conn: duckdb.DuckDBPyConnection, sync_dir: Path, snapshot_date: str
) -> int:
    """Import parsed JSON files to parsed_outputs table (v0.13.0).
    
    Simple and clean: Just insert JSON results, no raw text storage.
    """
    parsed_dir = sync_dir / "parsed"
    if not parsed_dir.exists():
        logger.debug(f"No parsed directory at {parsed_dir}")
        return 0

    imported = 0
    for device_dir in parsed_dir.iterdir():
        if not device_dir.is_dir():
            continue

        device_name = device_dir.name

        for json_file in device_dir.glob("*.json"):
            try:
                # Read JSON file
                data = json.loads(json_file.read_text(encoding="utf-8"))
                command = data.get("command", json_file.stem)

                # Insert into parsed_outputs
                conn.execute(
                    """
                    INSERT INTO parsed_outputs
                    (device_name, command, parsed_data, snapshot_date)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        device_name,
                        command,
                        json.dumps(data),  # Store entire JSON
                        snapshot_date,
                    ],
                )
                imported += 1
                logger.debug(f"✓ Imported {device_name}/{command}")

            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {device_name}/{json_file.name}: {e}")
            except Exception as e:
                logger.debug(f"Failed to import {device_name}/{json_file.name}: {e}")

    logger.info(f"Imported {imported} parsed commands for snapshot {snapshot_date}")
    return imported
