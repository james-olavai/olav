import pytest


class TestNetworkSimulator:
    def test_simulator_import(self):
        from olav.core.simulation.engine import NetworkSimulator, simulate_config_change

        assert NetworkSimulator is not None
        assert simulate_config_change is not None

    def test_simulator_init(self):
        from olav.core.simulation.engine import NetworkSimulator

        sim = NetworkSimulator()
        assert sim.db_path is None

    def test_load_empty_topology(self):
        from olav.core.simulation.engine import NetworkSimulator

        sim = NetworkSimulator()
        topology = sim.load_topology()

        assert "nodes" in topology
        assert "links" in topology

    def test_simulate_change(self):
        from olav.core.simulation.engine import NetworkSimulator

        sim = NetworkSimulator()

        result = sim.simulate_change("R1", {"ospf": "enabled"})

        assert result["simulated"] is True
        assert result["device"] == "R1"
        assert "affected_devices" in result

    def test_analyze_impact(self):
        from olav.core.simulation.engine import NetworkSimulator

        sim = NetworkSimulator()

        changes = [
            {"device": "R1", "config": {}},
            {"device": "R2", "config": {}},
        ]

        result = sim.analyze_impact(changes)

        assert "total_affected" in result
        assert "risk_level" in result

    def test_execute_function(self):
        from olav.core.simulation.engine import simulate_config_change

        result = simulate_config_change("R1", {"bgp": "enabled"})

        assert result["simulated"] is True
        assert result["device"] == "R1"


class TestNetworkSimulatorIntegration:
    def test_multiple_devices_impact(self):
        from olav.core.simulation.engine import NetworkSimulator

        sim = NetworkSimulator()

        sim._topology = {
            "nodes": [{"name": "R1"}, {"name": "R2"}, {"name": "R3"}],
            "links": [
                {"source": "R1", "target": "R2"},
                {"source": "R2", "target": "R3"},
            ],
        }

        result = sim.simulate_change("R2", {"ospf": "disabled"})

        assert "R2" in result["affected_devices"]
        assert len(result["affected_devices"]) > 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
