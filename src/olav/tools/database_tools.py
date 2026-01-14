"""Database query tools for Agent integration.

This module provides tool wrappers for querying the unified database,
enabling natural language access to network data.
"""

from typing import Any

from olav.analysis.macro_analyzer import MacroAnalyzer
from olav.core.unified_database import UnifiedDatabase


def find_ip_location_tool(ip_address: str) -> dict[str, Any]:
    """Find the location of an IP address in the network.

    Args:
        ip_address: IP address to locate (e.g., "10.1.12.1")

    Returns:
        Dictionary with location information:
        - device_name: Device where IP was found
        - interface: Interface name
        - mac_address: Associated MAC address
        - vlan: VLAN ID if available
    """
    with UnifiedDatabase() as udb:
        result = udb.find_ip_location(ip_address)

    if not result:
        return {
            "found": False,
            "message": f"IP {ip_address} not found in network",
        }

    return {
        "found": True,
        "ip": ip_address,
        "device_name": result.get("device_name"),
        "interface": result.get("interface"),
        "mac_address": result.get("mac_address"),
        "vlan": result.get("vlan"),
    }


def get_device_health_tool(device_name: str) -> dict[str, Any]:
    """Get comprehensive health information for a device.

    Args:
        device_name: Name of the device (e.g., "R1", "SW1")

    Returns:
        Dictionary with device health data:
        - device_name: Device name
        - platform: Platform type
        - role: Device role
        - arp_count: Number of ARP entries
        - route_count: Number of routes
        - neighbor_count: Number of topology neighbors
        - command_count: Number of available commands
    """
    with UnifiedDatabase() as udb:
        result = udb.get_device_health(device_name)

    if not result or "error" in result:
        return {
            "found": False,
            "message": f"Device {device_name} not found",
        }

    return {
        "found": True,
        "device_name": result.get("device_name"),
        "platform": result.get("platform"),
        "role": result.get("role"),
        "arp_count": result.get("arp_entries", 0),
        "route_count": result.get("routes", 0),
        "neighbor_count": result.get("neighbors", 0),
        "command_count": result.get("available_commands", 0),
    }


def get_network_summary_tool() -> dict[str, Any]:
    """Get a summary of the entire network.

    Returns:
        Dictionary with network-wide statistics:
        - total_devices: Number of devices
        - total_links: Number of topology links
        - total_arp_entries: Total ARP entries
        - total_routes: Total routes
        - platforms: List of unique platforms
    """
    with UnifiedDatabase() as udb:
        result = udb.get_network_summary()
        
        # Get platforms list
        platforms_result = udb.query(
            "SELECT DISTINCT platform FROM snapshot.topology_devices"
        )
        platforms = [row[0] for row in platforms_result]

    return {
        "total_devices": result.get("devices", 0),
        "total_links": result.get("links", 0),
        "total_arp_entries": result.get("arp_entries", 0),
        "total_routes": result.get("routes", 0),
        "platforms": platforms,
    }


def search_ip_across_network_tool(ip_pattern: str) -> list[dict[str, Any]]:
    """Search for IPs matching a pattern across the network.

    Args:
        ip_pattern: SQL LIKE pattern (e.g., "10.1.%", "192.168.1._")

    Returns:
        List of dictionaries with IP information:
        - ip: IP address
        - device_name: Device where found
        - interface: Interface name
        - mac_address: Associated MAC
        - source: Data source (arp_table, routes, etc.)
    """
    with UnifiedDatabase() as udb:
        results = udb.search_ip_across_network(ip_pattern)

    return [
        {
            "ip": row.get("ip"),
            "device_name": row.get("device_name"),
            "interface": row.get("interface"),
            "mac_address": row.get("mac_address"),
            "source": row.get("source"),
        }
        for row in results
    ]


def analyze_network_health_tool(snapshot_date: str | None = None) -> dict[str, Any]:
    """Generate comprehensive network health analysis.

    Args:
        snapshot_date: Date of snapshot to analyze (YYYY-MM-DD).
                      If None, uses latest snapshot.

    Returns:
        Dictionary with analysis report:
        - overall_score: Overall health score (0-100)
        - overall_status: HEALTHY/WARNING/CRITICAL
        - layer_scores: Scores for each OSI layer
        - device_health: Per-device health information
        - anomalies: List of detected anomalies
        - markdown_report: Formatted markdown report
    """
    with MacroAnalyzer() as analyzer:
        report = analyzer.generate_full_analysis(snapshot_date)
        markdown = analyzer.format_report_as_markdown(report)

    return {
        "overall_score": report.get("overall_score", 0),
        "overall_status": report.get("overall_status", "UNKNOWN"),
        "layer_scores": report.get("layer_scores", {}),
        "device_health": report.get("device_health", []),
        "anomalies": report.get("anomalies", []),
        "markdown_report": markdown,
    }


def query_database_tool(sql_query: str) -> list[dict[str, Any]]:
    """Execute a SQL query across the unified database.

    WARNING: Use with caution. Only SELECT queries are allowed.

    Args:
        sql_query: SQL SELECT query to execute

    Returns:
        List of dictionaries with query results
    """
    # Security check: only allow SELECT
    if not sql_query.strip().upper().startswith("SELECT"):
        return [{"error": "Only SELECT queries are allowed"}]

    try:
        with UnifiedDatabase() as udb:
            results = udb.query(sql_query)
        return [dict(row) for row in results]
    except Exception as e:
        return [{"error": f"Query failed: {e!s}"}]
