"""Unified Device Import Tool - Nornir YAML to DuckDB Migration.

Architecture:
- Single source of truth: Nornir hosts.yaml (human-editable YAML)
- Auto-convert: YAML → Python dict → DuckDB table
- No external JSON files or manual conversion
- Supports both direct YAML and device metadata enrichment

Usage:
    from olav.lib.devices_import import import_devices_from_nornir
    
    import_devices_from_nornir(
        hosts_yaml_path='.olav/config/nornir/hosts.yaml',
        db_path='.olav/db/main.duckdb',
    )
"""

import logging
from pathlib import Path
from typing import Any

import duckdb
import yaml

logger = logging.getLogger(__name__)


def import_devices_from_nornir(
    hosts_yaml_path: str | Path,
    db_path: str | Path,
    table_name: str = "devices",
) -> dict[str, int]:
    """Import devices from Nornir hosts.yaml to DuckDB.
    
    This replaces the ad-hoc device population in sync_tools.py with a
    centralized, testable import mechanism.
    
    Args:
        hosts_yaml_path: Path to .olav/config/nornir/hosts.yaml
        db_path: Path to DuckDB database file
        table_name: Target table name (default: 'devices')
    
    Returns:
        Dictionary with import statistics:
            {
                'imported': int,      # Successfully imported
                'failed': int,        # Failed imports
                'duplicates': int,    # Items already in DB (using INSERT OR REPLACE)
                'roles_found': set,   # Unique roles found
                'sites_found': set,   # Unique sites found
            }
    
    Raises:
        FileNotFoundError: If hosts.yaml not found
        ValueError: If YAML is malformed
        duckdb.CatalogException: If database table doesn't exist
    
    Example:
        >>> stats = import_devices_from_nornir(
        ...     '.olav/config/nornir/hosts.yaml',
        ...     '.olav/db/main.duckdb'
        ... )
        >>> print(f"Imported {stats['imported']} devices")
        >>> print(f"Found roles: {stats['roles_found']}")
    """
    hosts_yaml_path = Path(hosts_yaml_path)
    db_path = Path(db_path)

    # Validate input file
    if not hosts_yaml_path.exists():
        raise FileNotFoundError(f"hosts.yaml not found: {hosts_yaml_path}")

    # Load YAML
    logger.info(f"Loading Nornir hosts from {hosts_yaml_path}")
    try:
        with open(hosts_yaml_path, encoding='utf-8') as f:
            hosts_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse hosts.yaml: {e}") from e

    if not isinstance(hosts_data, dict):
        raise ValueError(f"hosts.yaml must be a YAML dictionary, got {type(hosts_data)}")

    # Extract device records
    devices = _extract_devices_from_nornir(hosts_data)
    logger.info(f"Extracted {len(devices)} device(s) from hosts.yaml")

    # Connect to database (create if doesn't exist)
    # Note: DuckDB will create the file if it doesn't exist
    conn = duckdb.connect(str(db_path))

    try:
        # Ensure table exists with proper schema
        _ensure_devices_table_schema(conn, table_name)

        # Import devices
        stats = _insert_devices_to_duckdb(
            conn=conn,
            devices=devices,
            table_name=table_name,
        )

        logger.info(
            f"✅ Import complete: {stats['imported']} imported, "
            f"{stats['failed']} failed, roles={stats['roles_found']}"
        )

        return stats

    finally:
        conn.close()


