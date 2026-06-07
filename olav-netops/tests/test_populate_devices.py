"""Unit tests for netops_init._populate_devices (R70 Device ETL).

Nornir stub + in-memory DuckDB — no real SSH / LLM.  Covers:
  * hostname / ip_address / platform trusted verbatim from Nornir
  * vendor resolved via platform_profiles (YAML profile or rule fallback)
  * model / os_version extracted from show-version parse via profile fields
  * UPSERT COALESCE preserves non-null columns on re-run
  * environment tag propagated from Nornir data.environment
  * unknown platform still rows in (platform='unknown' but hostname captured)
  * Nornir-only hosts (no DB capture yet) get a row with NULL model/os_version
  * DB-only hosts (LLDP-discovered, no Nornir entry) still get a row
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import duckdb
import pytest


# ──────────────────────────────────────────────────────────────────────────
# Load the netops_init/run.py module without the full Nornir bootstrap.
# ──────────────────────────────────────────────────────────────────────────

_RUN_PY = (
    Path(__file__).resolve().parents[1]
    / ".olav" / "workspace" / "ops" / "netops_init" / "run.py"
)


def _import_run_module():
    spec = importlib.util.spec_from_file_location("_netops_init_run", _RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_netops_init_run"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _import_run_module()


# ──────────────────────────────────────────────────────────────────────────
# Nornir stub — mimics nr.inventory.hosts[name].platform / hostname / data
# ──────────────────────────────────────────────────────────────────────────

class _StubHost:
    def __init__(self, platform, hostname, data=None):
        self.platform = platform
        self.hostname = hostname
        self.data = data or {}


class _StubInventory:
    def __init__(self, hosts):
        self.hosts = hosts


class _StubNornir:
    def __init__(self, hosts):
        self.inventory = _StubInventory(hosts)

    def close_connections(self):
        pass


# ──────────────────────────────────────────────────────────────────────────
# Shared DB fixture
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "main.duckdb"
    with duckdb.connect(str(p)) as c:
        c.execute("CREATE SCHEMA netops")
        # Minimal schema matching what Device ETL expects
        c.execute(
            "CREATE TABLE netops.devices ("
            "hostname VARCHAR NOT NULL PRIMARY KEY, "
            "ip_address VARCHAR, platform VARCHAR, site VARCHAR, "
            "role VARCHAR, vendor VARCHAR, model VARCHAR, "
            "os_version VARCHAR, environment VARCHAR, "
            "last_seen TIMESTAMP, metadata JSON)"
        )
        c.execute(
            "CREATE TABLE netops.parsed_outputs ("
            "device_name VARCHAR, command VARCHAR, parsed_data JSON, "
            "snapshot_id VARCHAR, raw_output TEXT, "
            "raw_output_hash VARCHAR, ingested_at TIMESTAMP)"
        )
        c.execute(
            "CREATE TABLE netops.raw_output_store ("
            "device_name VARCHAR, command VARCHAR, raw_output TEXT, "
            "snapshot_id VARCHAR, updated_at TIMESTAMP)"
        )
    return p


def _put_show_version(db_path, device, entries):
    with duckdb.connect(str(db_path)) as c:
        c.execute(
            "INSERT INTO netops.parsed_outputs "
            "(device_name, command, parsed_data, snapshot_id) VALUES (?, ?, ?, ?)",
            [device, "show version", json.dumps(entries), "snap-1"],
        )
        # raw_output_store is the primary source for "what devices exist"
        c.execute(
            "INSERT INTO netops.raw_output_store "
            "(device_name, command, raw_output, snapshot_id) VALUES (?, ?, ?, ?)",
            [device, "show version", "(synthetic raw)", "snap-1"],
        )


def _fetch_device(db_path, hostname):
    with duckdb.connect(str(db_path), read_only=True) as c:
        return c.execute(
            "SELECT hostname, ip_address, platform, vendor, model, "
            "os_version, environment FROM netops.devices WHERE hostname = ?",
            [hostname],
        ).fetchone()


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────

class TestLoadHostInventory:
    def test_reads_via_nornir_abstraction(self, run_mod):
        nr = _StubNornir({
            "R1": _StubHost("cisco_ios", "10.0.0.1", {"environment": "prod"}),
            "R2": _StubHost("juniper_junos", "10.0.0.2", {}),
        })
        inv = run_mod._load_host_inventory(nr)
        assert inv["R1"]["platform"] == "cisco_ios"
        assert inv["R1"]["hostname"] == "10.0.0.1"
        assert inv["R1"]["environment"] == "prod"
        assert inv["R2"]["platform"] == "juniper_junos"
        # No environment tag → key absent (not empty string)
        assert "environment" not in inv["R2"]

    def test_empty_host_produces_empty_entry(self, run_mod):
        nr = _StubNornir({
            "R1": _StubHost(None, None),
        })
        inv = run_mod._load_host_inventory(nr)
        # Entry not added when both platform + hostname are missing
        assert "R1" not in inv

    def test_whitespace_stripped(self, run_mod):
        nr = _StubNornir({
            "R1": _StubHost("  cisco_ios  ", "  10.0.0.1  ",
                            {"environment": "  lab  "}),
        })
        inv = run_mod._load_host_inventory(nr)
        assert inv["R1"] == {
            "platform": "cisco_ios",
            "hostname": "10.0.0.1",
            "environment": "lab",
        }


class TestPopulateDevicesNornirAuthoritative:
    """Platform + IP come from Nornir, never re-derived."""

    def test_nornir_populates_basic_fields(self, run_mod, db_path):
        nr = _StubNornir({
            "R1": _StubHost("cisco_ios", "192.168.100.1", {"environment": "lab"}),
            "R2": _StubHost("juniper_junos", "192.168.100.2", {"environment": "lab"}),
        })
        n = run_mod._populate_devices(db_path, "snap-1", nr=nr)
        assert n == 2
        r1 = _fetch_device(db_path, "R1")
        assert r1[:4] == ("R1", "192.168.100.1", "cisco_ios", "Cisco")
        r2 = _fetch_device(db_path, "R2")
        assert r2[:4] == ("R2", "192.168.100.2", "juniper_junos", "Juniper")

    def test_ip_is_nornir_hostname_not_show_version(self, run_mod, db_path):
        """Nornir hostname wins even if show-version parse has a different IP."""
        _put_show_version(db_path, "R1",
                          [{"HARDWARE": ["C3945"], "VERSION": "15.5(3)M"}])
        nr = _StubNornir({
            "R1": _StubHost("cisco_ios", "192.168.100.1", {}),
        })
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "R1")
        # ip_address reflects Nornir, not anything extracted from output
        assert row[1] == "192.168.100.1"


class TestPopulateDevicesProfileFields:
    """Model / os_version come from show-version parse via platform_profiles."""

    def test_cisco_model_os_extracted(self, run_mod, db_path):
        _put_show_version(db_path, "R1",
                          [{"HARDWARE": ["C3945"], "VERSION": "15.5(3)M4a"}])
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "R1")
        # model_fields: [MODEL, HARDWARE] → no MODEL, so HARDWARE[0]=C3945
        assert row[4] == "C3945"
        # os_version_fields: [VERSION, ROMMON, SOFTWARE_IMAGE]
        assert row[5] == "15.5(3)M4a"

    def test_juniper_junos_version_field(self, run_mod, db_path):
        _put_show_version(db_path, "R1",
                          [{"JUNOS_VERSION": "18.4R3-S3", "MODEL": "vsrx"}])
        nr = _StubNornir({"R1": _StubHost("juniper_junos", "10.0.0.1", {})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "R1")
        assert row[4] == "vsrx"
        assert row[5] == "18.4R3-S3"

    def test_no_show_version_leaves_model_null(self, run_mod, db_path):
        # No parsed_outputs row for R1 → model/os_version stay NULL
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "R1")
        assert row[4] is None
        assert row[5] is None


class TestPopulateDevicesVendorFallback:
    """Unknown platform still gets a vendor via rule-based inference."""

    def test_rule_based_vendor_for_unknown_platform(self, run_mod, db_path):
        # paloalto_panos has no YAML profile in builtin list — rule fallback wins
        nr = _StubNornir({"FW1": _StubHost("paloalto_panos", "10.0.0.10", {})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "FW1")
        assert row[2] == "paloalto_panos"
        assert row[3] == "Palo Alto"
        # No profile → no model/os extraction fields → NULL
        assert row[4] is None
        assert row[5] is None

    def test_completely_unknown_vendor(self, run_mod, db_path):
        nr = _StubNornir({"X1": _StubHost("weirdos_v2", "10.0.0.99", {})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "X1")
        assert row[3] == "Weirdos"


class TestPopulateDevicesUpsert:
    def test_rerun_preserves_existing_model(self, run_mod, db_path):
        # First pass: model captured
        _put_show_version(db_path, "R1",
                          [{"HARDWARE": ["C3945"], "VERSION": "15.5(3)M"}])
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        assert _fetch_device(db_path, "R1")[4] == "C3945"

        # Second pass with NO show-version data → current extraction returns None,
        # but UPSERT COALESCE keeps the previously stored model.
        with duckdb.connect(str(db_path)) as c:
            c.execute("DELETE FROM netops.parsed_outputs")
            c.execute("DELETE FROM netops.raw_output_store")
            c.execute(
                "INSERT INTO netops.raw_output_store "
                "(device_name, command, raw_output, snapshot_id) VALUES (?,?,?,?)",
                ["R1", "show version", "(raw)", "snap-2"],
            )
        run_mod._populate_devices(db_path, "snap-2", nr=nr)
        row = _fetch_device(db_path, "R1")
        assert row[4] == "C3945"  # preserved

    def test_environment_updated_on_rerun(self, run_mod, db_path):
        nr1 = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {"environment": "lab"})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr1)
        assert _fetch_device(db_path, "R1")[6] == "lab"
        nr2 = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {"environment": "prod"})})
        run_mod._populate_devices(db_path, "snap-2", nr=nr2)
        assert _fetch_device(db_path, "R1")[6] == "prod"


class TestPopulateDevicesEdgeCases:
    def test_db_only_host_no_nornir_entry(self, run_mod, db_path):
        """Device exists in raw_output_store (e.g. LLDP-discovered) but
        not in Nornir inventory → row is written with platform='unknown'."""
        _put_show_version(db_path, "R99",
                          [{"HARDWARE": ["X"], "VERSION": "1"}])
        nr = _StubNornir({})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "R99")
        assert row is not None
        assert row[2] == "unknown"
        assert row[3] == ""  # no vendor — platform unknown
        # model/os_version NOT extracted because platform is None in ETL
        assert row[4] is None
        assert row[5] is None

    def test_nornir_only_host_no_show_version(self, run_mod, db_path):
        """Device declared in Nornir but no captures yet — still a row."""
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        run_mod._populate_devices(db_path, "snap-1", nr=nr)
        row = _fetch_device(db_path, "R1")
        assert row is not None
        assert row[2] == "cisco_ios"

    def test_empty_inventory_no_captures_returns_zero(self, run_mod, db_path):
        nr = _StubNornir({})
        n = run_mod._populate_devices(db_path, "snap-1", nr=nr)
        assert n == 0
