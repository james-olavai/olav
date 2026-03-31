"""TDD tests for OC-EXTEND-1: _olav: private namespace for non-OC operational data.

Tests cover:
  1. schema_engine._COMMAND_MODULE_HINTS includes _olav: module hints
  2. schema_engine.build_mapping_rules() generates _olav: paths
  3. normalization._oc_module_for_path() handles _olav: paths
  4. normalization.apply_oc_mapping() produces _olav:-keyed output dicts
  5. has_oc check accepts _olav: keys
"""

from __future__ import annotations

import json

import duckdb
import pytest


def _mem_con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


# --- 1. _COMMAND_MODULE_HINTS includes _olav: entries ---


class TestCommandModuleHintsOlav:
    def test_clock_command_has_olav_hint(self):
        from olav.core.schema_engine import _COMMAND_MODULE_HINTS

        hints_dict = {kw: mod for kw, mod in _COMMAND_MODULE_HINTS}
        assert "clock" in hints_dict
        assert hints_dict["clock"].startswith("_olav:")

    def test_logging_command_has_olav_hint(self):
        from olav.core.schema_engine import _COMMAND_MODULE_HINTS

        hints_dict = {kw: mod for kw, mod in _COMMAND_MODULE_HINTS}
        assert "logging" in hints_dict
        assert hints_dict["logging"].startswith("_olav:")

    def test_users_command_has_olav_hint(self):
        from olav.core.schema_engine import _COMMAND_MODULE_HINTS

        hints_dict = {kw: mod for kw, mod in _COMMAND_MODULE_HINTS}
        assert "users" in hints_dict
        assert hints_dict["users"].startswith("_olav:")

    def test_processes_command_has_olav_hint(self):
        from olav.core.schema_engine import _COMMAND_MODULE_HINTS

        hints_dict = {kw: mod for kw, mod in _COMMAND_MODULE_HINTS}
        assert "processes" in hints_dict or "cpu" in hints_dict

    def test_existing_oc_hints_preserved(self):
        from olav.core.schema_engine import _COMMAND_MODULE_HINTS

        hints_dict = {kw: mod for kw, mod in _COMMAND_MODULE_HINTS}
        assert hints_dict.get("lldp") == "openconfig-lldp"
        assert hints_dict.get("bgp") == "openconfig-bgp"
        assert hints_dict.get("interface") == "openconfig-interfaces"


# --- 2. build_mapping_rules generates _olav: paths ---


