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

# NOTE: this path was ".olav/workspace/ops/netops_init/run.py" until 2026-08-05.
# The script moved to workspace/netops/ in a workspace reorg and the fixture was
# never updated, so all 15 tests in this file errored at setup with
# FileNotFoundError — they had stopped guarding populate_devices entirely.
_RUN_PY = (
    Path(__file__).resolve().parents[1]
    / ".olav" / "workspace" / "netops" / "netops_init" / "run.py"
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


def _populate(db_path, snapshot_id, nr):
    """Bridge these tests' Nornir-object API to the current inventory API.

    They were written when the helper took ``nr=<Nornir>``; populate_devices now
    reads the inventory itself via ``load_host_metadata()``. Rather than rewrite
    fifteen bodies, translate the stub inventory into the dict shape
    load_host_metadata returns and patch it in. Keeps the tests' original intent
    — "these fields come from inventory, verbatim" — while exercising the real
    code path.
    """
    from unittest.mock import patch

    from olav_netops.core import device_etl

    meta = {
        name: {
            "mgmt_ip": host.hostname,
            "platform": host.platform,
            "role": (host.data or {}).get("role"),
            "site": (host.data or {}).get("site"),
            "environment": (host.data or {}).get("environment"),
            "groups": [],
            "aliases": [a for a in (host.data or {}).get("aliases", [])],
            "extra": {},
        }
        for name, host in nr.inventory.hosts.items()
    }
    with patch.object(device_etl, "load_host_metadata", return_value=meta):
        return device_etl.populate_devices(db_path, snapshot_id)


def _put_capture(db_path, device, command="show version", platform=None):
    """Insert a bare raw_output_store row.

    Devices come from raw_output_store now — inventory alone no longer creates a
    row. Tests that only declared a Nornir host therefore need a capture to have
    anything to assert on.
    """
    with duckdb.connect(str(db_path)) as c:
        c.execute(
            "INSERT INTO netops.raw_output_store "
            "(device_name, command, raw_output, snapshot_id) VALUES (?, ?, ?, ?)",
            [device, command, "(synthetic raw)", "snap-1"],
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

class TestLoadHostMetadata:
    """These three tested ``run_mod._load_host_inventory(nr)``, which no longer
    exists — inventory reading moved into ``device_etl.load_host_metadata()``,
    which parses hosts.yaml itself instead of taking a Nornir object. The file
    had been erroring at setup since a workspace reorg, so nobody noticed the
    API move. Rewritten against the live function, same three properties.
    """

    @staticmethod
    def _with_hosts_yaml(tmp_path, monkeypatch, doc: str):
        import yaml as _yaml

        from olav_netops.core import config_paths, device_etl

        cfg = tmp_path / "config.yaml"
        (tmp_path / "hosts.yaml").write_text(doc)
        monkeypatch.setattr(config_paths, "resolve_nornir_config_path", lambda: cfg)
        return device_etl.load_host_metadata()

    def test_reads_platform_ip_and_environment(self, tmp_path, monkeypatch):
        inv = self._with_hosts_yaml(tmp_path, monkeypatch, """
R1:
  hostname: 10.0.0.1
  platform: cisco_ios
  data:
    environment: prod
R2:
  hostname: 10.0.0.2
  platform: juniper_junos
""")
        assert inv["R1"]["platform"] == "cisco_ios"
        assert inv["R1"]["mgmt_ip"] == "10.0.0.1"
        assert inv["R1"]["environment"] == "prod"
        assert inv["R2"]["platform"] == "juniper_junos"
        assert inv["R2"]["environment"] is None

    def test_non_mapping_host_is_skipped(self, tmp_path, monkeypatch):
        inv = self._with_hosts_yaml(tmp_path, monkeypatch, """
R1: null
R2:
  hostname: 10.0.0.2
""")
        assert "R1" not in inv
        assert "R2" in inv

    def test_whitespace_stripped_from_tags(self, tmp_path, monkeypatch):
        inv = self._with_hosts_yaml(tmp_path, monkeypatch, """
R1:
  hostname: 10.0.0.1
  platform: cisco_ios
  data:
    role: "  core  "
    site: "  hq  "
    environment: "   "
""")
        assert inv["R1"]["role"] == "core"
        assert inv["R1"]["site"] == "hq"
        assert inv["R1"]["environment"] is None, "whitespace-only tag → None"

    def test_missing_inventory_returns_empty(self, tmp_path, monkeypatch):
        from olav_netops.core import config_paths, device_etl

        monkeypatch.setattr(
            config_paths, "resolve_nornir_config_path", lambda: tmp_path / "config.yaml"
        )
        assert device_etl.load_host_metadata() == {}


class TestPopulateDevicesNornirAuthoritative:
    """Platform + IP come from Nornir, never re-derived."""

    def test_nornir_populates_basic_fields(self, run_mod, db_path):
        _put_capture(db_path, "R1")
        _put_capture(db_path, "R2")
        nr = _StubNornir({
            "R1": _StubHost("cisco_ios", "192.168.100.1", {"environment": "lab"}),
            "R2": _StubHost("juniper_junos", "192.168.100.2", {"environment": "lab"}),
        })
        n = _populate(db_path, "snap-1", nr)
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
        _populate(db_path, "snap-1", nr)
        row = _fetch_device(db_path, "R1")
        # ip_address reflects Nornir, not anything extracted from output
        assert row[1] == "192.168.100.1"


class TestPopulateDevicesProfileFields:
    """Model / os_version come from show-version parse via platform_profiles."""

    def test_cisco_model_os_extracted(self, run_mod, db_path):
        _put_show_version(db_path, "R1",
                          [{"HARDWARE": ["C3945"], "VERSION": "15.5(3)M4a"}])
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        _populate(db_path, "snap-1", nr)
        row = _fetch_device(db_path, "R1")
        # model_fields: [MODEL, HARDWARE] → no MODEL, so HARDWARE[0]=C3945
        assert row[4] == "C3945"
        # os_version_fields: [VERSION, ROMMON, SOFTWARE_IMAGE]
        assert row[5] == "15.5(3)M4a"

    def test_juniper_junos_version_field(self, run_mod, db_path):
        _put_show_version(db_path, "R1",
                          [{"JUNOS_VERSION": "18.4R3-S3", "MODEL": "vsrx"}])
        nr = _StubNornir({"R1": _StubHost("juniper_junos", "10.0.0.1", {})})
        _populate(db_path, "snap-1", nr)
        row = _fetch_device(db_path, "R1")
        assert row[4] == "vsrx"
        assert row[5] == "18.4R3-S3"

    def test_no_show_version_leaves_model_null(self, run_mod, db_path):
        # No parsed_outputs row for R1 → model/os_version stay NULL
        _put_capture(db_path, "R1")
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        _populate(db_path, "snap-1", nr)
        row = _fetch_device(db_path, "R1")
        assert row[4] is None
        assert row[5] is None


class TestPopulateDevicesVendorFallback:
    """Unknown platform still gets a vendor via rule-based inference."""

    def test_rule_based_vendor_for_unknown_platform(self, run_mod, db_path):
        # paloalto_panos has no YAML profile in builtin list — rule fallback wins
        _put_capture(db_path, "FW1")
        nr = _StubNornir({"FW1": _StubHost("paloalto_panos", "10.0.0.10", {})})
        _populate(db_path, "snap-1", nr)
        row = _fetch_device(db_path, "FW1")
        assert row[2] == "paloalto_panos"
        # Was "Palo Alto". platform_profiles derives the vendor as
        # platform.split("_")[0].title() and documents "No vendor-alias table in
        # code" — a display name like "Palo Alto" belongs in the YAML profile's
        # explicit `vendor:` field, which survives upgrades. So the rule output
        # is "Paloalto" until someone adds that profile.
        assert row[3] == "Paloalto"
        # No profile → no model/os extraction fields → NULL
        assert row[4] is None
        assert row[5] is None

    def test_completely_unknown_vendor(self, run_mod, db_path):
        _put_capture(db_path, "X1")
        nr = _StubNornir({"X1": _StubHost("weirdos_v2", "10.0.0.99", {})})
        _populate(db_path, "snap-1", nr)
        row = _fetch_device(db_path, "X1")
        assert row[3] == "Weirdos"


class TestPopulateDevicesUpsert:
    def test_rerun_preserves_existing_model(self, run_mod, db_path):
        # First pass: model captured
        _put_show_version(db_path, "R1",
                          [{"HARDWARE": ["C3945"], "VERSION": "15.5(3)M"}])
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        _populate(db_path, "snap-1", nr)
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
        _populate(db_path, "snap-2", nr)
        row = _fetch_device(db_path, "R1")
        assert row[4] == "C3945"  # preserved

    def test_environment_updated_on_rerun(self, run_mod, db_path):
        _put_capture(db_path, "R1")
        nr1 = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {"environment": "lab"})})
        _populate(db_path, "snap-1", nr1)
        assert _fetch_device(db_path, "R1")[6] == "lab"
        nr2 = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {"environment": "prod"})})
        _populate(db_path, "snap-2", nr2)
        assert _fetch_device(db_path, "R1")[6] == "prod"


