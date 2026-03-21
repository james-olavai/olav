"""SR Linux OpenConfig exporter — DuckDB → gNMI Set (OC-9).

Reads OpenConfig-structured data from DuckDB ``parsed_outputs`` and
pushes it to SR Linux ContainerLab nodes via gNMI ``Set`` operations.

Usage::

    exporter = SrlExporter(
        target=("clab-srl1", 57400),
        username="admin",
        password="NokiaSrl1!",
    )
    results = exporter.export_interfaces(oc_interface_list)

Convenience function::

    export_to_srlinux(
        db_path=".olav/databases/main.duckdb",
        target=("clab-srl1", 57400),
        username="admin",
        password="NokiaSrl1!",
    )
"""

from __future__ import annotations

import logging
from typing import Any

import duckdb

from olav.services.gnmi_collector import GnmiCollector

logger = logging.getLogger(__name__)


class SrlExporter:
    """Push OpenConfig JSON to SR Linux devices via gNMI Set.

    Parameters
    ----------
    target:
        ``(host, port)`` tuple for the gNMI target.
    username:
        gNMI authentication username.
    password:
        gNMI authentication password.
    vendor:
        Vendor name, defaults to ``"srlinux"``.
    insecure:
        Skip TLS verification (common for ContainerLab).
    dry_run:
        If ``True``, build payloads but skip actual gNMI Set calls.
    """

    def __init__(
        self,
        target: tuple[str, int],
        username: str,
        password: str,
        vendor: str = "srlinux",
        insecure: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.target = target
        self.username = username
        self.password = password
        self.vendor = vendor
        self.insecure = insecure
        self.dry_run = dry_run

        self._collector = GnmiCollector(
            target=target,
            username=username,
            password=password,
            vendor=vendor,
            insecure=insecure,
        )

    # ------------------------------------------------------------------
    # Interface export
    # ------------------------------------------------------------------

    def export_interfaces(self, oc_interfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Export OpenConfig interface data via gNMI Set.

        Parameters
        ----------
        oc_interfaces:
            List of OpenConfig interface dicts (matching ``Interface`` model).

        Returns
        -------
        list[dict]:
            One result dict per interface — ``{"interface": name, "status": ...}``.
        """
        results: list[dict[str, Any]] = []
        for iface in oc_interfaces:
            iface_name = iface.get("name", "")
            state = iface.get("state", {})

            # Build config payload from state (strip read-only fields)
            config: dict[str, Any] = {}
            if "admin-status" in state:
                config["enabled"] = state["admin-status"].upper() == "UP"
            if "mtu" in state:
                config["mtu"] = state["mtu"]
            if "description" in state:
                config["description"] = state["description"]

            path = f"openconfig-interfaces:interfaces/interface[name={iface_name}]/config"

            if self.dry_run:
                logger.info("DRY-RUN: would set %s → %s", path, config)
                results.append({"interface": iface_name, "status": "dry-run", "config": config})
            else:
                resp = self._collector.set_config(path, config)
                results.append(
                    {
                        "interface": iface_name,
                        "status": "ok" if resp else "failed",
                        "response": resp,
                    }
                )

        return results

    # ------------------------------------------------------------------
    # BGP export
    # ------------------------------------------------------------------

    def export_bgp_neighbors(self, oc_neighbors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Export OpenConfig BGP neighbor config via gNMI Set.

        Parameters
        ----------
        oc_neighbors:
            List of OpenConfig BGP neighbor dicts (matching ``BgpNeighbor``).

        Returns
        -------
        list[dict]:
            One result per neighbor.
        """
        results: list[dict[str, Any]] = []
        for nbr in oc_neighbors:
            nbr_addr = nbr.get("neighbor-address", "")
            state = nbr.get("state", {})

            config: dict[str, Any] = {"neighbor-address": nbr_addr}
            if "peer-as" in state:
                config["peer-as"] = state["peer-as"]

            path = f"openconfig-bgp:bgp/neighbors/neighbor[neighbor-address={nbr_addr}]/config"

            if self.dry_run:
                logger.info("DRY-RUN: would set %s → %s", path, config)
                results.append({"neighbor": nbr_addr, "status": "dry-run", "config": config})
            else:
                resp = self._collector.set_config(path, config)
                results.append(
                    {"neighbor": nbr_addr, "status": "ok" if resp else "failed", "response": resp}
                )

        return results


# ---------------------------------------------------------------------------
# Convenience function: load from DuckDB + export
# ---------------------------------------------------------------------------


def export_to_srlinux(
    db_path: str,
    target: tuple[str, int],
    username: str,
    password: str,
    dry_run: bool = False,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Load OpenConfig data from DuckDB and push to SR Linux via gNMI.

    Parameters
    ----------
    db_path:
        Path to DuckDB database.
    target:
        ``(host, port)`` tuple for the gNMI target.
    username:
        gNMI username.
    password:
        gNMI password.
    dry_run:
        If ``True``, skip actual gNMI calls.
    snapshot_id:
        Optional snapshot filter. Defaults to latest.

    Returns
    -------
    dict:
        Summary of export results per domain.
    """
    exporter = SrlExporter(
        target=target,
        username=username,
        password=password,
        dry_run=dry_run,
    )

    summary: dict[str, Any] = {"interfaces": [], "bgp": []}

    conn = duckdb.connect(db_path, read_only=True)
    try:
        # Build per-view snapshot filter — use provided snapshot_id or latest
        if snapshot_id:
            iface_snap_filter = f"snapshot_id = '{snapshot_id}'"
            bgp_snap_filter = f"snapshot_id = '{snapshot_id}'"
        else:
            iface_snap_filter = "snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces)"
            bgp_snap_filter = "snapshot_id = (SELECT MAX(snapshot_id) FROM v_bgp_neighbors)"

        # Read interface data from v_interfaces semantic view
        iface_rows = conn.execute(
            "SELECT device_name, interface, ip_address, admin_status, line_status, snapshot_id"
            f" FROM v_interfaces WHERE {iface_snap_filter}"
        ).fetchall()

        oc_interfaces: list[dict[str, Any]] = []
        for row in iface_rows:
            oc_interfaces.append(
                {
                    "name": row[1],  # interface
                    "state": {
                        "admin-status": row[3] or "",
                        "oper-status": row[4] or "",
                    },
                }
            )
        summary["interfaces"] = exporter.export_interfaces(oc_interfaces)

        # Read BGP data from v_bgp_neighbors semantic view
        bgp_rows = conn.execute(
            "SELECT device_name, neighbor_ip, neighbor_as, state, prefixes_received, snapshot_id"
            f" FROM v_bgp_neighbors WHERE {bgp_snap_filter}"
        ).fetchall()

        oc_neighbors: list[dict[str, Any]] = []
        for row in bgp_rows:
            oc_neighbors.append(
                {
                    "neighbor-address": row[1],
                    "state": {
                        "peer-as": row[2],
                        "session-state": row[3] or "",
                        "prefixes-received": row[4],
                    },
                }
            )
        summary["bgp"] = exporter.export_bgp_neighbors(oc_neighbors)

    finally:
        conn.close()

    return summary
