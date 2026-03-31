"""Tests for netutils normalization layer (OC-4).

TDD cycle: netutils-based cleaning of TextFSM output before LLM mapping.
Covers interface name canonicalization, MAC normalization, IP/CIDR handling.
"""

import pytest


class TestNormalizeInterfaceName:
    def test_import(self):
        from olav.core.normalization import normalize_interface_name

        assert callable(normalize_interface_name)

    def test_short_to_canonical(self):
        from olav.core.normalization import normalize_interface_name

        assert normalize_interface_name("Gi0/0") == "GigabitEthernet0/0"

    def test_already_canonical(self):
        from olav.core.normalization import normalize_interface_name

        assert normalize_interface_name("GigabitEthernet0/0") == "GigabitEthernet0/0"

    def test_ten_gig(self):
        from olav.core.normalization import normalize_interface_name

        result = normalize_interface_name("Te1/0/1")
        assert "TenGigabitEthernet" in result or "Te" in result

    def test_empty_passthrough(self):
        from olav.core.normalization import normalize_interface_name

        assert normalize_interface_name("") == ""

    def test_unknown_passthrough(self):
        from olav.core.normalization import normalize_interface_name

        result = normalize_interface_name("mgmt0")
        assert result == "Management0"


class TestNormalizeMac:
    def test_import(self):
        from olav.core.normalization import normalize_mac

        assert callable(normalize_mac)

    def test_colon_format(self):
        from olav.core.normalization import normalize_mac

        result = normalize_mac("AA:BB:CC:DD:EE:FF")
        assert result == "aa:bb:cc:dd:ee:ff"

    def test_cisco_format(self):
        from olav.core.normalization import normalize_mac

        result = normalize_mac("aabb.ccdd.eeff")
        assert result == "aa:bb:cc:dd:ee:ff"

    def test_dash_format(self):
        from olav.core.normalization import normalize_mac

        result = normalize_mac("AA-BB-CC-DD-EE-FF")
        assert result == "aa:bb:cc:dd:ee:ff"

    def test_empty_passthrough(self):
        from olav.core.normalization import normalize_mac

        assert normalize_mac("") == ""

    def test_invalid_passthrough(self):
        from olav.core.normalization import normalize_mac

        assert normalize_mac("not-a-mac") == "not-a-mac"


class TestNormalizeIpPrefix:
    def test_import(self):
        from olav.core.normalization import normalize_ip_prefix

        assert callable(normalize_ip_prefix)

    def test_netmask_to_cidr(self):
        from olav.core.normalization import normalize_ip_prefix

        result = normalize_ip_prefix("192.168.1.0", "255.255.255.0")
        assert result == "192.168.1.0/24"

    def test_already_cidr(self):
        from olav.core.normalization import normalize_ip_prefix

        result = normalize_ip_prefix("10.0.0.0/8")
        assert result == "10.0.0.0/8"

    def test_no_mask_returns_host(self):
        from olav.core.normalization import normalize_ip_prefix

        result = normalize_ip_prefix("192.168.1.1")
        assert result == "192.168.1.1"

    def test_empty(self):
        from olav.core.normalization import normalize_ip_prefix

        assert normalize_ip_prefix("") == ""


class TestNormalizeRecord:
    """normalize_record applies all normalizations to a parsed TextFSM dict."""

    def test_import(self):
        from olav.core.normalization import normalize_record

        assert callable(normalize_record)

    def test_interface_field_normalized(self):
        from olav.core.normalization import normalize_record

        record = {"interface": "Gi0/0", "status": "up"}
        result = normalize_record(record)
        assert result["interface"] == "GigabitEthernet0/0"
        assert result["status"] == "up"

    def test_mac_field_normalized(self):
        from olav.core.normalization import normalize_record

        record = {"mac_address": "aabb.ccdd.eeff", "vlan": "10"}
        result = normalize_record(record)
        assert result["mac_address"] == "aa:bb:cc:dd:ee:ff"

    def test_multiple_fields(self):
        from olav.core.normalization import normalize_record

        record = {
            "interface": "Fa0/1",
            "mac_address": "AA-BB-CC-DD-EE-FF",
            "status": "up",
        }
        result = normalize_record(record)
        assert "FastEthernet" in result["interface"]
        assert result["mac_address"] == "aa:bb:cc:dd:ee:ff"

    def test_empty_record(self):
        from olav.core.normalization import normalize_record

        assert normalize_record({}) == {}

    def test_original_not_mutated(self):
        from olav.core.normalization import normalize_record

        record = {"interface": "Gi0/0"}
        normalize_record(record)
        assert record["interface"] == "Gi0/0"


