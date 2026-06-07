"""Unit tests for olav_netops.core.view_builder.

Exercises the R70 view pipeline end-to-end on in-memory DuckDB:
  * view_name_for concept → v_<concept>_auto naming
  * _json_extract / _json_extract_any COALESCE across cases
  * _vendor_filter_clause universal vs specific
  * _escape_sql_literal
  * _BGP_STATE_CASE / _OSPF_STATE_CASE canonical normalization
  * _bgp_branch / _ospf_branch / _l2_branch / _custom_branch SQL generation
  * build_one_view + build_all_views + rebuild_views_for_command
  * ensure_view_recipes_table idempotent DDL
"""
from __future__ import annotations

import json

import duckdb
import pytest

from olav_netops.core import view_builder as vb


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute("CREATE SCHEMA netops")
    c.execute(
        "CREATE TABLE netops.parsed_outputs ("
        "device_name VARCHAR NOT NULL, command VARCHAR NOT NULL, "
        "parsed_data JSON, snapshot_id VARCHAR)"
    )
    c.execute(
        "CREATE TABLE netops.devices ("
        "hostname VARCHAR NOT NULL PRIMARY KEY, platform VARCHAR)"
    )
    c.execute(
        "CREATE TABLE netops.topology_links ("
        "source_device VARCHAR, source_interface VARCHAR, "
        "destination_device VARCHAR, destination_interface VARCHAR, "
        "discovery_protocol VARCHAR, link_status VARCHAR, snapshot_id VARCHAR)"
    )
    vb.ensure_view_recipes_table(c)
    yield c
    c.close()


def _insert_recipe(conn, **kw) -> None:
    conn.execute(
        "INSERT INTO view_recipes "
        "(command, concept, vendor_hint, field_mappings, filter_expr, discovered_at) "
        "VALUES (?, ?, ?, ?, ?, NOW())",
        [
            kw["command"],
            kw["concept"],
            kw.get("vendor_hint", "universal"),
            json.dumps(kw.get("field_mappings", {})),
            kw.get("filter_expr"),
        ],
    )


def _insert_parsed(conn, device, command, rows, platform="cisco_ios",
                   snapshot_id="snap-1"):
    conn.execute(
        "INSERT INTO netops.parsed_outputs VALUES (?, ?, ?, ?)",
        [device, command, json.dumps(rows), snapshot_id],
    )
    # Ensure device row so _vendor_filter_clause can join
    conn.execute(
        "INSERT OR REPLACE INTO netops.devices (hostname, platform) VALUES (?, ?)",
        [device, platform],
    )


# ──────────────────────────────────────────────────────────────────────────
# view_name_for
# ──────────────────────────────────────────────────────────────────────────

class TestViewNameFor:
    def test_bgp(self):
        assert vb.view_name_for("bgp_neighbors") == "v_bgp_neighbors_auto"

    def test_ospf(self):
        assert vb.view_name_for("ospf_neighbors") == "v_ospf_neighbors_auto"

    def test_topology_l2(self):
        assert vb.view_name_for("topology_l2") == "v_l2_links_auto"

    def test_custom_concept(self):
        assert vb.view_name_for("firewall_rules") == "v_firewall_rules_auto"

    def test_custom_isis(self):
        assert vb.view_name_for("isis_neighbors") == "v_isis_neighbors_auto"


# ──────────────────────────────────────────────────────────────────────────
# _json_extract / _json_extract_any
# ──────────────────────────────────────────────────────────────────────────