class TestPopulateDevicesEdgeCases:
    def test_db_only_host_no_nornir_entry(self, run_mod, db_path):
        """Device in raw_output_store but not in inventory → typed from the CLI.

        This used to assert platform='unknown'. Device ETL now has an explicit
        CLI fallback for hosts missing from inventory — HARDWARE+VERSION in a
        parsed `show version` means cisco_ios, JUNOS_VERSION means
        juniper_junos — so an inventory-less device gets typed and its
        model/os_version extracted. Asserting the fallback is the point.
        """
        _put_show_version(db_path, "R99",
                          [{"HARDWARE": ["X"], "VERSION": "1"}])
        nr = _StubNornir({})
        _populate(db_path, "snap-1", nr)
        row = _fetch_device(db_path, "R99")
        assert row is not None, "captures alone must be enough to create a row"
        assert row[2] == "cisco_ios", (
            f"HARDWARE+VERSION should type it as cisco_ios, got {row[2]!r}"
        )
        assert row[3] == "Cisco"
        assert row[4] == "X" and row[5] == "1", "model/os come from the same parse"

    def test_inventory_only_host_gets_no_row(self, run_mod, db_path):
        """Inventory alone no longer invents a device row.

        Inverted deliberately: this test asserted "declared in Nornir but no
        captures yet — still a row". populate_devices now enumerates
        ``SELECT DISTINCT device_name FROM netops.raw_output_store``, so the
        device table describes what has actually been collected rather than what
        someone declared. Asserting the current contract keeps the case useful
        instead of leaving it to rot.
        """
        nr = _StubNornir({"R1": _StubHost("cisco_ios", "10.0.0.1", {})})
        assert _populate(db_path, "snap-1", nr) == 0
        assert _fetch_device(db_path, "R1") is None

    def test_empty_inventory_no_captures_returns_zero(self, run_mod, db_path):
        nr = _StubNornir({})
        n = _populate(db_path, "snap-1", nr)
        assert n == 0


