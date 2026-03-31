"""Tests for OpenConfig Pydantic v2 models (OC-1).

TDD RED phase: these tests define the contract for all 5 OpenConfig domains.
"""

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestImports:
    """All model classes must be importable from olav.core.models."""

    def test_import_interface_models(self):
        from olav.core.models.openconfig import (
            Interface,
            InterfaceCounters,
            InterfaceState,
            SubinterfaceState,
        )

        assert Interface is not None
        assert InterfaceCounters is not None
        assert InterfaceState is not None
        assert SubinterfaceState is not None

    def test_import_bgp_models(self):
        from olav.core.models.openconfig import (
            BgpNeighbor,
            BgpNeighborState,
            BgpPrefixes,
        )

        assert BgpNeighbor is not None
        assert BgpNeighborState is not None
        assert BgpPrefixes is not None

    def test_import_lldp_models(self):
        from olav.core.models.openconfig import (
            LldpInterface,
            LldpNeighbor,
            LldpNeighborState,
        )

        assert LldpInterface is not None
        assert LldpNeighbor is not None
        assert LldpNeighborState is not None

    def test_import_ospf_models(self):
        from olav.core.models.openconfig import (
            OspfAreaState,
            OspfInterfaceState,
            OspfNeighborState,
        )

        assert OspfAreaState is not None
        assert OspfInterfaceState is not None
        assert OspfNeighborState is not None

    def test_import_platform_models(self):
        from olav.core.models.openconfig import Component, ComponentState

        assert Component is not None
        assert ComponentState is not None

    def test_import_container_model(self):
        from olav.core.models.openconfig import OpenConfigData

        assert OpenConfigData is not None

    def test_import_from_init(self):
        """All models must be re-exported from olav.core.models.__init__."""
        from olav.core.models import (
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

        assert all(
            [
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
            ]
        )


# ---------------------------------------------------------------------------
# Interfaces domain
# ---------------------------------------------------------------------------


class TestInterfaceModels:
    def test_interface_state_minimal(self):
        from olav.core.models.openconfig import InterfaceState

        state = InterfaceState(name="eth0")
        assert state.name == "eth0"
        assert state.mtu is None
        assert state.admin_status is None

    def test_interface_state_full(self):
        from olav.core.models.openconfig import InterfaceCounters, InterfaceState

        counters = InterfaceCounters(
            **{
                "in-octets": 1000,
                "out-octets": 2000,
                "in-errors": 0,
                "out-errors": 0,
                "in-discards": 0,
                "out-discards": 0,
            }
        )
        state = InterfaceState(
            name="GigabitEthernet0/0",
            type="ethernetCsmacd",
            mtu=1500,
            **{"admin-status": "UP", "oper-status": "UP"},
            description="Uplink",
            counters=counters,
        )
        assert state.name == "GigabitEthernet0/0"
        assert state.admin_status == "UP"
        assert state.oper_status == "UP"
        assert state.counters.in_octets == 1000

    def test_interface_state_python_field_names(self):
        """populate_by_name=True allows using Python names too."""
        from olav.core.models.openconfig import InterfaceState

        state = InterfaceState(
            name="eth0",
            admin_status="DOWN",
            oper_status="UP",
        )
        assert state.admin_status == "DOWN"

    def test_interface_state_invalid_mtu_type(self):
        from olav.core.models.openconfig import InterfaceState

        with pytest.raises(ValidationError):
            InterfaceState(name="eth0", mtu="not_a_number")

    def test_interface_full_model(self):
        from olav.core.models.openconfig import Interface, InterfaceState

        iface = Interface(
            name="eth0",
            state=InterfaceState(name="eth0", mtu=9000),
        )
        assert iface.state.mtu == 9000

    def test_interface_counters_serialization(self):
        from olav.core.models.openconfig import InterfaceCounters

        counters = InterfaceCounters(**{"in-octets": 100, "out-octets": 200})
        d = counters.model_dump(by_alias=True)
        assert d["in-octets"] == 100
        assert d["out-octets"] == 200

    def test_subinterface_state(self):
        from olav.core.models.openconfig import SubinterfaceState

        sub = SubinterfaceState(
            index=0,
            **{"ip-address": "10.0.0.1", "prefix-length": 24},
        )
        assert sub.ip_address == "10.0.0.1"
        assert sub.prefix_length == 24

    def test_interface_with_subinterfaces(self):
        from olav.core.models.openconfig import (
            Interface,
            InterfaceState,
            SubinterfaceState,
        )

        iface = Interface(
            name="eth0",
            state=InterfaceState(
                name="eth0",
                subinterfaces=[
                    SubinterfaceState(index=0, **{"ip-address": "10.0.0.1", "prefix-length": 24}),
                    SubinterfaceState(index=1, **{"ip-address": "10.0.1.1", "prefix-length": 30}),
                ],
            ),
        )
        assert len(iface.state.subinterfaces) == 2


# ---------------------------------------------------------------------------
# BGP domain
# ---------------------------------------------------------------------------


class TestBgpModels:
    def test_bgp_neighbor_state_minimal(self):
        from olav.core.models.openconfig import BgpNeighborState

        state = BgpNeighborState(**{"neighbor-address": "10.0.0.1"})
        assert state.neighbor_address == "10.0.0.1"

    def test_bgp_neighbor_state_full(self):
        from olav.core.models.openconfig import BgpNeighborState, BgpPrefixes

        state = BgpNeighborState(
            **{
                "neighbor-address": "10.0.0.1",
                "peer-as": 65001,
                "local-as": 65000,
                "peer-type": "EXTERNAL",
                "session-state": "ESTABLISHED",
            },
            prefixes=BgpPrefixes(received=100, sent=50, installed=90),
        )
        assert state.peer_as == 65001
        assert state.session_state == "ESTABLISHED"
        assert state.prefixes.received == 100

    def test_bgp_neighbor_address_required(self):
        from olav.core.models.openconfig import BgpNeighborState

        with pytest.raises(ValidationError):
            BgpNeighborState()  # neighbor-address is required

    def test_bgp_neighbor_full(self):
        from olav.core.models.openconfig import BgpNeighbor, BgpNeighborState

        nbr = BgpNeighbor(
            **{"neighbor-address": "10.0.0.1"},
            state=BgpNeighborState(**{"neighbor-address": "10.0.0.1", "session-state": "ACTIVE"}),
        )
        assert nbr.state.session_state == "ACTIVE"

    def test_bgp_prefixes_all_optional(self):
        from olav.core.models.openconfig import BgpPrefixes

        p = BgpPrefixes()
        assert p.received is None
        assert p.sent is None


# ---------------------------------------------------------------------------
# LLDP domain
# ---------------------------------------------------------------------------


class TestLldpModels:
    def test_lldp_neighbor_state(self):
        from olav.core.models.openconfig import LldpNeighborState

        state = LldpNeighborState(
            **{
                "system-name": "switch1.lab",
                "chassis-id": "aa:bb:cc:dd:ee:ff",
                "port-id": "Ethernet1",
                "management-address": "10.0.0.1",
            },
        )
        assert state.system_name == "switch1.lab"
        assert state.chassis_id == "aa:bb:cc:dd:ee:ff"

    def test_lldp_neighbor_all_optional(self):
        from olav.core.models.openconfig import LldpNeighborState

        state = LldpNeighborState()
        assert state.system_name is None
        assert state.chassis_id is None

    def test_lldp_interface(self):
        from olav.core.models.openconfig import (
            LldpInterface,
            LldpNeighbor,
            LldpNeighborState,
        )

        iface = LldpInterface(
            name="eth0",
            neighbors=[
                LldpNeighbor(
                    state=LldpNeighborState(**{"system-name": "peer1", "port-id": "eth1"})
                ),
            ],
        )
        assert len(iface.neighbors) == 1
        assert iface.neighbors[0].state.system_name == "peer1"


# ---------------------------------------------------------------------------
# OSPF domain
# ---------------------------------------------------------------------------


class TestOspfModels:
    def test_ospf_neighbor_state(self):
        from olav.core.models.openconfig import OspfNeighborState

        state = OspfNeighborState(
            **{
                "neighbor-id": "1.1.1.1",
                "neighbor-address": "10.0.0.2",
            },
            state="FULL",
            priority=1,
            **{"dead-time": 40},
        )
        assert state.neighbor_id == "1.1.1.1"
        assert state.state == "FULL"

    def test_ospf_neighbor_id_required(self):
        from olav.core.models.openconfig import OspfNeighborState

        with pytest.raises(ValidationError):
            OspfNeighborState()  # neighbor-id is required

    def test_ospf_interface_state(self):
        from olav.core.models.openconfig import OspfInterfaceState, OspfNeighborState

        iface = OspfInterfaceState(
            id="0.0.0.0",
            **{"network-type": "BROADCAST"},
            cost=10,
            passive=False,
            neighbors=[
                OspfNeighborState(**{"neighbor-id": "2.2.2.2"}),
            ],
        )
        assert iface.cost == 10
        assert len(iface.neighbors) == 1

    def test_ospf_area_state(self):
        from olav.core.models.openconfig import OspfAreaState, OspfInterfaceState

        area = OspfAreaState(
            identifier="0.0.0.0",
            interfaces=[
                OspfInterfaceState(id="eth0", cost=1),
            ],
        )
        assert area.identifier == "0.0.0.0"
        assert len(area.interfaces) == 1


# ---------------------------------------------------------------------------
# Platform domain
# ---------------------------------------------------------------------------


class TestPlatformModels:
    def test_component_state_minimal(self):
        from olav.core.models.openconfig import ComponentState

        state = ComponentState(name="chassis")
        assert state.name == "chassis"
        assert state.serial_no is None

    def test_component_state_full(self):
        from olav.core.models.openconfig import ComponentState

        state = ComponentState(
            name="Chassis",
            type="CHASSIS",
            description="Main chassis",
            **{
                "mfg-name": "Cisco",
                "hardware-version": "1.0",
                "firmware-version": "16.9.4",
                "software-version": "IOS-XE 16.9.4",
                "serial-no": "ABC12345",
                "part-no": "C9300-48P",
            },
            temperature=42.5,
        )
        assert state.mfg_name == "Cisco"
        assert state.serial_no == "ABC12345"
        assert state.temperature == 42.5

    def test_component_full(self):
        from olav.core.models.openconfig import Component, ComponentState

        comp = Component(
            name="FAN-1",
            state=ComponentState(name="FAN-1", type="FAN"),
        )
        assert comp.state.type == "FAN"


# ---------------------------------------------------------------------------
# Container model (OpenConfigData)
# ---------------------------------------------------------------------------


class TestOpenConfigData:
    def test_empty_container(self):
        from olav.core.models.openconfig import OpenConfigData

        data = OpenConfigData()
        assert data.interfaces is None
        assert data.bgp_neighbors is None

    def test_container_with_interfaces(self):
        from olav.core.models.openconfig import (
            Interface,
            InterfaceState,
            OpenConfigData,
        )

        data = OpenConfigData(
            interfaces=[
                Interface(name="eth0", state=InterfaceState(name="eth0", mtu=1500)),
            ],
        )
        assert len(data.interfaces) == 1

    def test_container_with_all_domains(self):
        from olav.core.models.openconfig import (
            BgpNeighbor,
            BgpNeighborState,
            Component,
            ComponentState,
            Interface,
            InterfaceState,
            LldpInterface,
            OpenConfigData,
            OspfAreaState,
        )

        data = OpenConfigData(
            interfaces=[Interface(name="eth0", state=InterfaceState(name="eth0"))],
            bgp_neighbors=[
                BgpNeighbor(
                    **{"neighbor-address": "10.0.0.1"},
                    state=BgpNeighborState(**{"neighbor-address": "10.0.0.1"}),
                ),
            ],
            lldp_interfaces=[LldpInterface(name="eth0")],
            ospf_areas=[OspfAreaState(identifier="0.0.0.0")],
            components=[
                Component(name="chassis", state=ComponentState(name="chassis")),
            ],
        )
        assert len(data.interfaces) == 1
        assert len(data.bgp_neighbors) == 1
        assert len(data.lldp_interfaces) == 1
        assert len(data.ospf_areas) == 1
        assert len(data.components) == 1

    def test_container_alias_serialization(self):
        """Container uses aliases for OpenConfig-style output."""
        from olav.core.models.openconfig import (
            BgpNeighbor,
            BgpNeighborState,
            OpenConfigData,
        )

        data = OpenConfigData(
            bgp_neighbors=[
                BgpNeighbor(
                    **{"neighbor-address": "10.0.0.1"},
                    state=BgpNeighborState(**{"neighbor-address": "10.0.0.1"}),
                ),
            ],
        )
        d = data.model_dump(by_alias=True, exclude_none=True)
        assert "bgp-neighbors" in d
        assert "neighbor-address" in d["bgp-neighbors"][0]


# ---------------------------------------------------------------------------
# Serialization / round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_model_dump_by_alias(self):
        from olav.core.models.openconfig import InterfaceState

        state = InterfaceState(name="eth0", admin_status="UP", oper_status="DOWN")
        d = state.model_dump(by_alias=True)
        assert "admin-status" in d
        assert "oper-status" in d
        assert d["admin-status"] == "UP"

    def test_model_dump_by_python_name(self):
        from olav.core.models.openconfig import InterfaceState

        state = InterfaceState(name="eth0", admin_status="UP")
        d = state.model_dump()
        assert "admin_status" in d

    def test_json_round_trip(self):
        from olav.core.models.openconfig import (
            BgpNeighbor,
            BgpNeighborState,
            BgpPrefixes,
        )

        original = BgpNeighbor(
            **{"neighbor-address": "10.0.0.1"},
            state=BgpNeighborState(
                **{
                    "neighbor-address": "10.0.0.1",
                    "peer-as": 65001,
                    "session-state": "ESTABLISHED",
                },
                prefixes=BgpPrefixes(received=100, sent=50),
            ),
        )
        json_str = original.model_dump_json(by_alias=True)
        restored = BgpNeighbor.model_validate_json(json_str)
        assert restored.neighbor_address == "10.0.0.1"
        assert restored.state.peer_as == 65001
        assert restored.state.prefixes.received == 100

    def test_json_round_trip_container(self):
        from olav.core.models.openconfig import (
            Component,
            ComponentState,
            OpenConfigData,
        )

        original = OpenConfigData(
            components=[
                Component(
                    name="chassis",
                    state=ComponentState(
                        name="chassis",
                        type="CHASSIS",
                        **{"serial-no": "SN123"},
                    ),
                ),
            ],
        )
        json_str = original.model_dump_json(by_alias=True)
        restored = OpenConfigData.model_validate_json(json_str)
        assert restored.components[0].state.serial_no == "SN123"