class TestJsonExtract:
    def test_case_symmetric_field_single_extract(self):
        sql = vb._json_extract("123")
        assert "COALESCE" not in sql
        assert "'$.123'" in sql

    def test_mixed_case_field_produces_coalesce(self):
        sql = vb._json_extract("Neighbor_IP")
        assert "COALESCE" in sql
        assert "neighbor_ip" in sql
        assert "NEIGHBOR_IP" in sql

    def test_any_single_candidate(self):
        sql = vb._json_extract_any("state")
        assert "COALESCE" in sql  # coalesce of lower + upper inside _json_extract
        # No outer wrapping COALESCE beyond the single-extract one
        assert sql.count("COALESCE") == 1

    def test_any_multiple_candidates(self):
        sql = vb._json_extract_any("state", "state_pfxrcd")
        # Outer COALESCE across the two candidates plus inner ones
        assert sql.count("COALESCE") >= 2


# ──────────────────────────────────────────────────────────────────────────
# _vendor_filter_clause
# ──────────────────────────────────────────────────────────────────────────

class TestVendorFilterClause:
    def test_universal_returns_empty(self):
        assert vb._vendor_filter_clause("universal") == ""

    def test_none_returns_empty(self):
        assert vb._vendor_filter_clause(None) == ""

    def test_empty_string_returns_empty(self):
        assert vb._vendor_filter_clause("") == ""

    def test_specific_vendor_produces_join(self):
        clause = vb._vendor_filter_clause("cisco_ios")
        assert "platform = 'cisco_ios'" in clause
        assert "netops.devices" in clause


# ──────────────────────────────────────────────────────────────────────────
# _escape_sql_literal
# ──────────────────────────────────────────────────────────────────────────

class TestEscapeSqlLiteral:
    def test_no_quotes(self):
        assert vb._escape_sql_literal("show bgp") == "show bgp"

    def test_single_quote_doubled(self):
        assert vb._escape_sql_literal("O'Brien") == "O''Brien"


# ──────────────────────────────────────────────────────────────────────────
# State canonical normalization (via end-to-end view build)
# ──────────────────────────────────────────────────────────────────────────

class TestBgpStateCase:
    """_BGP_STATE_CASE regex + LIKE patterns → canonical values."""

    def test_numeric_becomes_established(self, conn):
        _insert_recipe(conn, command="show bgp summary", concept="bgp_neighbors",
                       vendor_hint="cisco_ios",
                       field_mappings={"neighbor_ip": "neighbor_ip",
                                       "neighbor_as": "neighbor_as",
                                       "state": "state_pfxrcd",
                                       "uptime": "up_down"})
        _insert_parsed(conn, "R1", "show bgp summary",
                       [{"neighbor_ip": "10.0.0.1", "neighbor_as": "65001",
                         "state_pfxrcd": "3", "up_down": "1w2d"}])
        vb.build_one_view(conn, "bgp_neighbors")
        row = conn.execute(
            "SELECT state FROM netops.v_bgp_neighbors_auto"
        ).fetchone()
        assert row[0] == "Established"

    def test_idle_canonical(self, conn):
        _insert_recipe(conn, command="show bgp summary", concept="bgp_neighbors",
                       vendor_hint="cisco_ios",
                       field_mappings={"neighbor_ip": "neighbor_ip",
                                       "neighbor_as": "neighbor_as",
                                       "state": "state_pfxrcd",
                                       "uptime": "up_down"})
        _insert_parsed(conn, "R1", "show bgp summary",
                       [{"neighbor_ip": "10.0.0.1", "neighbor_as": "65001",
                         "state_pfxrcd": "Idle", "up_down": "never"}])
        vb.build_one_view(conn, "bgp_neighbors")
        row = conn.execute(
            "SELECT state FROM netops.v_bgp_neighbors_auto"
        ).fetchone()
        assert row[0] == "Idle"

    def test_establ_prefix_normalised(self, conn):
        _insert_recipe(conn, command="show bgp summary", concept="bgp_neighbors",
                       vendor_hint="cisco_ios",
                       field_mappings={"neighbor_ip": "neighbor_ip",
                                       "neighbor_as": "neighbor_as",
                                       "state": "state",
                                       "uptime": "uptime"})
        _insert_parsed(conn, "R1", "show bgp summary",
                       [{"neighbor_ip": "10.0.0.1", "neighbor_as": "65001",
                         "state": "Established", "uptime": "1d"}])
        vb.build_one_view(conn, "bgp_neighbors")
        row = conn.execute(
            "SELECT state FROM netops.v_bgp_neighbors_auto"
        ).fetchone()
        assert row[0] == "Established"


