"""Test Network Topology Analysis using NetworkX."""

import sys
from pathlib import Path

import pytest

# Resolve tool location without requiring package install
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / ".olav/workspace/ops/topology/tools"))
from topology import _build_graph, _find_path, _detect_loops, _get_connected


class TestTopologyAnalysis:
    @pytest.fixture
    def graph(self):
        topology = [
            {"device": "R1", "neighbor": "R2"},
            {"device": "R2", "neighbor": "R3"},
        ]
        return _build_graph(topology)

    def test_find_path(self, graph):
        result = _find_path(graph, source="R1", destination="R3")
        assert result["status"] == "success"
        assert result["path"] == ["R1", "R2", "R3"]

    def test_no_path(self, graph):
        # Node does not exist at all → error, not a silent "no path"
        result = _find_path(graph, source="R1", destination="R4")
        assert result["status"] == "error"
        assert "R4" in result["message"]

    def test_loop_detection(self):
        topo = [{"src": "R1", "dst": "R2"}, {"src": "R2", "dst": "R3"}, {"src": "R3", "dst": "R1"}]
        G = _build_graph(topo)
        result = _detect_loops(G)
        assert result["status"] == "success"
        assert result["loops_found"] == 1

    def test_connectivity(self, graph):
        result = _get_connected(graph, device="R2")
        assert result["status"] == "success"
        assert result["connection_count"] == 2