def _seed_olav_yang_and_catalog(con: duckdb.DuckDBPyConnection) -> None:
    from olav.core.bootstrap_yang import create_yang_leaves_table

    create_yang_leaves_table(con)
    yang_rows = [
        (
            "interfaces/interface/config/name",
            "name",
            "string",
            "Interface name",
            "openconfig-interfaces",
        ),
        (
            "_olav:diagnostic/clock/current-time",
            "current-time",
            "string",
            "Current device time",
            "_olav:diagnostic",
        ),
        (
            "_olav:diagnostic/clock/timezone",
            "timezone",
            "string",
            "Device timezone",
            "_olav:diagnostic",
        ),
        (
            "_olav:diagnostic/logging/message",
            "message",
            "string",
            "Log message",
            "_olav:diagnostic",
        ),
        ("_olav:system/users/username", "username", "string", "Active user", "_olav:system"),
    ]
    con.executemany(
        "INSERT INTO yang_leaves (yang_path, leaf_name, leaf_type, description, module) VALUES (?,?,?,?,?)",
        yang_rows,
    )

    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_catalog (
            source_type TEXT, source_name TEXT, platform TEXT,
            fields TEXT, description TEXT, updated_at TIMESTAMP
        )
    """)
    catalog_rows = [
        (
            "textfsm",
            "show clock",
            "cisco_ios",
            json.dumps(
                [{"name": "current_time", "type": "str"}, {"name": "timezone", "type": "str"}]
            ),
            "",
            None,
        ),
        (
            "textfsm",
            "show logging",
            "cisco_ios",
            json.dumps([{"name": "message", "type": "str"}]),
            "",
            None,
        ),
        (
            "textfsm",
            "show users",
            "cisco_ios",
            json.dumps([{"name": "username", "type": "str"}]),
            "",
            None,
        ),
    ]
    con.executemany("INSERT INTO schema_catalog VALUES (?,?,?,?,?,?)", catalog_rows)


def test_build_mapping_rules_generates_olav_paths() -> None:
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_olav_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    clock_rows = con.execute(
        "SELECT src_field, oc_path FROM mapping_rules WHERE command = 'show clock'"
    ).fetchall()
    assert clock_rows, "Expected mapping_rules for 'show clock'"
    for src_field, oc_path in clock_rows:
        assert oc_path.startswith("_olav:diagnostic/clock/"), (
            f"show clock field '{src_field}' mapped to {oc_path!r}"
        )
    con.close()


def test_build_mapping_rules_olav_coexists_with_oc() -> None:
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_olav_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    olav_count = con.execute(
        "SELECT COUNT(*) FROM mapping_rules WHERE oc_path LIKE '_olav:%'"
    ).fetchone()[0]
    assert olav_count > 0
    con.close()


# --- 3. normalization._oc_module_for_path handles _olav: paths ---


class TestOcModuleForPathOlav:
    def test_olav_diagnostic_path(self):
        from olav.core.normalization import _oc_module_for_path

        result = _oc_module_for_path("_olav:diagnostic/clock/current-time")
        assert result == "_olav:diagnostic"

    def test_olav_system_path(self):
        from olav.core.normalization import _oc_module_for_path

        result = _oc_module_for_path("_olav:system/users/username")
        assert result == "_olav:system"

    def test_olav_raw_path(self):
        from olav.core.normalization import _oc_module_for_path

        result = _oc_module_for_path("_olav:raw/netconf/bgp-reply")
        assert result == "_olav:raw"

    def test_olav_vendor_path(self):
        from olav.core.normalization import _oc_module_for_path

        result = _oc_module_for_path("_olav:vendor/cisco/feature-x")
        assert result == "_olav:vendor"

    def test_standard_oc_paths_still_work(self):
        from olav.core.normalization import _oc_module_for_path

        assert _oc_module_for_path("interfaces/interface/config/name") == "openconfig-interfaces"
        assert _oc_module_for_path("bgp/neighbors/neighbor/state/session-state") == "openconfig-bgp"


# --- 4. apply_oc_mapping produces _olav:-keyed output ---


class TestApplyOcMappingOlav:
    def _make_con(self):
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE mapping_rules (
                vendor TEXT NOT NULL, command TEXT NOT NULL,
                src_field TEXT NOT NULL, oc_path TEXT NOT NULL,
                confidence TEXT NOT NULL,
                PRIMARY KEY (vendor, command, src_field)
            )
        """)
        con.execute("""
            CREATE TABLE schema_catalog (
                source_type TEXT, source_name TEXT, platform TEXT,
                fields TEXT, description TEXT, updated_at TEXT
            )
        """)
        return con

    @staticmethod
    def _insert_mapping(con, vendor, command, src_field, oc_path, confidence="name_similarity"):
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
        con.execute(
            "INSERT INTO mapping_rules VALUES (?, ?, ?, ?, ?)",
            [vendor, command, src_field, oc_path, confidence],
        )

    def test_olav_diagnostic_mapping_produces_top_key(self):
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show clock",
            "current_time",
            "_olav:diagnostic/clock/current-time",
        )
        records = [{"current_time": "14:23:01 UTC"}]
        result = apply_oc_mapping(records, "cisco_ios", "show clock", con)

        assert len(result) == 1
        assert "_olav:diagnostic" in result[0]

    def test_olav_and_oc_coexist_in_same_record(self):
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show interfaces",
            "intf_name",
            "interfaces/interface/config/name",
        )
        self._insert_mapping(
            con,
            "cisco_ios",
            "show interfaces",
            "custom_field",
            "_olav:vendor/cisco/custom",
        )
        records = [{"intf_name": "Gi0/0", "custom_field": "vendor_data"}]
        result = apply_oc_mapping(records, "cisco_ios", "show interfaces", con)

        d = result[0]
        assert "openconfig-interfaces" in d
        assert "_olav:vendor" in d

    def test_olav_unmapped_fields_preserved(self):
        from olav.core.normalization import apply_oc_mapping

        con = self._make_con()
        self._insert_mapping(
            con,
            "cisco_ios",
            "show clock",
            "current_time",
            "_olav:diagnostic/clock/current-time",
        )
        records = [{"current_time": "14:23:01 UTC", "extra": "val"}]
        result = apply_oc_mapping(records, "cisco_ios", "show clock", con)

        assert "_unmapped" in result[0]
        assert result[0]["_unmapped"]["extra"] == "val"


# --- 5. has_oc check accepts _olav: keys ---


class TestHasOcOlavCheck:
    def test_has_oc_check_accepts_olav_keys(self):
        oc_result = [
            {"_olav:diagnostic": {"_olav:diagnostic": {"clock": {"current-time": "14:23:01"}}}}
        ]
        has_oc = any(
            isinstance(r, dict)
            and any(k.startswith("openconfig-") or k.startswith("_olav:") for k in r)
            for r in oc_result
        )
        assert has_oc

    def test_has_oc_check_still_rejects_empty(self):
        oc_result = [{"_unmapped": {"field": "value"}}]
        has_oc = any(
            isinstance(r, dict)
            and any(k.startswith("openconfig-") or k.startswith("_olav:") for k in r)
            for r in oc_result
        )
        assert not has_oc