class TestOspfStateCase:
    def test_full_with_role_suffix_preserved(self, conn):
        _insert_recipe(conn, command="show ip ospf neighbor",
                       concept="ospf_neighbors", vendor_hint="cisco_ios",
                       field_mappings={"neighbor_id": "neighbor_id",
                                       "neighbor_ip": "address",
                                       "interface": "interface",
                                       "state": "state",
                                       "dead_time": "dead_time"})
        _insert_parsed(conn, "R1", "show ip ospf neighbor",
                       [{"neighbor_id": "2.2.2.2", "address": "10.1.12.2",
                         "interface": "Gi0/0", "state": "FULL/BDR",
                         "dead_time": "00:00:35"}])
        vb.build_one_view(conn, "ospf_neighbors")
        row = conn.execute(
            "SELECT state FROM netops.v_ospf_neighbors_auto"
        ).fetchone()
        # Role suffix must be preserved (Cisco-specific semantics survive)
        assert row[0] == "FULL/BDR"

    def test_junos_full_no_role_suffix(self, conn):
        _insert_recipe(conn, command="show ospf neighbor",
                       concept="ospf_neighbors", vendor_hint="juniper_junos",
                       field_mappings={"neighbor_id": "id",
                                       "neighbor_ip": "address",
                                       "interface": "interface",
                                       "state": "state",
                                       "dead_time": "dead_time"})
        _insert_parsed(conn, "R1", "show ospf neighbor",
                       [{"id": "2.2.2.2", "address": "10.1.12.2",
                         "interface": "ge-0/0/0", "state": "Full",
                         "dead_time": "35"}],
                       platform="juniper_junos")
        vb.build_one_view(conn, "ospf_neighbors")
        row = conn.execute(
            "SELECT state FROM netops.v_ospf_neighbors_auto"
        ).fetchone()
        assert row[0] == "Full"


# ──────────────────────────────────────────────────────────────────────────
# L2 branch (topology_l2)
# ──────────────────────────────────────────────────────────────────────────

class TestL2Branch:
    def test_projects_topology_links(self, conn):
        _insert_recipe(conn, command="@topology_links", concept="topology_l2",
                       vendor_hint="universal", field_mappings={})
        conn.execute(
            "INSERT INTO netops.topology_links VALUES "
            "('R1', 'Gi0/0', 'R2', 'Gi0/0', 'CDP', 'up', 'snap-1')"
        )
        result = vb.build_one_view(conn, "topology_l2")
        assert result == {"v_l2_links_auto": 1}
        row = conn.execute(
            "SELECT source_device, discovery_protocol FROM netops.v_l2_links_auto"
        ).fetchone()
        assert row == ("R1", "CDP")


# ──────────────────────────────────────────────────────────────────────────
# Custom branch (user-defined concepts)
# ──────────────────────────────────────────────────────────────────────────