def _extract_devices_from_nornir(hosts_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract device records from Nornir hosts.yaml structure.
    
    Nornir hosts.yaml format:
    ```yaml
    R1:
      hostname: 192.168.100.101
      platform: cisco_ios
      groups: [test]
      data:
        role: border
        site: lab
        aliases: [R1路由器]
    ```
    
    Args:
        hosts_data: Parsed YAML dictionary from hosts.yaml
    
    Returns:
        List of device dictionaries with normalized fields
    """
    devices = []

    for device_name, host_config in hosts_data.items():
        if not isinstance(host_config, dict):
            logger.warning(f"Skipping {device_name}: not a dictionary")
            continue

        try:
            # Extract core fields
            device = {
                'device_id': device_name,
                'name': device_name,
                'hostname': host_config.get('hostname', ''),
                'platform': host_config.get('platform', ''),
                'mgmt_ip': host_config.get('hostname', ''),  # IP from hostname

                # Extract from data section (Nornir standard)
                'device_type': host_config.get('data', {}).get('device_type', 'Unknown'),
                'device_role': host_config.get('data', {}).get('role', ''),
                'site': host_config.get('data', {}).get('site', ''),
                'location': host_config.get('data', {}).get('location', ''),

                # Optional vendor/model (may be auto-discovered later)
                'vendor': host_config.get('data', {}).get('vendor', ''),
                'model': host_config.get('data', {}).get('model', ''),
                'site_id': host_config.get('data', {}).get('site_id', ''),
            }

            # Clean up empty strings
            device = {k: (v if v else None) for k, v in device.items()}

            devices.append(device)
            logger.debug(f"Extracted device: {device_name} (role={device.get('device_role')})")

        except Exception as e:
            logger.error(f"Failed to extract device {device_name}: {e}")
            continue

    return devices


def _ensure_devices_table_schema(conn: duckdb.DuckDBPyConnection, table_name: str) -> None:
    """Ensure devices table exists with correct schema.
    
    Creates or validates the table structure. Uses IF NOT EXISTS to avoid
    errors on subsequent calls.
    
    Args:
        conn: DuckDB connection
        table_name: Name of the devices table
    
    Schema created:
        - device_id: Primary identifier (unique)
        - name: Human-readable device name
        - hostname: IP address or FQDN
        - platform: OS type (cisco_ios, huawei_vrp, etc.)
        - mgmt_ip: Management IP (same as hostname for most cases)
        - device_type: Router, Switch, Firewall (from Nornir role or discovery)
        - device_role: Border, core, access (from Nornir data.role)
        - site: Physical site name (lab, dc1, dc2, etc.)
        - location: Detailed location (rack, building, etc.)
        - vendor: Device vendor (Cisco, Huawei, etc.)
        - model: Device model number
        - site_id: Numeric site identifier (if applicable)
        - created_at: Record creation timestamp
        - updated_at: Last update timestamp
        - is_active: Active status flag
    """
    logger.debug(f"Ensuring {table_name} table schema exists")

    # Check if table exists
    existing_tables = conn.execute(
        f"SELECT table_name FROM duckdb_tables() WHERE table_name = '{table_name}'"
    ).fetchall()

    if existing_tables:
        logger.debug(f"Table {table_name} already exists, validating schema")
        # Validate schema has required columns
        required_columns = {
            'device_id', 'name', 'hostname', 'platform', 'mgmt_ip',
            'device_type', 'device_role', 'site', 'vendor', 'model'
        }

        existing_columns = {
            row[0] for row in conn.execute(f"DESCRIBE {table_name}").fetchall()
        }

        missing_columns = required_columns - existing_columns
        if missing_columns:
            logger.warning(f"Table {table_name} missing columns: {missing_columns}")
            # Add missing columns
            for col in missing_columns:
                try:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} VARCHAR")
                    logger.info(f"Added missing column: {col}")
                except Exception as e:
                    logger.error(f"Failed to add column {col}: {e}")
    else:
        # Create table
        logger.info(f"Creating {table_name} table")
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                device_id VARCHAR PRIMARY KEY,
                name VARCHAR,
                hostname VARCHAR,
                platform VARCHAR,
                mgmt_ip VARCHAR,
                device_type VARCHAR,
                device_role VARCHAR,
                site VARCHAR,
                location VARCHAR,
                vendor VARCHAR,
                model VARCHAR,
                site_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        logger.info(f"Created {table_name} table with full schema")


def _insert_devices_to_duckdb(
    conn: duckdb.DuckDBPyConnection,
    devices: list[dict[str, Any]],
    table_name: str,
) -> dict[str, Any]:
    """Insert devices into DuckDB table.
    
    Simple direct INSERT strategy with replace-on-conflict.
    
    Args:
        conn: DuckDB connection
        devices: List of device dictionaries from _extract_devices_from_nornir()
        table_name: Target table
    
    Returns:
        Statistics dictionary
    """
    stats = {
        'imported': 0,
        'failed': 0,
        'duplicates': 0,
        'roles_found': set(),
        'sites_found': set(),
    }

    # Get table columns
    table_columns = {
        row[0] for row in conn.execute(f"DESCRIBE {table_name}").fetchall()
    }
    logger.debug(f"Target table columns: {table_columns}")

    for device in devices:
        try:
            # Track metadata
            if device.get('device_role'):
                stats['roles_found'].add(device['device_role'])
            if device.get('site'):
                stats['sites_found'].add(device['site'])

            # Only include columns that exist in the table and have non-None values
            device_id = device.get('device_id')
            if not device_id:
                logger.warning("Skipping device without device_id")
                stats['failed'] += 1
                continue

            # Filter columns: only include those that exist in table and have values
            insert_columns = []
            insert_values = []
            for col, val in device.items():
                if col in table_columns and val is not None:
                    insert_columns.append(col)
                    insert_values.append(val)

            if not insert_columns:
                logger.warning(f"No columns to insert for device {device_id}")
                stats['failed'] += 1
                continue

            # Use INSERT OR REPLACE for simplicity
            placeholders = ', '.join(['?' for _ in insert_columns])
            column_list = ', '.join(insert_columns)
            sql = f"INSERT OR REPLACE INTO {table_name} ({column_list}) VALUES ({placeholders})"

            logger.debug(f"Executing INSERT for {device_id}: {sql[:80]}...")
            logger.debug(f"Values: {insert_values}")

            conn.execute(sql, insert_values)
            stats['imported'] += 1
            logger.debug(f"✅ Inserted device {device_id}")

        except Exception as e:
            logger.error(f"❌ Failed to insert device {device.get('device_id')}: {e}")
            stats['failed'] += 1

    logger.info(f"Committing {stats['imported']} device insertions...")
    conn.commit()
    logger.info("✅ Commit complete")

    return stats


def validate_devices_import(db_path: str | Path, table_name: str = "devices") -> dict[str, Any]:
    """Validate that devices were correctly imported.
    
    Args:
        db_path: Path to DuckDB database
        table_name: Devices table name
    
    Returns:
        Validation report with statistics
    """
    db_path = Path(db_path)
    conn = duckdb.connect(str(db_path), read_only=True)

    try:
        # Get basic stats
        total = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

        # Get role distribution
        roles = conn.execute(
            f"SELECT device_role, COUNT(*) FROM {table_name} "
            f"WHERE device_role IS NOT NULL GROUP BY device_role ORDER BY device_role"
        ).fetchall()

        # Get site distribution
        sites = conn.execute(
            f"SELECT site, COUNT(*) FROM {table_name} "
            f"WHERE site IS NOT NULL GROUP BY site ORDER BY site"
        ).fetchall()

        # Get sample records
        samples = conn.execute(
            f"SELECT device_id, name, device_role, site FROM {table_name} LIMIT 5"
        ).fetchall()

        return {
            'total_devices': total,
            'roles': {role: count for role, count in roles},
            'sites': {site: count for site, count in sites},
            'sample_records': [
                {
                    'device_id': s[0],
                    'name': s[1],
                    'device_role': s[2],
                    'site': s[3],
                }
                for s in samples
            ],
        }

    finally:
        conn.close()
