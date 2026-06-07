"""Unit tests for olav_netops.core.topology_intent.

Covers:
  * load_intent — YAML parsing, normalisation, dedupe
  * intent_to_concept — alias map + passthrough for unknown protocols
  * missing_recipes — gap detection against view_recipes + netops.devices
  * effective_intent — builtin default fallback
"""
from __future__ import annotations

import duckdb
import pytest

from olav_netops.core import topology_intent as ti


# ──────────────────────────────────────────────────────────────────────────
# load_intent
# ──────────────────────────────────────────────────────────────────────────

class TestLoadIntent:
    def test_missing_file_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ti, "_intent_path", lambda: tmp_path / "absent.yaml")
        assert ti.load_intent() == []

    def test_basic_list(self, monkeypatch, tmp_path):
        p = tmp_path / "topology.yaml"
        p.write_text("protocols:\n  - bgp\n  - ospf\n  - cdp_lldp\n")
        monkeypatch.setattr(ti, "_intent_path", lambda: p)
        assert ti.load_intent() == ["bgp", "ospf", "cdp_lldp"]

    def test_normalises_case_and_whitespace(self, monkeypatch, tmp_path):
        p = tmp_path / "topology.yaml"
        p.write_text("protocols:\n  - '  BGP  '\n  - OSPF\n  - '  cdp_lldp '\n")
        monkeypatch.setattr(ti, "_intent_path", lambda: p)
        assert ti.load_intent() == ["bgp", "ospf", "cdp_lldp"]

    def test_dedupes_preserving_first_order(self, monkeypatch, tmp_path):
        p = tmp_path / "topology.yaml"
        p.write_text("protocols:\n  - bgp\n  - ospf\n  - bgp\n  - OSPF\n")
        monkeypatch.setattr(ti, "_intent_path", lambda: p)
        assert ti.load_intent() == ["bgp", "ospf"]

    def test_ignores_non_string_entries(self, monkeypatch, tmp_path):
        p = tmp_path / "topology.yaml"
        p.write_text("protocols:\n  - bgp\n  - 42\n  - null\n  - ospf\n")
        monkeypatch.setattr(ti, "_intent_path", lambda: p)
        assert ti.load_intent() == ["bgp", "ospf"]

    def test_protocols_not_list_returns_empty(self, monkeypatch, tmp_path):
        p = tmp_path / "topology.yaml"
        p.write_text("protocols: bgp\n")  # scalar, not list
        monkeypatch.setattr(ti, "_intent_path", lambda: p)
        assert ti.load_intent() == []

    def test_yaml_parse_error_returns_empty(self, monkeypatch, tmp_path):
        p = tmp_path / "topology.yaml"
        p.write_text("protocols:\n  - [::broken\n")
        monkeypatch.setattr(ti, "_intent_path", lambda: p)
        assert ti.load_intent() == []


# ──────────────────────────────────────────────────────────────────────────
# intent_to_concept
# ──────────────────────────────────────────────────────────────────────────

class TestIntentToConcept:
    def test_aliased_bgp(self):
        assert ti.intent_to_concept("bgp") == "bgp_neighbors"

    def test_aliased_ospf(self):
        assert ti.intent_to_concept("ospf") == "ospf_neighbors"

    def test_aliased_cdp_lldp(self):
        assert ti.intent_to_concept("cdp_lldp") == "topology_l2"

    def test_unknown_passthrough(self):
        # New protocols fall through with intent == concept.
        assert ti.intent_to_concept("bfd") == "bfd"
        assert ti.intent_to_concept("isis") == "isis"
        assert ti.intent_to_concept("firewall_rules") == "firewall_rules"


# ──────────────────────────────────────────────────────────────────────────
# missing_recipes
# ──────────────────────────────────────────────────────────────────────────

class TestMissingRecipes:
    @pytest.fixture
    def conn(self):
        c = duckdb.connect(":memory:")
        c.execute("CREATE SCHEMA netops")
        c.execute(
            "CREATE TABLE netops.devices ("
            "hostname VARCHAR, platform VARCHAR)"
        )
        c.execute(
            "CREATE TABLE view_recipes ("
            "command VARCHAR, concept VARCHAR, vendor_hint VARCHAR)"
        )
        yield c
        c.close()

    def test_empty_intent_returns_empty(self, conn):
        assert ti.missing_recipes(conn, []) == []

    def test_no_devices_returns_empty(self, conn):
        # intent non-empty but no devices -> nothing to complain about
        assert ti.missing_recipes(conn, ["bgp"]) == []

    def test_all_recipes_present(self, conn):
        conn.execute("INSERT INTO netops.devices VALUES ('R1', 'cisco_ios')")
        conn.execute(
            "INSERT INTO view_recipes VALUES "
            "('show bgp summary', 'bgp_neighbors', 'cisco_ios')"
        )
        assert ti.missing_recipes(conn, ["bgp"]) == []

    def test_missing_recipe_flagged(self, conn):
        conn.execute("INSERT INTO netops.devices VALUES ('R1', 'cisco_ios')")
        conn.execute("INSERT INTO netops.devices VALUES ('R2', 'juniper_junos')")
        conn.execute(
            "INSERT INTO view_recipes VALUES "
            "('show bgp summary', 'bgp_neighbors', 'cisco_ios')"
        )
        gaps = ti.missing_recipes(conn, ["bgp"])
        assert gaps == [("bgp", "juniper_junos")]

    def test_universal_recipe_satisfies_all_vendors(self, conn):
        conn.execute("INSERT INTO netops.devices VALUES ('R1', 'cisco_ios')")
        conn.execute("INSERT INTO netops.devices VALUES ('R2', 'juniper_junos')")
        conn.execute(
            "INSERT INTO view_recipes VALUES "
            "('@topology_links', 'topology_l2', 'universal')"
        )
        assert ti.missing_recipes(conn, ["cdp_lldp"]) == []

    def test_unknown_protocol_uses_concept_passthrough(self, conn):
        """User writes `- bfd`; missing_recipes should look for concept 'bfd'."""
        conn.execute("INSERT INTO netops.devices VALUES ('R1', 'cisco_ios')")
        # No BFD recipe anywhere — should flag the gap
        gaps = ti.missing_recipes(conn, ["bfd"])
        assert gaps == [("bfd", "cisco_ios")]
        # Add it under concept 'bfd' + vendor 'cisco_ios' → gap closes
        conn.execute(
            "INSERT INTO view_recipes VALUES "
            "('show bfd session', 'bfd', 'cisco_ios')"
        )
        assert ti.missing_recipes(conn, ["bfd"]) == []

    def test_missing_devices_table_returns_empty(self, conn):
        conn.execute("DROP TABLE netops.devices")
        assert ti.missing_recipes(conn, ["bgp"]) == []


# ──────────────────────────────────────────────────────────────────────────
# effective_intent
# ──────────────────────────────────────────────────────────────────────────

class TestEffectiveIntent:
    def test_user_declared_wins(self, monkeypatch):
        monkeypatch.setattr(ti, "load_intent", lambda: ["bgp", "isis"])
        assert ti.effective_intent() == ["bgp", "isis"]

    def test_defaults_when_empty(self, monkeypatch):
        monkeypatch.setattr(ti, "load_intent", lambda: [])
        assert ti.effective_intent() == list(ti.DEFAULT_INTENT)
        # Ensure we return a copy — callers shouldn't mutate the constant.
        result = ti.effective_intent()
        result.append("xxx")
        assert "xxx" not in ti.DEFAULT_INTENT
