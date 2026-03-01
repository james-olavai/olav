"""Test Network Topology Analysis using DuckPGQ."""

import pytest


class TestDuckPGQ:
    def test_duckpgq_loads(self):
        import duckdb

        conn = duckdb.connect()
        conn.execute("LOAD duckpgq")
        conn.close()


class TestTopologyAnalysis:
    @pytest.fixture
    def topology(self):
        return [
            {"device": "R1", "neighbor": "R2"},
            {"device": "R2", "neighbor": "R1"},
            {"device": "R2", "neighbor": "R3"},
            {"device": "R3", "neighbor": "R2"},
        ]

    def test_find_path(self, topology):
        from src.olav.core.memory.topology import analyze_network_topology

        result = analyze_network_topology(topology, intent="path", source="R1", destination="R3")
        assert result["status"] == "success"
        assert result["path"] is not None

    def test_no_path(self, topology):
        from src.olav.core.memory.topology import analyze_network_topology

        result = analyze_network_topology(topology, intent="path", source="R1", destination="R4")
        assert result["status"] == "success"
        assert result["path"] is None

    def test_loop_detection(self, topology):
        from src.olav.core.memory.topology import analyze_network_topology

        result = analyze_network_topology(topology, intent="loop_detection")
        assert result["status"] == "success"

    def test_connectivity(self, topology):
        from src.olav.core.memory.topology import analyze_network_topology

        result = analyze_network_topology(topology, intent="connectivity", source="R2")
        assert result["status"] == "success"
        assert result["connection_count"] == 2
