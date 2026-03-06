import logging
from typing import Any

logger = logging.getLogger(__name__)


class NetworkSimulator:
    def __init__(self, db_path: str | None = None, conn=None):
        self.db_path = db_path
        self.conn = conn
        self._topology = None

    def load_topology(self) -> dict:
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

            links = (
                conn.execute(
                    "SELECT source_device, destination_device FROM topology_links"
                ).fetchall()
                if self._has_table(conn, "topology_links")
                else []
            )
            self._topology["links"] = [{"source": link[0], "target": link[1]} for link in links]

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

    def simulate_change(self, device: str, config_delta: dict) -> dict:
        topology = self.load_topology()

        affected = [device]

        for link in topology.get("links", []):
            if link["source"] == device:
                affected.append(link["target"])
            elif link["target"] == device:
                affected.append(link["source"])

        return {
            "simulated": True,
            "device": device,
            "changes": config_delta,
            "affected_devices": affected,
            "impact_level": "high" if len(affected) > 3 else "medium",
        }

    def analyze_impact(self, changes: list[dict]) -> dict:
        affected = set()

        for change in changes:
            sim_result = self.simulate_change(change["device"], change)
            affected.update(sim_result["affected_devices"])

        return {
            "total_affected": len(affected),
            "affected_devices": list(affected),
            "risk_level": "high" if len(affected) > 5 else "low",
        }


def simulate_config_change(device: str, config: dict) -> dict:
    simulator = NetworkSimulator()
    return simulator.simulate_change(device, config)
