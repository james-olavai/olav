"""Phase 1.5: Devices Management API - Device discovery, querying, and management.

Provides:
- Device discovery and listing with filters
- Device detail retrieval
- Interface information
- Device capabilities
- Subnet-based queries
- Device status and health
"""

import logging
from typing import Any

from olav.core.unified_database import UnifiedDatabase

logger = logging.getLogger(__name__)


def list_devices(
    limit: int = 100,
    offset: int = 0,
    vendor: str | None = None,
    device_type: str | None = None,
    status: str | None = None,
    order_by: str = "hostname",
) -> list[dict[str, Any]]:
    """List devices with optional filtering.

    Args:
        limit: Max devices to return
        offset: Offset for pagination
        vendor: Filter by vendor (e.g., "cisco", "juniper")
        device_type: Filter by type (e.g., "router", "switch")
        status: Filter by status (e.g., "up", "down")
        order_by: Sort field

    Returns:
        List of device dicts with id, name, vendor, type, status, etc.

    Example:
        >>> devices = list_devices(vendor="cisco", limit=10)
        >>> for dev in devices:
        ...     print(dev["hostname"], dev["vendor"])
    """
    try:
        db = UnifiedDatabase()

        # Build SQL query with parameterized query to prevent SQL injection
        where_clauses = []
        params = []

        if vendor:
            where_clauses.append('vendor ILIKE ?')
            params.append(f'%{vendor}%')

        if device_type:
            where_clauses.append('device_type ILIKE ?')
            params.append(f'%{device_type}%')

        if status:
            where_clauses.append('is_active = ?')
            params.append(status.lower() == "up")

        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Query devices with parameterized query
        sql = f"""
            SELECT 
                device_id,
                hostname,
                vendor,
                device_type,
                is_active,
                created_at
            FROM devices
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT {limit} OFFSET {offset}
        """

        rows = db.query(sql, params if params else None)

        devices = []
        for row in rows:
            devices.append({
                "device_id": row[0],
                "hostname": row[1],
                "vendor": row[2],
                "device_type": row[3],
                "status": "up" if row[4] else "down",
                "created_at": row[5],
            })

        return devices

    except Exception as e:
        logger.error(f"Failed to list devices: {e}")
        raise  # Propagate error instead of returning empty list


def get_device(device_id: str) -> dict[str, Any] | None:
    """Get detailed information about a specific device.

    Args:
        device_id: Device ID or hostname

    Returns:
        Device dict with all information, or None if not found

    Example:
        >>> device = get_device("router-01")
        >>> print(device["vendor"], device["device_type"])
    """
    if not device_id:
        return None

    try:
        db = UnifiedDatabase()

        # Query device
        sql = f"""
            SELECT 
                device_id,
                hostname,
                vendor,
                device_type,
                is_active,
                created_at
            FROM devices
            WHERE device_id = '{device_id}' OR hostname = '{device_id}'
            LIMIT 1
        """

        rows = db.query(sql)

        if rows:
            row = rows[0]
            return {
                "device_id": row[0],
                "hostname": row[1],
                "vendor": row[2],
                "device_type": row[3],
                "status": "up" if row[4] else "down",
                "created_at": row[5],
            }

        return None

    except Exception as e:
        logger.error(f"Failed to get device {device_id}: {e}")
        raise  # Propagate error instead of returning None


def get_device_interfaces(
    device_id: str,
    limit: int = 100,
    order_by: str = "interface_name",
) -> list[dict[str, Any]]:
    """Get interfaces for a device.

    Args:
        device_id: Device ID
        limit: Max interfaces to return
        order_by: Sort field

    Returns:
        List of interface dicts

    Example:
        >>> interfaces = get_device_interfaces("router-01")
        >>> for iface in interfaces:
        ...     print(iface["interface_name"], iface.get("ip_address"))
    """
    if not device_id:
        return []

    try:
        db = UnifiedDatabase()

        # Query interfaces
        sql = f"""
            SELECT 
                interface_id,
                interface_name,
                ip_address,
                subnet_mask,
                status,
                mtu
            FROM topology_interfaces
            WHERE device_id = '{device_id}'
            ORDER BY {order_by}
            LIMIT {limit}
        """

        rows = db.query(sql)

        interfaces = []
        for row in rows:
            interfaces.append({
                "interface_id": row[0],
                "interface_name": row[1],
                "ip_address": row[2],
                "subnet_mask": row[3],
                "status": row[4],
                "mtu": row[5],
            })

        return interfaces

    except Exception as e:
        logger.error(f"Failed to get interfaces for {device_id}: {e}")
        raise  # Propagate error instead of returning empty list