class TestCustomBranch:
    def test_firewall_rules_view(self, conn):
        """User-defined concept 'firewall_rules' goes through _custom_branch."""
        _insert_recipe(conn, command="show security policy",
                       concept="firewall_rules",
                       vendor_hint="paloalto_panos",
                       field_mappings={"rule_name": "NAME",
                                       "action": "ACTION"})
        _insert_parsed(conn, "FW1", "show security policy",
                       [{"NAME": "allow_web", "ACTION": "permit"},
                        {"NAME": "deny_all", "ACTION": "deny"}],
                       platform="paloalto_panos")
        result = vb.build_one_view(conn, "firewall_rules")
        assert result == {"v_firewall_rules_auto": 2}
        rows = conn.execute(
            "SELECT rule_name, action FROM netops.v_firewall_rules_auto ORDER BY rule_name"
        ).fetchall()
        assert rows == [("allow_web", "permit"), ("deny_all", "deny")]

    def test_empty_field_mappings_produces_no_branch(self, conn):
        # Empty mappings → _custom_branch returns "" → no view rows
        _insert_recipe(conn, command="show x", concept="custom_empty",
                       vendor_hint="cisco_ios", field_mappings={})
        result = vb.build_one_view(conn, "custom_empty")
        assert result == {}

    def test_filter_expr_applied(self, conn):
        _insert_recipe(conn, command="show security policy",
                       concept="firewall_rules",
                       vendor_hint="paloalto_panos",
                       field_mappings={"rule_name": "NAME", "action": "ACTION"},
                       filter_expr="ACTION = 'permit'")
        _insert_parsed(conn, "FW1", "show security policy",
                       [{"NAME": "allow_web", "ACTION": "permit"},
                        {"NAME": "deny_all", "ACTION": "deny"}],
                       platform="paloalto_panos")
        vb.build_one_view(conn, "firewall_rules")
        rows = conn.execute(
            "SELECT rule_name FROM netops.v_firewall_rules_auto"
        ).fetchall()
        assert rows == [("allow_web",)]


# ──────────────────────────────────────────────────────────────────────────
# Vendor filter end-to-end
# ──────────────────────────────────────────────────────────────────────────

class TestVendorFilter:
    def test_recipe_only_applies_to_matching_vendor(self, conn):
        # Cisco recipe + Cisco device + Junos device; only Cisco rows emerge
        _insert_recipe(conn, command="show bgp summary", concept="bgp_neighbors",
                       vendor_hint="cisco_ios",
                       field_mappings={"neighbor_ip": "neighbor_ip",
                                       "neighbor_as": "neighbor_as",
                                       "state": "state",
                                       "uptime": "uptime"})
        _insert_parsed(conn, "R2", "show bgp summary",
                       [{"neighbor_ip": "10.0.0.2", "neighbor_as": "65002",
                         "state": "Established", "uptime": "1d"}],
                       platform="cisco_ios")
        _insert_parsed(conn, "R1", "show bgp summary",
                       [{"neighbor_ip": "10.0.0.1", "neighbor_as": "65001",
                         "state": "Established", "uptime": "1d"}],
                       platform="juniper_junos")
        vb.build_one_view(conn, "bgp_neighbors")
        devs = conn.execute(
            "SELECT DISTINCT device FROM netops.v_bgp_neighbors_auto"
        ).fetchall()
        assert devs == [("R2",)]


# ──────────────────────────────────────────────────────────────────────────
# build_all_views
# ──────────────────────────────────────────────────────────────────────────

class TestBuildAllViews:
    def test_multiple_concepts_built(self, conn):
        # BGP recipe
        _insert_recipe(conn, command="show bgp summary", concept="bgp_neighbors",
                       vendor_hint="cisco_ios",
                       field_mappings={"neighbor_ip": "neighbor_ip",
                                       "neighbor_as": "neighbor_as",
                                       "state": "state", "uptime": "uptime"})
        # L2 recipe
        _insert_recipe(conn, command="@topology_links", concept="topology_l2",
                       vendor_hint="universal", field_mappings={})
        _insert_parsed(conn, "R1", "show bgp summary",
                       [{"neighbor_ip": "10.0.0.1", "neighbor_as": "65001",
                         "state": "Established", "uptime": "1d"}])
        conn.execute(
            "INSERT INTO netops.topology_links VALUES "
            "('R1', 'Gi0/0', 'R2', 'Gi0/0', 'LLDP', 'up', 'snap-1')"
        )
        result = vb.build_all_views(conn)
        assert "v_bgp_neighbors_auto" in result
        assert "v_l2_links_auto" in result
        assert result["v_bgp_neighbors_auto"] >= 1
        assert result["v_l2_links_auto"] == 1

    def test_empty_recipes_returns_empty(self, conn):
        assert vb.build_all_views(conn) == {}

    def test_missing_view_recipes_table_returns_empty(self, conn):
        conn.execute("DROP TABLE view_recipes")
        assert vb.build_all_views(conn) == {}


