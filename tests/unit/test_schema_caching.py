"""Tests for schema mapping cache (OC-6).

TDD cycle: cached lookups bypass LLM, cache miss falls through.
"""

import pytest


class TestSchemaCacheImport:
    def test_import_cache(self):
        from olav.core.schema_cache import SchemaCache

        assert SchemaCache is not None

    def test_import_helpers(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        assert hasattr(cache, "get")
        assert hasattr(cache, "put")
        assert hasattr(cache, "has")


class TestSchemaCacheBasicOps:
    def test_put_and_get(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        cache.put("show interfaces", "Mtu", "openconfig-interfaces:interfaces/interface/state/mtu")
        result = cache.get("show interfaces", "Mtu")
        assert result == "openconfig-interfaces:interfaces/interface/state/mtu"

    def test_get_miss_returns_none(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        assert cache.get("show interfaces", "NonExistent") is None

    def test_has_true(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        cache.put("show ip bgp", "peer_as", "openconfig-bgp:bgp/neighbors/neighbor/state/peer-as")
        assert cache.has("show ip bgp", "peer_as") is True

    def test_has_false(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        assert cache.has("show ip bgp", "peer_as") is False

    def test_overwrite(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        cache.put("cmd", "key", "path_a")
        cache.put("cmd", "key", "path_b")
        assert cache.get("cmd", "key") == "path_b"


class TestSchemaCacheBulk:
    def test_get_all_for_command(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        cache.put("show interfaces", "Mtu", "oc_mtu")
        cache.put("show interfaces", "Status", "oc_status")
        cache.put("show ip bgp", "peer_as", "oc_peer_as")

        result = cache.get_all("show interfaces")
        assert len(result) == 2
        assert result["Mtu"] == "oc_mtu"
        assert result["Status"] == "oc_status"

    def test_get_all_empty(self):
        from olav.core.schema_cache import SchemaCache

        cache = SchemaCache()
        assert cache.get_all("show interfaces") == {}


class TestSchemaCachePersistence:
    def test_load_from_duckdb(self, tmp_path):
        import duckdb
        import json

        from olav.core.schema_cache import SchemaCache

        db_path = str(tmp_path / "test.duckdb")
        conn = duckdb.connect(db_path)
        conn.execute(
            "CREATE TABLE schema_catalog ("
            "  source_type TEXT, source_name TEXT, platform TEXT, fields TEXT, "
            "  description TEXT, updated_at TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO schema_catalog VALUES (?,?,?,?,?,?)",
            [
                "textfsm",
                "show interfaces",
                "cisco_ios",
                json.dumps(
                    [
                        {
                            "name": "Mtu",
                            "openconfig_path": "openconfig-interfaces:interfaces/interface/state/mtu",
                        }
                    ]
                ),
                "",
                None,
            ],
        )
        conn.close()

        cache = SchemaCache.from_duckdb(db_path)
        assert (
            cache.get("show interfaces", "Mtu")
            == "openconfig-interfaces:interfaces/interface/state/mtu"
        )

    def test_load_from_empty_db(self, tmp_path):
        import duckdb

        from olav.core.schema_cache import SchemaCache

        db_path = str(tmp_path / "empty.duckdb")
        conn = duckdb.connect(db_path)
        conn.close()

        with pytest.raises(ValueError, match="schema_catalog table is required"):
            SchemaCache.from_duckdb(db_path)
