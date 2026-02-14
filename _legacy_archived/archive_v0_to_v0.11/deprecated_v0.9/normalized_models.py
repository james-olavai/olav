"""Normalized data models for cross-vendor network data standardization.

This module defines Pydantic models for standardized network data structures.
These models enable consistent data representation across different network vendors
(Cisco, Juniper, Arista, etc.) by normalizing vendor-specific field names.

Architecture:
    Layer 1 (Raw): command_outputs table with vendor-specific JSON
    Layer 2 (Normalization): These Pydantic models + field_mappings
    Layer 3 (Views): DuckDB views for standardized queries

Usage:
    from olav.core.normalized_models import BGPNeighbor

    # Parse vendor-specific data into normalized model
    neighbor = BGPNeighbor(
        neighbor_ip="10.0.0.1",
        remote_as=65001,
        state="Established"
    )
"""

from datetime import datetime
from enum import Enum
from ipaddress import IPv4Address, IPv6Address
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# =============================================================================
# Enums for Standardized Values
# =============================================================================


class BGPState(str, Enum):
    """BGP neighbor states (RFC 4271)."""

    IDLE = "Idle"
    CONNECT = "Connect"
    ACTIVE = "Active"
    OPENSENT = "OpenSent"
    OPENCONFIRM = "OpenConfirm"
    ESTABLISHED = "Established"


class OSPFState(str, Enum):
    """OSPF neighbor states (RFC 2328)."""

    DOWN = "Down"
    ATTEMPT = "Attempt"
    INIT = "Init"
    TWOWAY = "2-Way"
    EXSTART = "ExStart"
    EXCHANGE = "Exchange"
    LOADING = "Loading"
    FULL = "Full"


class InterfaceStatus(str, Enum):
    """Interface status values."""

    UP = "up"
    DOWN = "down"
    ADMIN_DOWN = "admin-down"


class RouteProtocol(str, Enum):
    """Routing protocol types."""

    CONNECTED = "connected"
    STATIC = "static"
    BGP = "bgp"
    OSPF = "ospf"
    EIGRP = "eigrp"
    ISIS = "isis"
    RIP = "rip"
    OTHER = "other"


# =============================================================================
# Core Normalized Models
# =============================================================================


class BGPNeighbor(BaseModel):
    """Standardized BGP neighbor representation.

    Normalized fields across vendors:
        Cisco: BGP_NEIGHBOR, AS, STATE_PFXRCD
        Juniper: Peer, ASNum, State
        Arista: neighborAddress, asn, state
    """

    neighbor_ip: IPv4Address | IPv6Address = Field(..., description="BGP neighbor IP address")
    remote_as: int = Field(..., description="Remote autonomous system number", ge=1, le=4294967295)
    state: BGPState = Field(..., description="BGP session state")
    prefixes_received: int | None = Field(None, description="Number of prefixes received", ge=0)
    uptime: str | None = Field(None, description="Session uptime (e.g., '01:23:45')")
    local_ip: IPv4Address | IPv6Address | None = Field(
        None, description="Local IP address for BGP session"
    )

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, v: str) -> str:
        """Normalize BGP state strings to standard enum values."""
        # Handle common variations
        state_map = {
            "established": "Established",
            "idle": "Idle",
            "active": "Active",
            "connect": "Connect",
            "opensent": "OpenSent",
            "openconfirm": "OpenConfirm",
        }
        return state_map.get(v.lower(), v)

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "neighbor_ip": "10.0.0.1",
                "remote_as": 65001,
                "state": "Established",
                "prefixes_received": 150,
                "uptime": "3d4h",
                "local_ip": "10.0.0.2",
            }
        }


class OSPFNeighbor(BaseModel):
    """Standardized OSPF neighbor representation.

    Normalized fields across vendors:
        Cisco: NEIGHBOR_ID, ADDRESS, STATE, INTERFACE
        Juniper: NeighborID, NeighborAddress, State, Interface
        Arista: neighborRouterId, neighborIpAddress, adjacencyState, interface
    """

    neighbor_id: IPv4Address = Field(..., description="OSPF router ID")
    neighbor_address: IPv4Address | IPv6Address = Field(..., description="Neighbor IP address")
    state: OSPFState = Field(..., description="OSPF neighbor state")
    interface: str = Field(..., description="Local interface connecting to neighbor")
    priority: int | None = Field(None, description="OSPF priority", ge=0, le=255)
    dead_time: str | None = Field(None, description="Dead timer remaining (e.g., '00:00:35')")

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, v: str) -> str:
        """Normalize OSPF state strings to standard enum values."""
        state_map = {
            "full": "Full",
            "2way": "2-Way",
            "init": "Init",
            "down": "Down",
            "exstart": "ExStart",
            "exchange": "Exchange",
            "loading": "Loading",
        }
        # Handle "FULL/DR", "FULL/BDR" variations
        if "/" in v:
            v = v.split("/")[0]
        return state_map.get(v.lower(), v)

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "neighbor_id": "192.168.1.1",
                "neighbor_address": "10.0.0.1",
                "state": "Full",
                "interface": "GigabitEthernet0/1",
                "priority": 1,
                "dead_time": "00:00:35",
            }
        }