# ──────────────────────────────────────────────────────────────────────────
# Role derivation for fleets imported without an inventory (dev_docs/115 §1g)
# ──────────────────────────────────────────────────────────────────────────

class TestRoleDerivedFromHostname:
    """role was NULL for all 339 devices of an offline-imported fleet.

    Three consumers assume it is populated (execute_sql's SCHEMA_HINT,
    SCHEMA_REFERENCE.md, and sim/graph_view.py's BGP-fact gate), and the agent
    asked for "the alpha border router", could not use role, guessed hostnames,
    and analysed the wrong device.
    """

    def test_offline_import_derives_role_from_hostname(self, db_path, monkeypatch):
        from olav_netops.core import device_etl

        # No hosts.yaml — exactly the offline-import path.
        monkeypatch.setattr(device_etl, "load_host_metadata", lambda: {})
        _put_show_version(db_path, "alpha-border-4500x.net.demo.internal", [])
        device_etl.populate_devices(db_path)

        with duckdb.connect(str(db_path), read_only=True) as c:
            role, meta = c.execute(
                "SELECT role, metadata FROM netops.devices WHERE hostname LIKE 'alpha-border%'"
            ).fetchone()
        assert role == "border", f"offline import left role={role!r}"
        assert json.loads(meta)["role_source"] == "hostname", (
            "an inferred role must be marked as inferred"
        )

    def test_inventory_role_wins_and_is_marked_as_declared(self, db_path, monkeypatch):
        from olav_netops.core import device_etl

        monkeypatch.setattr(
            device_etl,
            "load_host_metadata",
            lambda: {"alpha-border-4500x.net.demo.internal": {"role": "distribution"}},
        )
        _put_show_version(db_path, "alpha-border-4500x.net.demo.internal", [])
        device_etl.populate_devices(db_path)

        with duckdb.connect(str(db_path), read_only=True) as c:
            role, meta = c.execute(
                "SELECT role, metadata FROM netops.devices WHERE hostname LIKE 'alpha-border%'"
            ).fetchone()
        assert role == "distribution", (
            "inventory is authoritative — derivation must not override it"
        )
        assert json.loads(meta)["role_source"] == "inventory"

    def test_unmatched_hostname_leaves_role_null(self, db_path, monkeypatch):
        from olav_netops.core import device_etl

        monkeypatch.setattr(device_etl, "load_host_metadata", lambda: {})
        _put_show_version(db_path, "alpha-as1-3850.net.demo.internal", [])
        device_etl.populate_devices(db_path)

        with duckdb.connect(str(db_path), read_only=True) as c:
            role, meta = c.execute(
                "SELECT role, metadata FROM netops.devices WHERE hostname LIKE 'alpha-as1%'"
            ).fetchone()
        assert role is None, f"access switch should stay NULL, got {role!r}"
        assert meta is None or "role_source" not in json.loads(meta)


