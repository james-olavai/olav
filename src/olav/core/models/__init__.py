"""OpenConfig Pydantic v2 models — public API.

All model classes are re-exported here for convenient imports::

    from olav.core.models import Interface, BgpNeighbor, OpenConfigData
"""

from olav.core.models.openconfig import (
    BgpNeighbor,
    BgpNeighborState,
    BgpPrefixes,
    Component,
    ComponentState,
    Interface,
    InterfaceCounters,
    InterfaceState,
    LldpInterface,
    LldpNeighbor,
    LldpNeighborState,
    OpenConfigData,
    OspfAreaState,
    OspfInterfaceState,
    OspfNeighborState,
    SubinterfaceState,
)

__all__ = [
    "BgpNeighbor",
    "BgpNeighborState",
    "BgpPrefixes",
    "Component",
    "ComponentState",
    "Interface",
    "InterfaceCounters",
    "InterfaceState",
    "LldpInterface",
    "LldpNeighbor",
    "LldpNeighborState",
    "OpenConfigData",
    "OspfAreaState",
    "OspfInterfaceState",
    "OspfNeighborState",
    "SubinterfaceState",
]
