from __future__ import annotations

from typing import Any, cast

import duckdb

from olav.core.simulation.engine import NetworkSimulator


def _seed(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE devices (
            name TEXT,
            mgmt_ip TEXT,
            platform TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO devices VALUES (?, ?, ?)",
        [
            ("R1", "10.0.0.1", "cisco_ios"),
            ("R2", "10.0.0.2", "cisco_ios"),
            ("SW1", "10.0.0.11", "arista_eos"),
        ],
    )

    con.execute(
        """
        CREATE TABLE topology_links (
            source_device TEXT,
            destination_device TEXT,
            source_interface TEXT,
            destination_interface TEXT,
            discovery_protocol TEXT,
            link_type TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO topology_links VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("R1", "R2", "Eth0/0", "Eth0/1", "LLDP", "L2"),
            ("R2", "SW1", "Eth0/2", "Eth1", "CDP", "L2"),
        ],
    )


def test_build_canonical_graph_nodes_and_attrs() -> None:
    con = duckdb.connect(":memory:")
    _seed(con)
    sim = NetworkSimulator(conn=con)

    g = cast(Any, sim.build_canonical_graph())  # pyright: ignore[reportUnknownMemberType]
    node_attrs = cast(dict[str, Any], g.nodes["R1"])

    assert g.number_of_nodes() == 3
    assert g.has_node("R1")
    assert node_attrs["mgmt_ip"] == "10.0.0.1"
    assert node_attrs["platform"] == "cisco_ios"



def test_build_canonical_graph_edge_taxonomy() -> None:
    con = duckdb.connect(":memory:")
    _seed(con)
    sim = NetworkSimulator(conn=con)

    g = cast(Any, sim.build_canonical_graph())  # pyright: ignore[reportUnknownMemberType]

    assert g.number_of_edges() == 2
    edge_data = g.get_edge_data("R1", "R2")
    assert edge_data is not None
    first_edge = cast(dict[str, Any], next(iter(edge_data.values())))
    assert first_edge["discovery_protocol"] == "LLDP"
    assert first_edge["edge_taxonomy"] == "L2_DISCOVERY"


def test_build_graph_projection_counts() -> None:
    con = duckdb.connect(":memory:")
    _seed(con)
    sim = NetworkSimulator(conn=con)

    projection = cast(dict[str, Any], sim.build_graph_projection())

    assert projection["node_count"] == 3
    assert projection["edge_count"] == 2
    taxonomy_counts = cast(dict[str, int], projection["edge_taxonomy_counts"])
    assert taxonomy_counts.get("L2_DISCOVERY") == 2



def test_simulate_change_uses_topology_neighbors() -> None:
    con = duckdb.connect(":memory:")
    _seed(con)
    sim = NetworkSimulator(conn=con)

    result = sim.simulate_change("R2", {"cmd": "shutdown"})
    affected = cast(list[str], result["affected_devices"])

    assert result["simulated"] is True
    assert set(affected) == {"R2", "R1", "SW1"}
