"""Field mapping tables for cross-vendor data normalization.

This module provides mappings from vendor-specific field names to the normalized
Pydantic model fields defined in normalized_models.py.

Architecture:
    TextFSM Output (vendor-specific) → Field Mappings → Pydantic Models (normalized)

Usage:
    from olav.core.field_mappings import FIELD_MAPPINGS, get_mapping

    # Get mapping for a specific vendor/command
    mapping = get_mapping("cisco_ios", "show_ip_bgp_summary")

    # Apply mapping to raw data
    normalized_data = apply_mapping(raw_data, mapping)

Supported Vendors:
    - cisco_ios: Cisco IOS/IOS-XE
    - juniper_junos: Juniper Junos OS
    - arista_eos: Arista EOS

Command Categories:
    - bgp_neighbor: BGP summary/neighbor data
    - ospf_neighbor: OSPF neighbor data
    - route_entry: Routing table entries
    - cdp_neighbor: CDP/LLDP neighbor data
    - interface_info: Interface status data
"""

from typing import Any

# =============================================================================
# Field Mappings by Vendor and Command
# =============================================================================

FIELD_MAPPINGS = {
    # =========================================================================
    # Cisco IOS / IOS-XE
    # =========================================================================
    "cisco_ios": {
        # BGP Neighbors (show ip bgp summary)
        "show_ip_bgp_summary": {
            "model": "bgp_neighbor",
            "fields": {
                "neighbor_ip": "BGP_NEIGHBOR",  # or NEIGHBOR
                "remote_as": "AS",  # or REMOTE_AS
                "state": "STATE_PFXRCD",  # Contains both state and prefix count
                "prefixes_received": "STATE_PFXRCD",  # Same field, parsed differently
                "uptime": "UP_DOWN",  # or UPTIME
            },
            "transformers": {
                "state": lambda v: v if v.isalpha() else "Established",
                "prefixes_received": lambda v: int(v) if v.isdigit() else None,
            },
        },
        # OSPF Neighbors (show ip ospf neighbor)
        "show_ip_ospf_neighbor": {
            "model": "ospf_neighbor",
            "fields": {
                "neighbor_id": "NEIGHBOR_ID",  # or NEIGHBOR
                "neighbor_address": "ADDRESS",  # or IP_ADDRESS
                "state": "STATE",
                "interface": "INTERFACE",
                "priority": "PRIORITY",
                "dead_time": "DEAD_TIME",  # or DEAD
            },
            "transformers": {
                "state": lambda v: v.split("/")[0] if "/" in v else v,  # Handle "FULL/DR"
            },
        },
        # Routing Table (show ip route)
        "show_ip_route": {
            "model": "route_entry",
            "fields": {
                "network": "NETWORK",
                "protocol": "PROTOCOL",  # or TYPE
                "next_hop": "NEXT_HOP",  # or NEXTHOP_IP
                "metric": "METRIC",
                "admin_distance": "DISTANCE",  # or AD
                "interface": "NEXTHOP_IF",  # or INTERFACE
            },
            "transformers": {
                "network": lambda v, mask: f"{v}/{mask}"
                if "mask" in locals()
                else v,  # Combine NETWORK and MASK
            },
        },
        # CDP Neighbors (show cdp neighbors detail)
        "show_cdp_neighbors_detail": {
            "model": "cdp_neighbor",
            "fields": {
                "neighbor_name": "NEIGHBOR",  # or DEVICE_ID
                "local_interface": "LOCAL_PORT",  # or LOCAL_INTERFACE
                "remote_interface": "REMOTE_PORT",  # or PORT_ID
                "platform": "PLATFORM",
                "capabilities": "CAPABILITIES",
                "ip_address": "MANAGEMENT_IP",  # or IP_ADDRESS
            },
        },
        # Interface Status (show ip interface brief)
        "show_ip_interface_brief": {
            "model": "interface_info",
            "fields": {
                "interface": "INTERFACE",  # or INTF
                "ip_address": "IP_ADDRESS",  # or IPADDR
                "status": "STATUS",  # Admin status
                "protocol": "PROTOCOL",  # Line protocol
            },
        },
        # LLDP Neighbors (show lldp neighbors detail)
        "show_lldp_neighbors_detail": {
            "model": "cdp_neighbor",
            "fields": {
                "neighbor_name": "NEIGHBOR_NAME",  # or SYSTEM_NAME
                "local_interface": "LOCAL_INTERFACE",
                "remote_interface": "PORT_ID",  # or NEIGHBOR_PORT_ID
                "platform": "SYSTEM_DESCRIPTION",  # Approximate
                "capabilities": "CAPABILITIES",
                "ip_address": "MANAGEMENT_IP",
            },
        },
    },
    # =========================================================================
    # Juniper Junos OS
    # =========================================================================
    "juniper_junos": {
        # BGP Neighbors (show bgp summary)
        "show_bgp_summary": {
            "model": "bgp_neighbor",
            "fields": {
                "neighbor_ip": "Peer",  # or PeerAddress
                "remote_as": "ASNum",  # or AS
                "state": "State",
                "prefixes_received": "InPfx",  # or ReceivedPrefixes
                "uptime": "Up/Down",  # or StateTime
            },
        },
        # OSPF Neighbors (show ospf neighbor)
        "show_ospf_neighbor": {
            "model": "ospf_neighbor",
            "fields": {
                "neighbor_id": "NeighborID",  # or RouterID
                "neighbor_address": "NeighborAddress",  # or Address
                "state": "State",
                "interface": "Interface",
                "priority": "Priority",
                "dead_time": "DeadTimer",  # or Dead
            },
        },
        # Routing Table (show route)
        "show_route": {
            "model": "route_entry",
            "fields": {
                "network": "Destination",  # or Route
                "protocol": "Protocol",  # or Type
                "next_hop": "NextHop",  # or Via
                "metric": "Metric",
                "admin_distance": "Preference",  # Junos uses Preference, not AD
                "interface": "Interface",
            },
        },
        # LLDP Neighbors (show lldp neighbors)
        "show_lldp_neighbors": {
            "model": "cdp_neighbor",
            "fields": {
                "neighbor_name": "SystemName",
                "local_interface": "LocalInterface",  # or LocalPort
                "remote_interface": "PortID",  # or RemotePort
                "platform": "SystemDescription",
                "capabilities": "Capabilities",
                "ip_address": "ManagementAddress",
            },
        },
        # Interface Status (show interfaces terse)
        "show_interfaces_terse": {
            "model": "interface_info",
            "fields": {
                "interface": "Interface",
                "ip_address": "Address",  # May need separate query
                "status": "Status",  # Admin status
                "protocol": "LinkStatus",  # Link status
            },
        },
    },
    # =========================================================================
    # Arista EOS
    # =========================================================================
    "arista_eos": {
        # BGP Neighbors (show ip bgp summary)
        "show_ip_bgp_summary": {
            "model": "bgp_neighbor",
            "fields": {
                "neighbor_ip": "neighborAddress",  # or peerAddress
                "remote_as": "asn",  # or remoteAs
                "state": "state",
                "prefixes_received": "prefixReceived",
                "uptime": "upDownTime",  # or uptime
            },
        },
        # OSPF Neighbors (show ip ospf neighbor)
        "show_ip_ospf_neighbor": {
            "model": "ospf_neighbor",
            "fields": {
                "neighbor_id": "neighborRouterId",  # or routerId
                "neighbor_address": "neighborIpAddress",  # or address
                "state": "adjacencyState",  # or state
                "interface": "interface",
                "priority": "priority",
                "dead_time": "deadTime",
            },
        },
        # Routing Table (show ip route)
        "show_ip_route": {
            "model": "route_entry",
            "fields": {
                "network": "network",  # Usually already in CIDR
                "protocol": "routeType",  # or protocol
                "next_hop": "nexthopAddr",  # or nextHop
                "metric": "metric",
                "admin_distance": "preference",  # Arista uses preference
                "interface": "interface",
            },
        },
        # LLDP Neighbors (show lldp neighbors)
        "show_lldp_neighbors": {
            "model": "cdp_neighbor",
            "fields": {
                "neighbor_name": "neighborDevice",  # or systemName
                "local_interface": "port",  # or localPort
                "remote_interface": "neighborPort",  # or portId
                "platform": "systemDescription",
                "capabilities": "capabilities",
                "ip_address": "managementAddress",
            },
        },
        # Interface Status (show interfaces status)
        "show_interfaces_status": {
            "model": "interface_info",
            "fields": {
                "interface": "interface",
                "ip_address": "ipv4Address",  # May need separate query
                "status": "interfaceStatus",  # or linkStatus
                "protocol": "lineProtocolStatus",
                "description": "description",
                "vlan": "vlan",
            },
        },
    },
}


