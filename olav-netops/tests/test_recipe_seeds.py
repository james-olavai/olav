"""Unit tests for olav_netops.core.recipe_seeds (R70 changes).

Covers the loosened concept validator:
  * builtin concepts still accepted
  * user-defined concepts (firewall_rules, bfd_sessions, ...) accepted with INFO log
  * invalid concept format rejected
  * @-prefixed directive commands allow empty field_mappings
"""
from __future__ import annotations

import json

import duckdb
import pytest

from olav_netops.core import recipe_seeds as rs


# ──────────────────────────────────────────────────────────────────────────
# _validate_entry
# ──────────────────────────────────────────────────────────────────────────

class TestValidateEntry:
    def test_builtin_concept_accepted(self):
        rs._validate_entry({
            "command": "show bgp summary",
            "concept": "bgp_neighbors",
            "field_mappings": {"neighbor_ip": "ip"},
        }, 0)

    def test_user_defined_concept_accepted(self, caplog):
        """R70: user concept loads, but an INFO log marks it as non-builtin."""
        import logging
        with caplog.at_level(logging.INFO, logger="olav_netops.core.recipe_seeds"):
            rs._validate_entry({
                "command": "show security policy",
                "concept": "firewall_rules",
                "field_mappings": {"rule": "name"},
            }, 0)
        assert any("user-defined concept" in r.message for r in caplog.records)

    def test_invalid_concept_format_rejected(self):
        with pytest.raises(ValueError, match="invalid concept"):
            rs._validate_entry({
                "command": "show x",
                "concept": "Bad-Concept!",
                "field_mappings": {"a": "b"},
            }, 0)

    def test_empty_concept_rejected(self):
        with pytest.raises(ValueError, match="invalid concept"):
            rs._validate_entry({
                "command": "show x",
                "concept": "",
                "field_mappings": {"a": "b"},
            }, 0)

    def test_uppercase_concept_rejected(self):
        # Convention: must start lowercase to match [a-z][a-z0-9_]*
        with pytest.raises(ValueError, match="invalid concept"):
            rs._validate_entry({
                "command": "show x",
                "concept": "Uppercase",
                "field_mappings": {"a": "b"},
            }, 0)

    def test_missing_required_field(self):
        with pytest.raises(ValueError, match="missing required fields"):
            rs._validate_entry({
                "concept": "bgp_neighbors",
                "field_mappings": {"a": "b"},
            }, 0)

    def test_at_directive_allows_empty_mappings(self):
        """Commands starting with '@' are directive sentinels — projection
        from a table not from parsed_outputs — so empty field_mappings is legal."""
        rs._validate_entry({
            "command": "@topology_links",
            "concept": "topology_l2",
            "field_mappings": {},
        }, 0)

    def test_non_at_directive_empty_mappings_rejected(self):
        with pytest.raises(ValueError, match="empty field_mappings"):
            rs._validate_entry({
                "command": "show bgp summary",
                "concept": "bgp_neighbors",
                "field_mappings": {},
            }, 0)


# ──────────────────────────────────────────────────────────────────────────
# load_recipe_seeds — end-to-end YAML → DuckDB UPSERT
# ──────────────────────────────────────────────────────────────────────────

class TestLoadRecipeSeeds:
    @pytest.fixture
    def conn(self):
        c = duckdb.connect(":memory:")
        yield c
        c.close()

    def test_single_file_upserts(self, conn, tmp_path):
        p = tmp_path / "bgp_cisco_ios.yaml"
        p.write_text(
            "- command: show bgp summary\n"
            "  concept: bgp_neighbors\n"
            "  vendor_hint: cisco_ios\n"
            "  field_mappings:\n"
            "    neighbor_ip: neighbor_ip\n"
        )
        stats = rs.load_recipe_seeds(conn, seed_path=p, include_user=False)
        assert stats["inserted_or_updated"] == 1
        row = conn.execute(
            "SELECT command, concept, vendor_hint FROM view_recipes"
        ).fetchone()
        assert row == ("show bgp summary", "bgp_neighbors", "cisco_ios")

    def test_upsert_is_idempotent(self, conn, tmp_path):
        p = tmp_path / "bgp.yaml"
        p.write_text(
            "- command: show bgp summary\n"
            "  concept: bgp_neighbors\n"
            "  vendor_hint: cisco_ios\n"
            "  field_mappings:\n"
            "    neighbor_ip: neighbor_ip\n"
        )
        rs.load_recipe_seeds(conn, seed_path=p, include_user=False)
        rs.load_recipe_seeds(conn, seed_path=p, include_user=False)
        count = conn.execute("SELECT COUNT(*) FROM view_recipes").fetchone()[0]
        assert count == 1

    def test_directory_glob(self, conn, tmp_path):
        (tmp_path / "a.yaml").write_text(
            "- command: show bgp summary\n  concept: bgp_neighbors\n"
            "  vendor_hint: cisco_ios\n  field_mappings: {neighbor_ip: ip}\n"
        )
        (tmp_path / "b.yaml").write_text(
            "- command: show ospf neighbor\n  concept: ospf_neighbors\n"
            "  vendor_hint: cisco_ios\n  field_mappings: {neighbor_id: id}\n"
        )
        stats = rs.load_recipe_seeds(conn, seed_path=tmp_path, include_user=False)
        assert stats["inserted_or_updated"] == 2

    def test_user_defined_concept_loaded(self, conn, tmp_path):
        p = tmp_path / "fw.yaml"
        p.write_text(
            "- command: show security policy\n"
            "  concept: firewall_rules\n"
            "  vendor_hint: paloalto_panos\n"
            "  field_mappings: {rule_name: name}\n"
        )
        stats = rs.load_recipe_seeds(conn, seed_path=p, include_user=False)
        assert stats["inserted_or_updated"] == 1
        row = conn.execute(
            "SELECT concept, vendor_hint, field_mappings FROM view_recipes"
        ).fetchone()
        assert row[0] == "firewall_rules"
        assert row[1] == "paloalto_panos"
        assert json.loads(row[2]) == {"rule_name": "name"}

    def test_invalid_entry_skipped_not_fatal(self, conn, tmp_path):
        """A bad entry in a multi-entry file must not abort the whole file."""
        p = tmp_path / "mixed.yaml"
        p.write_text(
            "- command: show x\n"
            "  concept: Invalid-Concept\n"  # bad format — skipped
            "  field_mappings: {a: b}\n"
            "- command: show bgp summary\n"
            "  concept: bgp_neighbors\n"
            "  vendor_hint: cisco_ios\n"
            "  field_mappings: {neighbor_ip: ip}\n"
        )
        stats = rs.load_recipe_seeds(conn, seed_path=p, include_user=False)
        assert stats["inserted_or_updated"] == 1

    def test_vendor_hint_defaults_to_universal(self, conn, tmp_path):
        p = tmp_path / "u.yaml"
        p.write_text(
            "- command: '@topology_links'\n"
            "  concept: topology_l2\n"
            "  field_mappings: {}\n"
        )
        rs.load_recipe_seeds(conn, seed_path=p, include_user=False)
        row = conn.execute("SELECT vendor_hint FROM view_recipes").fetchone()
        assert row[0] == "universal"

    def test_missing_sources_returns_zero(self, conn, tmp_path, monkeypatch):
        monkeypatch.setattr(rs, "_builtin_recipes_dir", lambda: tmp_path / "nope")
        monkeypatch.setattr(rs, "_user_recipes_dir", lambda: tmp_path / "also_nope")
        stats = rs.load_recipe_seeds(conn)
        assert stats["total"] == 0
        assert stats["inserted_or_updated"] == 0
