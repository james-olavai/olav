"""Tests for CDP → LLDP bridge (OC-7).

TDD cycle: maps CDP TextFSM output to openconfig-lldp structure
with source: "cdp" meta-tag.
"""

import pytest


class TestCdpBridgeImport:
    def test_import(self):
        from olav.core.bridges.cdp_lldp import cdp_to_lldp

        assert callable(cdp_to_lldp)


class TestCdpToLldp:
    def test_basic_mapping(self):
        from olav.core.bridges.cdp_lldp import cdp_to_lldp

        cdp_record = {
            "device_id": "switch1.example.com",
            "local_interface": "GigabitEthernet0/1",
            "port_id": "GigabitEthernet0/2",
            "platform": "cisco WS-C3750",
            "ip_address": "10.0.0.1",
        }
        result = cdp_to_lldp(cdp_record)

        assert result["name"] == "GigabitEthernet0/1"
        assert len(result["neighbors"]) == 1
        neighbor = result["neighbors"][0]
        assert neighbor["state"]["system-name"] == "switch1.example.com"
        assert neighbor["state"]["port-id"] == "GigabitEthernet0/2"
        assert neighbor["state"]["management-address"] == "10.0.0.1"

    def test_source_meta_tag(self):
        from olav.core.bridges.cdp_lldp import cdp_to_lldp

        cdp_record = {
            "device_id": "router1",
            "local_interface": "Fa0/0",
            "port_id": "Fa0/1",
        }
        result = cdp_to_lldp(cdp_record)
        assert result.get("_source") == "cdp"

    def test_missing_optional_fields(self):
        from olav.core.bridges.cdp_lldp import cdp_to_lldp

        cdp_record = {
            "device_id": "switch2",
            "local_interface": "eth0",
        }
        result = cdp_to_lldp(cdp_record)
        neighbor = result["neighbors"][0]
        assert neighbor["state"]["system-name"] == "switch2"
        assert neighbor["state"].get("port-id") is None

    def test_validates_against_pydantic(self):
        from olav.core.bridges.cdp_lldp import cdp_to_lldp
        from olav.core.models.openconfig import LldpInterface

        cdp_record = {
            "device_id": "sw1",
            "local_interface": "Gi0/1",
            "port_id": "Gi0/2",
            "ip_address": "10.1.1.1",
        }
        result = cdp_to_lldp(cdp_record)
        filtered = {k: v for k, v in result.items() if not k.startswith("_")}
        model = LldpInterface.model_validate(filtered)
        assert model.name == "Gi0/1"

    def test_system_description_from_platform(self):
        from olav.core.bridges.cdp_lldp import cdp_to_lldp

        cdp_record = {
            "device_id": "sw1",
            "local_interface": "eth0",
            "platform": "Cisco Nexus 9000",
        }
        result = cdp_to_lldp(cdp_record)
        neighbor = result["neighbors"][0]
        assert neighbor["state"]["system-description"] == "Cisco Nexus 9000"


class TestCdpBatchConvert:
    def test_batch_convert(self):
        from olav.core.bridges.cdp_lldp import cdp_batch_to_lldp

        records = [
            {"device_id": "sw1", "local_interface": "Gi0/1", "port_id": "Gi0/2"},
            {"device_id": "sw2", "local_interface": "Gi0/3", "port_id": "Gi0/4"},
        ]
        results = cdp_batch_to_lldp(records)
        assert len(results) == 2
        assert results[0]["name"] == "Gi0/1"
        assert results[1]["name"] == "Gi0/3"

    def test_batch_empty(self):
        from olav.core.bridges.cdp_lldp import cdp_batch_to_lldp

        assert cdp_batch_to_lldp([]) == []