class RouteEntry(BaseModel):
    """Standardized routing table entry.

    Normalized fields across vendors:
        Cisco: PROTOCOL, NETWORK, MASK, NEXT_HOP, METRIC, DISTANCE
        Juniper: Protocol, Destination, NextHop, Metric, Preference
        Arista: routeType, routeLeaked, network, nexthopAddr, metric
    """

    network: str = Field(..., description="Destination network (CIDR format)")
    protocol: RouteProtocol = Field(..., description="Routing protocol source")
    next_hop: IPv4Address | IPv6Address | Literal["Null0"] | None = Field(
        None, description="Next hop IP address or null route"
    )
    metric: int | None = Field(None, description="Route metric", ge=0)
    admin_distance: int | None = Field(None, description="Administrative distance", ge=0, le=255)
    interface: str | None = Field(None, description="Outgoing interface")

    @field_validator("protocol", mode="before")
    @classmethod
    def normalize_protocol(cls, v: str) -> str:
        """Normalize protocol strings to standard enum values."""
        protocol_map = {
            "c": "connected",
            "l": "connected",  # Local (Cisco) treated as connected
            "s": "static",
            "b": "bgp",
            "o": "ospf",
            "d": "eigrp",
            "i": "isis",
            "r": "rip",
        }
        return protocol_map.get(
            v.lower(), v.lower() if v.lower() in RouteProtocol.__members__.values() else "other"
        )

    @field_validator("network", mode="before")
    @classmethod
    def normalize_network(cls, v: str) -> str:
        """Ensure network is in CIDR format."""
        # If no prefix length, assume /32 for IPv4 or /128 for IPv6
        if "/" not in v:
            if ":" in v:
                return f"{v}/128"
            return f"{v}/32"
        return v

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "network": "10.0.0.0/24",
                "protocol": "ospf",
                "next_hop": "192.168.1.1",
                "metric": 10,
                "admin_distance": 110,
                "interface": "GigabitEthernet0/1",
            }
        }


class CDPNeighbor(BaseModel):
    """Standardized CDP/LLDP neighbor representation.

    Normalized fields across vendors:
        Cisco CDP: NEIGHBOR, LOCAL_PORT, REMOTE_PORT, PLATFORM, CAPABILITIES
        Cisco LLDP: NEIGHBOR_NAME, LOCAL_INTERFACE, PORT_ID, SYSTEM_DESCRIPTION
        Juniper LLDP: SystemName, LocalInterface, PortID, SystemDescription
    """

    neighbor_name: str = Field(..., description="Neighbor device name/hostname")
    local_interface: str = Field(..., description="Local interface connecting to neighbor")
    remote_interface: str = Field(..., description="Neighbor's interface")
    platform: str | None = Field(None, description="Neighbor platform/model")
    capabilities: str | None = Field(
        None, description="Neighbor capabilities (Router, Switch, etc.)"
    )
    ip_address: IPv4Address | IPv6Address | None = Field(None, description="Neighbor management IP")

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "neighbor_name": "R2.example.com",
                "local_interface": "GigabitEthernet0/1",
                "remote_interface": "GigabitEthernet0/2",
                "platform": "Cisco ISR4321",
                "capabilities": "Router Switch",
                "ip_address": "10.0.0.2",
            }
        }


class InterfaceInfo(BaseModel):
    """Standardized interface information.

    Normalized fields across vendors:
        Cisco: INTERFACE, IP_ADDRESS, STATUS, PROTOCOL
        Juniper: Interface, Status, LinkStatus, Address
        Arista: interface, interfaceStatus, lineProtocolStatus, ipv4Address
    """

    interface: str = Field(..., description="Interface name")
    ip_address: IPv4Address | IPv6Address | None = Field(
        None, description="IP address assigned to interface"
    )
    status: InterfaceStatus = Field(..., description="Administrative status (up/down)")
    protocol: InterfaceStatus = Field(..., description="Protocol status (line protocol)")
    description: str | None = Field(None, description="Interface description")
    vlan: int | None = Field(None, description="VLAN ID (for L2 interfaces)", ge=1, le=4094)

    @field_validator("status", "protocol", mode="before")
    @classmethod
    def normalize_status(cls, v: str) -> str:
        """Normalize status strings to standard enum values."""
        status_map = {
            "up": "up",
            "down": "down",
            "administratively down": "admin-down",
            "admin down": "admin-down",
        }
        return status_map.get(v.lower(), v.lower())

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "interface": "GigabitEthernet0/1",
                "ip_address": "10.0.0.1",
                "status": "up",
                "protocol": "up",
                "description": "Link to R2",
                "vlan": 100,
            }
        }


class TopologyLink(BaseModel):
    """Standardized topology link representation.

    This model combines CDP/LLDP neighbor data with interface status
    to represent physical topology connections.
    """

    source_device: str = Field(..., description="Source device name")
    source_interface: str = Field(..., description="Source interface")
    destination_device: str = Field(..., description="Destination device name")
    destination_interface: str = Field(..., description="Destination interface")
    link_type: Literal["cdp", "lldp", "manual"] = Field(..., description="Discovery protocol used")
    link_status: Literal["up", "down", "unknown"] = Field(
        ..., description="Link operational status"
    )
    discovered_at: datetime = Field(
        default_factory=datetime.now, description="When the link was discovered"
    )

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "source_device": "R1",
                "source_interface": "GigabitEthernet0/1",
                "destination_device": "R2",
                "destination_interface": "GigabitEthernet0/2",
                "link_type": "cdp",
                "link_status": "up",
                "discovered_at": "2026-01-15T10:00:00",
            }
        }


# =============================================================================
# Model Registry for Dynamic Access
# =============================================================================

NORMALIZED_MODELS = {
    "bgp_neighbor": BGPNeighbor,
    "ospf_neighbor": OSPFNeighbor,
    "route_entry": RouteEntry,
    "cdp_neighbor": CDPNeighbor,
    "interface_info": InterfaceInfo,
    "topology_link": TopologyLink,
}


def get_model_by_name(name: str) -> type[BaseModel]:
    """Get normalized model class by name.

    Args:
        name: Model name (e.g., "bgp_neighbor")

    Returns:
        Pydantic model class

    Raises:
        KeyError: If model name is not found
    """
    return NORMALIZED_MODELS[name]
