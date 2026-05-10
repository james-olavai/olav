"""query_topology — ARCH-28 agent tool.

Query the topology views (`v_bgp_neighbors_auto`,
`v_show_ip_ospf_neighbor_auto`, `v_l2_links_auto`) and return a typed
``TopologySnapshot`` Pydantic model. Used by the ops orchestrator and
ops-analyze sub-agent.

The views are built at snapshot time (Stage 3.7 in netops_init) so this
tool does **zero ETL work on invocation** — just SELECT + Pydantic
validate. State values are canonical (``Established`` for BGP,
``Full``/``FULL/DR``/``FULL/BDR`` for OSPF per vendor).

2026-05-10 schema-drift fix: BGP joins v_show_ip_bgp_summary_auto for
local_as/router_id; OSPF reads v_show_ip_ospf_neighbor_auto +
v_show_ip_ospf_interface_brief_auto for area. Old code referenced
``v_ospf_neighbors_auto`` which doesn't exist + column ``device``
which the BGP view exposes as ``device_name``.
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
    """Return the most recent snapshot_id that has L2 topology data.

    Why L2 instead of BGP: collection runs may produce partial
    snapshots (e.g., a re-run that only refreshed BGP summary). The
    "alphabetically latest" snapshot can therefore be thin — no L2,
    no OSPF, no BGP summary — and the LLM gets a sparse view that
    looks like the network is empty. Picking the latest snapshot
    that actually has L2 rows is a good proxy for "rich, complete
    collection" since L2 (LLDP/CDP) is the broadest data layer.

    2026-05-10 fix: original picked latest from any view, returned
    a thin snapshot on demo7 that hid all L2/OSPF data. Now scans
    L2 view first; falls back to BGP if no L2 snapshot exists.
    """
    try:
        row = con.execute(
            "SELECT snapshot_id FROM netops.v_l2_links_auto "
            "ORDER BY snapshot_id DESC LIMIT 1"
        ).fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    # Fallback: any view with rows
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
    """Fetch BGP sessions, joining v_bgp_neighbors_auto with the
    Cisco-style summary view to recover ``local_as`` / ``router_id``
    that aren't carried in v_bgp_neighbors_auto's schema.

    ARCH fix 2026-05-10: original SQL referenced columns
    (``device``, ``local_as``, ``router_id``, ``uptime``) that don't
    exist in v_bgp_neighbors_auto — column is ``device_name`` and the
    others live in v_show_ip_bgp_summary_auto. LEFT JOIN so neighbors
    on platforms without a summary row (Junos) still appear with
    ``local_as=None``.
    """
    rows = con.execute(
        "SELECT n.device_name, n.neighbor_ip, n.neighbor_as, "
        "       s.local_as, s.router_id, n.state, NULL AS uptime "
        "FROM netops.v_bgp_neighbors_auto n "
        "LEFT JOIN netops.v_show_ip_bgp_summary_auto s "
        "  ON n.device_name = s.device_name "
        " AND n.snapshot_id = s.snapshot_id "
        " AND n.neighbor_ip = s.bgp_neighbor "
        "WHERE n.snapshot_id = ? "
        "ORDER BY n.device_name, n.neighbor_ip",
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
    """Fetch OSPF adjacencies. ARCH fix 2026-05-10: original SQL
    referenced ``v_ospf_neighbors_auto`` which doesn't exist; the real
    view is ``v_show_ip_ospf_neighbor_auto``. Column ``area`` lives on
    a different view (``v_show_ip_ospf_interface_brief_auto``) and is
    joined by interface name; LEFT JOIN keeps the row when interface
    isn't matched (some vendor outputs lack the area column).
    """
    rows = con.execute(
        "SELECT n.device_name, n.neighbor_id, n.ip_address AS neighbor_ip, "
        "       n.interface, i.area, n.state, n.dead_time "
        "FROM netops.v_show_ip_ospf_neighbor_auto n "
        "LEFT JOIN netops.v_show_ip_ospf_interface_brief_auto i "
        "  ON n.device_name = i.device_name "
        " AND n.snapshot_id = i.snapshot_id "
        " AND n.interface   = i.interface "
        "WHERE n.snapshot_id = ? "
        "ORDER BY n.device_name, n.neighbor_id",
        [snapshot_id],
    ).fetchall()
    out: list[OSPFAdjacency] = []
    for r in rows:
        # Vendor casing varies (Cisco IOS prints "Full/DR" while the
        # OspfState literal expects "FULL/DR"). Normalize: if the
        # state contains "/" it's a composite form like "FULL/DR" —
        # uppercase the whole thing; otherwise it's a single word
        # like "Full" — title-case.
        state_raw = (r[5] or "").strip()
        state = state_raw.upper() if "/" in state_raw else state_raw.title()
        # 2-Way special: literal is "2-Way" (title-case form) not "2-WAY"
        if state.replace("-", "").upper() == "2WAY" and "/" not in state_raw:
            state = "2-Way"
        out.append(OSPFAdjacency(
            device=r[0],
            neighbor_id=r[1],
            neighbor_ip=r[2],
            interface=r[3],
            area=r[4],
            state=state,
            dead_time=r[6],
        ))
    return out


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
