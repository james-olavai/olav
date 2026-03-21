"""OpenConfig Pydantic v2 models for OLAV network data normalization.

These models represent the operational state of network devices following
OpenConfig YANG model structure. They cover five core domains:

- **Interfaces**: openconfig-interfaces
- **BGP**: openconfig-bgp (neighbors)
- **LLDP**: openconfig-lldp
- **OSPF**: openconfig-ospfv2
- **Platform**: openconfig-platform (components)

All models use hyphenated aliases matching OpenConfig naming conventions.
Use ``model_dump(by_alias=True)`` for OpenConfig-compatible JSON output.
"""

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Interfaces  (openconfig-interfaces)
# ---------------------------------------------------------------------------


class InterfaceCounters(BaseModel):
    """Per-interface traffic counters (state only)."""

    model_config = ConfigDict(populate_by_name=True)

    in_octets: int | None = Field(None, alias="in-octets")
    out_octets: int | None = Field(None, alias="out-octets")
    in_errors: int | None = Field(None, alias="in-errors")
    out_errors: int | None = Field(None, alias="out-errors")
    in_discards: int | None = Field(None, alias="in-discards")
    out_discards: int | None = Field(None, alias="out-discards")


class SubinterfaceState(BaseModel):
    """State of an interface sub-unit (e.g. VLAN, IP sub-interface)."""

    model_config = ConfigDict(populate_by_name=True)

    index: int
    ip_address: str | None = Field(None, alias="ip-address")
    prefix_length: int | None = Field(None, alias="prefix-length")


class InterfaceState(BaseModel):
    """Operational state of a single network interface."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    type: str | None = None
    mtu: int | None = None
    admin_status: str | None = Field(None, alias="admin-status")
    oper_status: str | None = Field(None, alias="oper-status")
    description: str | None = None
    counters: InterfaceCounters | None = None
    subinterfaces: list[SubinterfaceState] | None = None


class Interface(BaseModel):
    """Top-level interface entry (name + state container)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    state: InterfaceState


# ---------------------------------------------------------------------------
# BGP  (openconfig-bgp — neighbor focus)
# ---------------------------------------------------------------------------


class BgpPrefixes(BaseModel):
    """Prefix counters for a BGP neighbor session."""

    model_config = ConfigDict(populate_by_name=True)

    received: int | None = None
    sent: int | None = None
    installed: int | None = None


class BgpNeighborState(BaseModel):
    """Operational state of a single BGP neighbor."""

    model_config = ConfigDict(populate_by_name=True)

    neighbor_address: str = Field(..., alias="neighbor-address")
    peer_as: int | None = Field(None, alias="peer-as")
    local_as: int | None = Field(None, alias="local-as")
    peer_type: str | None = Field(None, alias="peer-type")
    session_state: str | None = Field(None, alias="session-state")
    prefixes: BgpPrefixes | None = None


class BgpNeighbor(BaseModel):
    """Top-level BGP neighbor entry."""

    model_config = ConfigDict(populate_by_name=True)

    neighbor_address: str = Field(..., alias="neighbor-address")
    state: BgpNeighborState


# ---------------------------------------------------------------------------
# LLDP  (openconfig-lldp)
# ---------------------------------------------------------------------------


class LldpNeighborState(BaseModel):
    """Operational state of a discovered LLDP neighbor."""

    model_config = ConfigDict(populate_by_name=True)

    system_name: str | None = Field(None, alias="system-name")
    system_description: str | None = Field(None, alias="system-description")
    chassis_id: str | None = Field(None, alias="chassis-id")
    chassis_id_type: str | None = Field(None, alias="chassis-id-type")
    port_id: str | None = Field(None, alias="port-id")
    port_id_type: str | None = Field(None, alias="port-id-type")
    management_address: str | None = Field(None, alias="management-address")


class LldpNeighbor(BaseModel):
    """Single LLDP neighbor entry."""

    model_config = ConfigDict(populate_by_name=True)

    state: LldpNeighborState


class LldpInterface(BaseModel):
    """LLDP state per interface."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    neighbors: list[LldpNeighbor] | None = None


# ---------------------------------------------------------------------------
# OSPF  (openconfig-ospfv2)
# ---------------------------------------------------------------------------


class OspfNeighborState(BaseModel):
    """Operational state of a single OSPF neighbor."""

    model_config = ConfigDict(populate_by_name=True)

    neighbor_id: str = Field(..., alias="neighbor-id")
    neighbor_address: str | None = Field(None, alias="neighbor-address")
    state: str | None = None
    priority: int | None = None
    dead_time: int | None = Field(None, alias="dead-time")


class OspfInterfaceState(BaseModel):
    """OSPF interface operational state within an area."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    network_type: str | None = Field(None, alias="network-type")
    cost: int | None = None
    passive: bool | None = None
    neighbors: list[OspfNeighborState] | None = None


class OspfAreaState(BaseModel):
    """OSPF area containing interfaces and their neighbors."""

    model_config = ConfigDict(populate_by_name=True)

    identifier: str
    interfaces: list[OspfInterfaceState] | None = None


# ---------------------------------------------------------------------------
# Platform  (openconfig-platform — components)
# ---------------------------------------------------------------------------


class ComponentState(BaseModel):
    """Operational state of a platform component (chassis, linecard, etc.)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    type: str | None = None
    id: str | None = None
    description: str | None = None
    mfg_name: str | None = Field(None, alias="mfg-name")
    hardware_version: str | None = Field(None, alias="hardware-version")
    firmware_version: str | None = Field(None, alias="firmware-version")
    software_version: str | None = Field(None, alias="software-version")
    serial_no: str | None = Field(None, alias="serial-no")
    part_no: str | None = Field(None, alias="part-no")
    temperature: float | None = None


class Component(BaseModel):
    """Top-level platform component entry."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    state: ComponentState


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------


class OpenConfigData(BaseModel):
    """Top-level container for all OpenConfig domains.

    This model aggregates data from all five supported domains into a
    single serialisable structure suitable for DuckDB storage or gNMI export.
    """

    model_config = ConfigDict(populate_by_name=True)

    interfaces: list[Interface] | None = None
    bgp_neighbors: list[BgpNeighbor] | None = Field(None, alias="bgp-neighbors")
    lldp_interfaces: list[LldpInterface] | None = Field(None, alias="lldp-interfaces")
    ospf_areas: list[OspfAreaState] | None = Field(None, alias="ospf-areas")
    components: list[Component] | None = None