# =============================================================================
# Helper Functions
# =============================================================================


def get_mapping(platform: str, command: str) -> dict[str, Any] | None:
    """Get field mapping for a specific vendor/command combination.

    Args:
        platform: Vendor platform (e.g., "cisco_ios", "juniper_junos")
        command: Command name (e.g., "show_ip_bgp_summary")

    Returns:
        Mapping dictionary with 'model' and 'fields' keys, or None if not found

    Example:
        >>> mapping = get_mapping("cisco_ios", "show_ip_bgp_summary")
        >>> mapping["model"]
        'bgp_neighbor'
        >>> mapping["fields"]["neighbor_ip"]
        'BGP_NEIGHBOR'
    """
    return FIELD_MAPPINGS.get(platform, {}).get(command)


def apply_mapping(raw_data: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Apply field mapping to raw vendor data.

    Args:
        raw_data: Raw data dictionary from TextFSM parser
        mapping: Field mapping from get_mapping()

    Returns:
        Normalized data dictionary with standardized field names

    Example:
        >>> raw = {"BGP_NEIGHBOR": "10.0.0.1", "AS": "65001", "STATE_PFXRCD": "150"}
        >>> mapping = get_mapping("cisco_ios", "show_ip_bgp_summary")
        >>> normalized = apply_mapping(raw, mapping)
        >>> normalized
        {'neighbor_ip': '10.0.0.1', 'remote_as': '65001', 'prefixes_received': 150}
    """
    if not mapping:
        return raw_data

    fields = mapping.get("fields", {})
    transformers = mapping.get("transformers", {})
    normalized = {}

    for normalized_name, raw_name in fields.items():
        if raw_name in raw_data:
            value = raw_data[raw_name]

            # Apply transformer if exists
            if normalized_name in transformers:
                try:
                    value = transformers[normalized_name](value)
                except Exception:
                    pass  # Keep original value if transformation fails

            normalized[normalized_name] = value

    return normalized


def get_supported_platforms() -> list[str]:
    """Get list of supported platforms.

    Returns:
        List of platform identifiers

    Example:
        >>> get_supported_platforms()
        ['cisco_ios', 'juniper_junos', 'arista_eos']
    """
    return list(FIELD_MAPPINGS.keys())


def get_supported_commands(platform: str) -> list[str]:
    """Get list of supported commands for a platform.

    Args:
        platform: Platform identifier

    Returns:
        List of command names

    Example:
        >>> get_supported_commands("cisco_ios")
        ['show_ip_bgp_summary', 'show_ip_ospf_neighbor', ...]
    """
    return list(FIELD_MAPPINGS.get(platform, {}).keys())


def infer_command_from_raw_fields(platform: str, raw_fields: list[str]) -> str | None:
    """Infer command name by matching raw field names.

    This is useful when you have raw data but don't know which command it came from.

    Args:
        platform: Platform identifier
        raw_fields: List of field names in raw data

    Returns:
        Inferred command name, or None if no match found

    Example:
        >>> raw_fields = ["BGP_NEIGHBOR", "AS", "STATE_PFXRCD"]
        >>> infer_command_from_raw_fields("cisco_ios", raw_fields)
        'show_ip_bgp_summary'
    """
    platform_mappings = FIELD_MAPPINGS.get(platform, {})

    for command, mapping in platform_mappings.items():
        mapped_fields = set(mapping["fields"].values())
        # Check if at least 70% of mapped fields are present
        match_count = len(mapped_fields.intersection(raw_fields))
        if match_count >= len(mapped_fields) * 0.7:
            return command

    return None


# =============================================================================
# Field Name Variations (for fuzzy matching)
# =============================================================================

FIELD_ALIASES = {
    # BGP field variations
    "neighbor": ["BGP_NEIGHBOR", "NEIGHBOR", "Peer", "PeerAddress", "neighborAddress"],
    "remote_as": ["AS", "REMOTE_AS", "ASNum", "asn", "remoteAs"],
    "state": ["STATE", "STATE_PFXRCD", "State", "state", "adjacencyState"],
    # OSPF field variations
    "neighbor_id": ["NEIGHBOR_ID", "NEIGHBOR", "NeighborID", "RouterID", "neighborRouterId"],
    "neighbor_address": ["ADDRESS", "IP_ADDRESS", "NeighborAddress", "neighborIpAddress"],
    # Routing field variations
    "network": ["NETWORK", "Destination", "Route", "network"],
    "protocol": ["PROTOCOL", "TYPE", "Protocol", "Type", "routeType"],
    "next_hop": ["NEXT_HOP", "NEXTHOP_IP", "NextHop", "Via", "nexthopAddr"],
    # Interface field variations
    "interface": ["INTERFACE", "INTF", "Interface", "interface", "port"],
    "status": ["STATUS", "Status", "interfaceStatus", "linkStatus"],
}


def find_field_by_alias(raw_fields: list[str], target_field: str) -> str | None:
    """Find raw field name using alias matching.

    Args:
        raw_fields: List of available field names in raw data
        target_field: Target normalized field name (e.g., "neighbor_ip")

    Returns:
        Matching raw field name, or None if no match found

    Example:
        >>> raw_fields = ["Peer", "ASNum", "State"]
        >>> find_field_by_alias(raw_fields, "neighbor")
        'Peer'
    """
    aliases = FIELD_ALIASES.get(target_field, [])
    for field in raw_fields:
        if field in aliases:
            return field
    return None
