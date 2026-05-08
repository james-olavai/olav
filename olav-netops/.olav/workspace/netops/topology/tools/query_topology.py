"""query_topology — ARCH-28 agent tool.

Query the ARCH-28 Path B views (`v_bgp_neighbors_auto`,
`v_ospf_neighbors_auto`, `v_l2_links_auto`) and return a typed
``TopologySnapshot`` Pydantic model. Used by the ops orchestrator and
ops-analyze sub-agent.

The views are built at snapshot time (Stage 3.7 in netops_init) so this
tool does **zero ETL work on invocation** — just SELECT + Pydantic
validate. State values are canonical (``Established`` for BGP,
``Full``/``FULL/DR``/``FULL/BDR`` for OSPF per vendor).
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import tool

from olav_netops.schemas import (
    BGPSession,
    L2Link,
    OSPFAdjacency,
    TopologySnapshot,
)


def _latest_snapshot(con: Any) -> str | None:
    """Return the most recent snapshot_id present in any view."""
    for view in ("v_bgp_neighbors_auto", "v_l2_links_auto"):
        try:
            row = con.execute(
                f"SELECT snapshot_id FROM netops.{view} "
                "ORDER BY snapshot_id DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            continue
    return None


def _fetch_bgp(con: Any, snapshot_id: str) -> list[BGPSession]:
    rows = con.execute(
        "SELECT device, neighbor_ip, neighbor_as, local_as, router_id, "
        "state, uptime FROM netops.v_bgp_neighbors_auto "
        "WHERE snapshot_id = ? ORDER BY device, neighbor_ip",
        [snapshot_id],
    ).fetchall()
    return [
        BGPSession(
            device=r[0],
            neighbor_ip=r[1],
            neighbor_as=r[2],
            local_as=r[3],
            router_id=r[4],
            state=r[5],
            uptime=r[6],
        )
        for r in rows
    ]


def _fetch_ospf(con: Any, snapshot_id: str) -> list[OSPFAdjacency]:
    rows = con.execute(
        "SELECT device, neighbor_id, neighbor_ip, interface, area, "
        "state, dead_time FROM netops.v_ospf_neighbors_auto "
        "WHERE snapshot_id = ? ORDER BY device, neighbor_id",
        [snapshot_id],
    ).fetchall()
    return [
        OSPFAdjacency(
            device=r[0],
            neighbor_id=r[1],
            neighbor_ip=r[2],
            interface=r[3],
            area=r[4],
            state=r[5],
            dead_time=r[6],
        )
        for r in rows
    ]


def _fetch_l2(con: Any, snapshot_id: str) -> list[L2Link]:
    rows = con.execute(
        "SELECT source_device, source_interface, destination_device, "
        "destination_interface, discovery_protocol, link_status "
        "FROM netops.v_l2_links_auto "
        "WHERE snapshot_id = ? "
        "ORDER BY source_device, source_interface",
        [snapshot_id],
    ).fetchall()
    return [
        L2Link(
            source_device=r[0],
            source_interface=r[1],
            destination_device=r[2],
            destination_interface=r[3],
            discovery_protocol=r[4],
            link_status=r[5],
        )
        for r in rows
    ]


@tool
def query_topology(
    concept: Literal["bgp", "ospf", "l2", "all"] = "all",
    snapshot_id: str | None = None,
) -> dict:
    """Query network topology via ARCH-28 views + Pydantic schema.

    Args:
        concept: Which layer to return. ``"all"`` includes BGP + OSPF + L2.
        snapshot_id: Specific snapshot to query. ``None`` = latest.

    Returns:
        JSON-serializable dict matching ``TopologySnapshot``. State values
        are canonical ('Established' for BGP; 'Full' / 'FULL/DR' etc.
        for OSPF). Interface names keep their vendor canonical form
        (Junos ``ge-0/0/2.0``, Cisco ``Ethernet0/0``).
    """
    import duckdb
    from olav.core.config import MAIN_DB_PATH

    con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    try:
        snap = snapshot_id or _latest_snapshot(con)
        if snap is None:
            return TopologySnapshot(snapshot_id="none").model_dump()

        bgp: list[BGPSession] = []
        ospf: list[OSPFAdjacency] = []
        l2: list[L2Link] = []

        if concept in ("bgp", "all"):
            bgp = _fetch_bgp(con, snap)
        if concept in ("ospf", "all"):
            ospf = _fetch_ospf(con, snap)
        if concept in ("l2", "all"):
            l2 = _fetch_l2(con, snap)

        return TopologySnapshot(
            snapshot_id=snap,
            bgp_sessions=bgp,
            ospf_adjacencies=ospf,
            l2_links=l2,
        ).model_dump(mode="json")
    finally:
        con.close()