def get_device_capabilities(device_id: str) -> dict[str, Any]:
    """Get capabilities of a device.

    Args:
        device_id: Device ID

    Returns:
        Dict with supported protocols and features

    Example:
        >>> caps = get_device_capabilities("router-01")
        >>> print("BGP" if caps["bgp"] else "No BGP")
    """
    if not device_id:
        return {}

    try:
        db = UnifiedDatabase()

        # Query capabilities
        sql = f"""
            SELECT 
                capability_id,
                capability_name,
                is_supported
            FROM device_capabilities
            WHERE device_id = '{device_id}'
            LIMIT 50
        """

        rows = db.query(sql)

        capabilities = {}
        for row in rows:
            cap_name = row[1].lower() if row[1] else ""
            capabilities[cap_name] = row[2]

        return capabilities

    except Exception as e:
        logger.error(f"Failed to get capabilities for {device_id}: {e}")
        raise  # Propagate error instead of returning empty dict


def query_subnet_devices(
    subnet: str,
    limit: int = 100,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Query devices in a subnet.

    Args:
        subnet: CIDR subnet (e.g., "192.168.1.0/24")
        limit: Max devices to return
        status: Filter by status ("up" or "down")

    Returns:
        List of devices in the subnet

    Example:
        >>> devices = query_subnet_devices("10.0.0.0/8")
        >>> print(f"Found {len(devices)} devices")
    """
    try:
        db = UnifiedDatabase()

        # Parse subnet
        subnet_parts = subnet.split("/")
        if len(subnet_parts) != 2:
            logger.warning(f"Invalid subnet format: {subnet}")
            return []

        network = subnet_parts[0]

        # Query devices with IP in subnet
        sql = f"""
            SELECT DISTINCT
                d.device_id,
                d.hostname,
                d.vendor,
                d.device_type,
                d.is_active,
                ti.ip_address
            FROM devices d
            LEFT JOIN topology_interfaces ti ON d.device_id = ti.device_id
            WHERE ti.ip_address LIKE '{network.rsplit(".", 1)[0]}%'
            LIMIT {limit}
        """

        rows = db.query(sql)

        devices = []
        for row in rows:
            devices.append({
                "device_id": row[0],
                "hostname": row[1],
                "vendor": row[2],
                "device_type": row[3],
                "status": "up" if row[4] else "down",
                "ip_address": row[5],
            })

        return devices

    except Exception as e:
        logger.error(f"Failed to query subnet {subnet}: {e}")
        raise  # Propagate error instead of returning empty list


def filter_devices(
    criteria: dict[str, Any],
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Filter devices by multiple criteria.

    Args:
        criteria: Filter dict (vendor, device_type, status, etc.)
        limit: Max devices to return
        offset: Offset for pagination

    Returns:
        List of matching devices

    Example:
        >>> devices = filter_devices({
        ...     "vendor": "cisco",
        ...     "device_type": "router",
        ...     "status": "up"
        ... })
    """
    # Use list_devices with unpacked criteria
    vendor = criteria.get("vendor")
    device_type = criteria.get("device_type")
    status = criteria.get("status")

    return list_devices(
        limit=limit,
        offset=offset,
        vendor=vendor,
        device_type=device_type,
        status=status,
    )


def get_device_status(device_id: str) -> dict[str, Any] | None:
    """Get current status and health of a device.

    Args:
        device_id: Device ID

    Returns:
        Dict with status, uptime, last_check, health metrics

    Example:
        >>> status = get_device_status("router-01")
        >>> print(f"CPU: {status.get('cpu_percent')}%")
    """
    if not device_id:
        return None

    try:
        db = UnifiedDatabase()

        # Get device status
        sql = f"""
            SELECT 
                device_id,
                is_active,
                created_at
            FROM devices
            WHERE device_id = '{device_id}'
            LIMIT 1
        """

        rows = db.query(sql)

        if rows:
            row = rows[0]
            return {
                "device_id": row[0],
                "status": "up" if row[1] else "down",
                "created_at": row[2],
                "last_check": None,  # Would need timestamp tracking
                "uptime_seconds": 0,  # Would need to calculate
                "health": "ok" if row[1] else "critical",
            }

        return None

    except Exception as e:
        logger.error(f"Failed to get status for {device_id}: {e}")
        raise  # Propagate error instead of returning None