class TestInferRoleFromHostname:
    """A wrong role is worse than no role — both the model and graph_view
    treat it as fact. These are the guards that keep it conservative."""

    def test_real_fleet_hostnames(self):
        from olav_netops.core.device_etl import infer_role_from_hostname as f

        assert f("alpha-border-4500x.net.demo.internal") == "border"
        assert f("kappa-2P1-BORDER-S1.net.demo.internal") == "border"  # case-insensitive
        assert f("alpha-core-6807v.net.demo.internal") == "core"
        assert f("alpha-wan-6880v.net.demo.internal") == "wan"
        assert f("alpha-oob.net.demo.internal") == "oob"
        assert f("alpha-dc-93180-a1-1.net.demo.internal") is None
        assert f("alpha-ap1-3850.net.demo.internal") is None

    def test_no_substring_matches(self):
        from olav_netops.core.device_etl import infer_role_from_hostname as f

        assert f("coreless-sw1") is None, "'coreless' is not 'core'"
        assert f("bordeaux-sw1") is None, "'bordeaux' is not 'border'"

    def test_domain_cannot_tag_every_device_in_it(self):
        from olav_netops.core.device_etl import infer_role_from_hostname as f

        assert f("host1.core.example.com") is None, (
            "only the first DNS label may contribute a role"
        )

    def test_empty_and_specific_before_generic(self):
        from olav_netops.core.device_etl import infer_role_from_hostname as f

        assert f("") is None
        # 'border' must win over the generic 'router' when both appear.
        assert f("dc1-border-router-1") == "border"