# ──────────────────────────────────────────────────────────────────────────
# rebuild_views_for_command
# ──────────────────────────────────────────────────────────────────────────

class TestRebuildViewsForCommand:
    def test_only_matching_concepts_rebuilt(self, conn):
        _insert_recipe(conn, command="show bgp summary", concept="bgp_neighbors",
                       vendor_hint="cisco_ios",
                       field_mappings={"neighbor_ip": "neighbor_ip",
                                       "neighbor_as": "neighbor_as",
                                       "state": "state", "uptime": "uptime"})
        _insert_recipe(conn, command="show ip ospf neighbor",
                       concept="ospf_neighbors", vendor_hint="cisco_ios",
                       field_mappings={"neighbor_id": "neighbor_id",
                                       "neighbor_ip": "address",
                                       "interface": "interface",
                                       "state": "state",
                                       "dead_time": "dead_time"})
        _insert_parsed(conn, "R1", "show bgp summary",
                       [{"neighbor_ip": "10.0.0.1", "neighbor_as": "65001",
                         "state": "Established", "uptime": "1d"}])
        result = vb.rebuild_views_for_command(conn, "show bgp summary")
        assert "v_bgp_neighbors_auto" in result
        assert "v_ospf_neighbors_auto" not in result

    def test_unknown_command_returns_empty(self, conn):
        assert vb.rebuild_views_for_command(conn, "show nonexistent") == {}


# ──────────────────────────────────────────────────────────────────────────
# ensure_view_recipes_table
# ──────────────────────────────────────────────────────────────────────────

class TestEnsureViewRecipesTable:
    def test_creates_on_cold_db(self):
        c = duckdb.connect(":memory:")
        try:
            vb.ensure_view_recipes_table(c)
            cols = [r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'view_recipes'"
            ).fetchall()]
            assert set(["command", "concept", "vendor_hint",
                        "field_mappings", "filter_expr", "discovered_at"]).issubset(cols)
        finally:
            c.close()

    def test_idempotent(self):
        c = duckdb.connect(":memory:")
        try:
            vb.ensure_view_recipes_table(c)
            vb.ensure_view_recipes_table(c)  # must not raise
        finally:
            c.close()


# ──────────────────────────────────────────────────────────────────────────
# _generate_sql_branch dispatch
# ──────────────────────────────────────────────────────────────────────────

class TestGenerateSqlBranch:
    def test_dispatches_bgp(self):
        sql = vb._generate_sql_branch(
            {"command": "show bgp summary", "vendor_hint": "cisco_ios",
             "field_mappings": {"neighbor_ip": "neighbor_ip",
                                "neighbor_as": "neighbor_as",
                                "state": "state", "uptime": "uptime"},
             "filter_expr": None},
            "bgp_neighbors",
        )
        assert "netops.parsed_outputs" in sql
        assert "neighbor_ip" in sql

    def test_dispatches_l2(self):
        sql = vb._generate_sql_branch(
            {"command": "@topology_links", "vendor_hint": "universal",
             "field_mappings": {}, "filter_expr": None},
            "topology_l2",
        )
        assert "netops.topology_links" in sql

    def test_falls_through_to_custom_for_unknown_concept(self):
        sql = vb._generate_sql_branch(
            {"command": "show security policy", "vendor_hint": "paloalto_panos",
             "field_mappings": {"rule": "NAME"}, "filter_expr": None},
            "firewall_rules",
        )
        # Custom branch emits parsed_outputs project with the canonical column
        assert "netops.parsed_outputs" in sql
        assert "rule" in sql
