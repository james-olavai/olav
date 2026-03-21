import logging
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)


class NetworkSimulator:
    def __init__(self, db_path: str | None = None, conn=None):
        self.db_path = db_path
        self.conn = conn
        self._topology = None

    def load_topology(self) -> dict[str, list[dict[str, Any]]]:
        if self._topology:
            return self._topology

        self._topology = {
            "nodes": [],
            "links": [],
        }

        try:
            # Use provided connection or open new one
            if self.conn:
                conn = self.conn
                close_after = False
            elif self.db_path:
                import duckdb

                conn = duckdb.connect(str(self.db_path), read_only=True)
                close_after = True
            else:
                logger.warning("No database connection or path provided")
                return self._topology

            nodes = conn.execute("SELECT name, mgmt_ip, platform FROM devices").fetchall()
            self._topology["nodes"] = [{"name": n[0], "ip": n[1], "platform": n[2]} for n in nodes]

            links = []
            if self._has_table(conn, "topology_links"):
                link_cols = self._table_columns(conn, "topology_links")
                has_source_iface = "source_interface" in link_cols
                has_dest_iface = "destination_interface" in link_cols
                has_protocol = "discovery_protocol" in link_cols

                if has_source_iface and has_dest_iface and has_protocol:
                    links = conn.execute(
                        "SELECT source_device, destination_device, source_interface, destination_interface, discovery_protocol "
                        "FROM topology_links"
                    ).fetchall()
                    self._topology["links"] = [
                        {
                            "source": link[0],
                            "target": link[1],
                            "source_interface": link[2],
                            "destination_interface": link[3],
                            "discovery_protocol": link[4],
                        }
                        for link in links
                    ]
                else:
                    links = conn.execute(
                        "SELECT source_device, destination_device FROM topology_links"
                    ).fetchall()
                    self._topology["links"] = [
                        {"source": link[0], "target": link[1]} for link in links
                    ]

            if close_after:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to load topology from DB: {e}")

        return self._topology

    def _has_table(self, conn, table_name: str) -> bool:
        try:
            conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
            return True
        except Exception:
            return False

    def _table_columns(self, conn, table_name: str) -> set[str]:
        try:
            rows = conn.execute(f"DESCRIBE {table_name}").fetchall()
            return {str(r[0]) for r in rows}
        except Exception:
            return set()

    def _edge_taxonomy(self, protocol: str | None, link_type: str | None) -> str:
        p = (protocol or "").upper()
        t = (link_type or "").upper()
        if p in {"LLDP", "CDP"}:
            return "L2_DISCOVERY"
        if t in {"L3", "ROUTING"}:
            return "L3_ADJACENCY"
        if t:
            return f"LINK_{t}"
        return "GENERIC_LINK"

    def build_canonical_graph(self) -> nx.MultiDiGraph:
        """Build canonical MultiDiGraph from devices + topology_links.

        Contract:
        - node id: device name
        - node attrs: mgmt_ip, platform
        - edge attrs: discovery_protocol/link_type + taxonomy
        """
        graph = nx.MultiDiGraph()

        try:
            if self.conn:
                conn = self.conn
                close_after = False
            elif self.db_path:
                import duckdb

                conn = duckdb.connect(str(self.db_path), read_only=True)
                close_after = True
            else:
                return graph

            if self._has_table(conn, "devices"):
                for name, mgmt_ip, platform in conn.execute(
                    "SELECT name, mgmt_ip, platform FROM devices"
                ).fetchall():
                    graph.add_node(str(name), mgmt_ip=mgmt_ip, platform=platform)

            if self._has_table(conn, "topology_links"):
                cols = self._table_columns(conn, "topology_links")
                if {"source_interface", "destination_interface", "discovery_protocol", "link_type"}.issubset(cols):
                    rows = conn.execute(
                        "SELECT source_device, destination_device, source_interface, destination_interface, discovery_protocol, link_type "
                        "FROM topology_links"
                    ).fetchall()
                    for src, dst, src_if, dst_if, proto, ltype in rows:
                        graph.add_edge(
                            str(src),
                            str(dst),
                            source_interface=src_if,
                            destination_interface=dst_if,
                            discovery_protocol=proto,
                            link_type=ltype,
                            edge_taxonomy=self._edge_taxonomy(str(proto) if proto else None, str(ltype) if ltype else None),
                        )
                else:
                    rows = conn.execute(
                        "SELECT source_device, destination_device FROM topology_links"
                    ).fetchall()
                    for src, dst in rows:
                        graph.add_edge(
                            str(src),
                            str(dst),
                            edge_taxonomy="GENERIC_LINK",
                        )

            if close_after:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to build canonical graph from DB: {e}")

        return graph

    def build_graph_projection(self) -> dict[str, Any]:
        """Return a stable summary projection from the canonical graph.

        Projection contract (Phase 2 baseline):
        - node_count / edge_count
        - per-taxonomy edge counters
        """
        graph = self.build_canonical_graph()
        taxonomy_counts: dict[str, int] = {}
        for _src, _dst, attrs in graph.edges(data=True):
            taxonomy = str(attrs.get("edge_taxonomy", "GENERIC_LINK"))
            taxonomy_counts[taxonomy] = taxonomy_counts.get(taxonomy, 0) + 1

        return {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "edge_taxonomy_counts": taxonomy_counts,
        }

    def simulate_change(self, device: str, config_delta: dict[str, Any]) -> dict[str, Any]:
        graph = self.build_canonical_graph()
        affected_set: set[str] = {device}
        if graph.has_node(device):
            affected_set.update(str(n) for n in graph.successors(device))
            affected_set.update(str(n) for n in graph.predecessors(device))
        affected = sorted(affected_set)

        return {
            "simulated": True,
            "device": device,
            "changes": config_delta,
            "affected_devices": affected,
            "impact_level": "high" if len(affected) > 3 else "medium",
        }

    def analyze_impact(self, changes: list[dict[str, Any]]) -> dict[str, Any]:
        affected = set()

        for change in changes:
            sim_result = self.simulate_change(change["device"], change)
            affected.update(sim_result["affected_devices"])

        return {
            "total_affected": len(affected),
            "affected_devices": list(affected),
            "risk_level": "high" if len(affected) > 5 else "low",
        }


def simulate_config_change(device: str, config: dict[str, Any]) -> dict[str, Any]:
    simulator = NetworkSimulator()
    return simulator.simulate_change(device, config)