class TestApplyOcMapping:
    """apply_oc_mapping builds nested OpenConfig dicts from TextFSM records (P2-4).

    After P0-FIX-1, the function no longer does flat field renaming. It builds
    nested dicts with ``openconfig-*`` top-level keys, grouping mapped fields
    by OC module prefix.  Unmapped fields are preserved under ``_unmapped``.
    """

    def _make_con(self):
        import duckdb

        con = duckdb.connect(":memory:")
        con.execute(
            """
            CREATE TABLE mapping_rules (
                vendor      TEXT NOT NULL,
                command     TEXT NOT NULL,
                src_field   TEXT NOT NULL,
                oc_path     TEXT NOT NULL,
                confidence  TEXT NOT NULL,
                PRIMARY KEY (vendor, command, src_field)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE schema_catalog (
                source_type TEXT,
                source_name TEXT,
                platform    TEXT,
                fields      TEXT,
                description TEXT,
                updated_at  TEXT
            )
            """
        )
        return con

    @staticmethod
    def _insert_mapping(con, vendor, command, src_field, oc_path, confidence="HIGH"):
        """Insert into both mapping_rules and schema_catalog for test compatibility."""
        import json

        con.execute(
            "INSERT INTO mapping_rules VALUES (?, ?, ?, ?, ?)",
            [vendor, command, src_field, oc_path, confidence],
        )
        # Upsert into schema_catalog: merge fields into existing row or create new
        existing = con.execute(
            "SELECT fields FROM schema_catalog WHERE platform = ? AND source_name = ?",
            [vendor, command],
        ).fetchone()
        if existing:
            fields = json.loads(existing[0])
            fields.append({"name": src_field, "openconfig_path": oc_path})
            con.execute(
                "UPDATE schema_catalog SET fields = ? WHERE platform = ? AND source_name = ?",
                [json.dumps(fields), vendor, command],
            )
        else:
            fields = [{"name": src_field, "openconfig_path": oc_path}]
            con.execute(
                "INSERT INTO schema_catalog VALUES (?, ?, ?, ?, ?, ?)",
                ["textfsm", command, vendor, json.dumps(fields), "", None],
            )

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _deep_get(d: dict, path: list[str]):
        """Walk *d* along *path*, unwrapping single-element lists."""
        cur = d
        for seg in path:
            if isinstance(cur, list):
                assert len(cur) == 1, f"expected single-element list at {seg}, got {cur}"
                cur = cur[0]
            cur = cur[seg]
        return cur

    # -- tests -----------------------------------------------------------------

    def test_import(self):
        from olav.core.normalization import apply_oc_mapping

        assert callable(apply_oc_mapping)

    def test_builds_nested_oc_structure(self):
        """Mapped field must appear inside a nested openconfig-* dict."""
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show lldp neighbors",
            "neighbor_name",
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        )
        records = [{"neighbor_name": "R2", "local_intf": "Gi0/0"}]
        result = apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

        assert len(result) == 1
        d = result[0]
        # Top-level key must start with openconfig-
        assert "openconfig-lldp" in d
        # Value at the leaf of the nested path must be "R2"
        val = self._deep_get(
            d,
            [
                "openconfig-lldp",
                "lldp",
                "interfaces",
                "interface",
                "neighbors",
                "neighbor",
                "state",
                "system-name",
            ],
        )
        assert val == "R2"

    def test_unmapped_fields_in_unmapped_key(self):
        """Fields without a mapping rule are preserved under ``_unmapped``."""
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show lldp neighbors",
            "neighbor_name",
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        )
        records = [{"neighbor_name": "R2", "extra_field": "some_value"}]
        result = apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

        assert "_unmapped" in result[0]
        assert result[0]["_unmapped"]["extra_field"] == "some_value"

    def test_empty_records_returns_empty(self):
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        result = apply_oc_mapping([], "cisco_ios", "show lldp neighbors", con)
        assert result == []

    def test_no_matching_rules_raises(self):
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        records = [{"neighbor_name": "R2", "port": "Gi0/0"}]
        with pytest.raises(ValueError, match="No schema_catalog entry found"):
            apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

    def test_scoped_to_platform_and_command(self):
        """Rules for a different vendor/command must NOT pollute this result."""
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "juniper",
            "show lldp neighbors",
            "neighbor_name",
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        )
        records = [{"neighbor_name": "R2"}]
        with pytest.raises(ValueError, match="No schema_catalog entry found"):
            apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

    def test_multiple_records_all_get_oc_structure(self):
        """Every input record produces its own OC-structured output dict."""
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show lldp neighbors",
            "neighbor_name",
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        )
        records = [{"neighbor_name": "R1"}, {"neighbor_name": "R2"}]
        result = apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

        assert len(result) == 2
        for i, expected in enumerate(["R1", "R2"]):
            val = self._deep_get(
                result[i],
                [
                    "openconfig-lldp",
                    "lldp",
                    "interfaces",
                    "interface",
                    "neighbors",
                    "neighbor",
                    "state",
                    "system-name",
                ],
            )
            assert val == expected

    def test_original_records_not_mutated(self):
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show lldp neighbors",
            "neighbor_name",
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        )
        original = [{"neighbor_name": "R1"}]
        apply_oc_mapping(original, "cisco_ios", "show lldp neighbors", con)
        assert "neighbor_name" in original[0]
        assert "openconfig-lldp" not in original[0]

    def test_apply_oc_mapping_cached_does_not_exist(self):
        """apply_oc_mapping_cached must be removed — importing it raises ImportError."""
        with pytest.raises(ImportError):
            from olav.core.normalization import apply_oc_mapping_cached  # noqa: F401

    def test_apply_oc_mapping_no_mapping_rules_fallback(self):
        """apply_oc_mapping raises ValueError immediately when schema_catalog has no entry.

        The mapping_rules fallback must be removed. No schema_catalog entry → ValueError,
        even when mapping_rules table exists.
        """
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        # mapping_rules has an entry, but schema_catalog does NOT
        con.execute(
            "INSERT INTO mapping_rules VALUES (?, ?, ?, ?, ?)",
            ["cisco_ios", "show lldp neighbors", "neighbor_name",
             "lldp/interfaces/interface/neighbors/neighbor/state/system-name", "HIGH"],
        )
        # schema_catalog is empty — must raise immediately, not fall back
        records = [{"neighbor_name": "R2"}]
        with pytest.raises(ValueError, match="No schema_catalog entry found"):
            apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

    def test_multiple_fields_merge_into_same_oc_subtree(self):
        """Two fields mapping to the same OC subtree share the nested dict."""
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show lldp neighbors",
            "neighbor_name",
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        )
        self._insert_mapping(
            con,
            "cisco_ios",
            "show lldp neighbors",
            "neighbor_interface",
            "lldp/interfaces/interface/neighbors/neighbor/state/port-id",
        )
        records = [{"neighbor_name": "R2", "neighbor_interface": "Gi0/1"}]
        result = apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

        d = result[0]
        assert "openconfig-lldp" in d
        state = self._deep_get(
            d,
            [
                "openconfig-lldp",
                "lldp",
                "interfaces",
                "interface",
                "neighbors",
                "neighbor",
                "state",
            ],
        )
        assert state["system-name"] == "R2"
        assert state["port-id"] == "Gi0/1"

    def test_different_modules_produce_separate_top_keys(self):
        """Fields from different OC modules get different openconfig-* keys."""
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show interfaces",
            "intf_name",
            "interfaces/interface/state/name",
        )
        self._insert_mapping(
            con,
            "cisco_ios",
            "show interfaces",
            "serial",
            "components/component/state/serial-no",
        )
        records = [{"intf_name": "Gi0/0", "serial": "SN123"}]
        result = apply_oc_mapping(records, "cisco_ios", "show interfaces", con)

        d = result[0]
        assert "openconfig-interfaces" in d
        assert "openconfig-platform" in d

    def test_yang_list_nodes_wrapped_in_arrays(self):
        """YANG list nodes (interface, neighbor, etc.) must be JSON arrays."""
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show lldp neighbors",
            "neighbor_name",
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        )
        records = [{"neighbor_name": "R2"}]
        result = apply_oc_mapping(records, "cisco_ios", "show lldp neighbors", con)

        oc = result[0]["openconfig-lldp"]
        # interface and neighbor are YANG list nodes — must be lists
        assert isinstance(oc["lldp"]["interfaces"]["interface"], list)
        iface = oc["lldp"]["interfaces"]["interface"][0]
        assert isinstance(iface["neighbors"]["neighbor"], list)
