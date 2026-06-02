"""incident_engine.py — Event-stream incident clustering + topology root-cause inference.

Algorithm
---------
1. Pull event stream from DuckDB across all state tables:
     interfaces (status != 'up'), bgp_neighbors (state != 'Established'),
     ospf_neighbors (state NOT IN FULL/2WAY), topology_links (status='down'),
     raw_diffs (any config change).

2. Sort all events by timestamp and apply sliding-window clustering:
     Events within `gap_minutes` of each other → same Incident Cluster.
     This is equivalent to single-linkage agglomerative clustering on 1-D time.

3. Per cluster, build a dependency graph from topology_links using networkx:
     - Add all affected devices as nodes.
     - Edges from topology_links (source → destination).
     - Root-cause candidate = node with no in-cluster predecessors AND
       the most downstream successors within the cluster.
     - If graph is disconnected → report all root candidates.

4. Return list of IncidentCluster dicts for map_engine to embed in output JSON:
     {
       "cluster_id":     "INC-001",
       "start_time":     "2026-03-04T03:42:00Z",
       "end_time":       "2026-03-04T03:50:00Z",
       "duration_mins":  8,
       "event_count":    14,
       "devices_affected": ["SW3", "R1", "SW1", "SW2"],
       "event_types":    {"interface_down": 6, "ospf_not_full": 3, "bgp_down": 2, ...},
       "root_cause_candidates": ["SW3"],
       "cascade_chain":  "SW3 → R1, SW1, SW2 → OSPF reconverge → BGP hold-timer",
       "events": [{...}, ...]   # raw event list
     }

If run_incident_clustering is not set in profile frontmatter, this module is
never called — zero performance impact on existing profiles.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import networkx as nx

import duckdb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_resolution_to_minutes(resolution: str) -> int:
    """Convert snapshot_resolution string to minutes.

    Examples:  "1d" → 1440,  "5m" → 5,  "1h" → 60,  "30s" → 1 (minimum)
    """
    resolution = resolution.strip().lower()
    if resolution.endswith("w"):
        return max(1, int(float(resolution[:-1]) * 10080))
    elif resolution.endswith("d"):
        return max(1, int(float(resolution[:-1]) * 1440))
    elif resolution.endswith("h"):
        return max(1, int(float(resolution[:-1]) * 60))
    elif resolution.endswith("m"):
        return max(1, int(float(resolution[:-1])))
    elif resolution.endswith("s"):
        return max(1, int(float(resolution[:-1]) / 60))
    return 1440  # default: daily


def build_incident_clusters(
    conn: duckdb.DuckDBPyConnection,
    window: str = "7d",
    gap_minutes: int | None = None,
    min_events: int = 2,
    resolution_minutes: int = 1440,
) -> list[dict]:
    """Build Incident Clusters from the DuckDB event stream.

    Args:
        conn:               Open DuckDB connection.
        window:             Time window string e.g. "7d", "24h".
        gap_minutes:        Max time gap (minutes) between events in the same cluster.
                            If None (default), auto-derived as resolution_minutes × 6
                            (SSH daily → 8640 min/6-day gap → clusters per day;
                             SNMP 5min → 30 min gap → sub-hour incident windows).
        resolution_minutes: Sampling interval in minutes. Drives auto gap when
                            gap_minutes is None.
        min_events:         Discard singleton events (noise filter).

    Returns:
        List of IncidentCluster dicts, sorted by event_count descending.
    """
    # Auto-derive gap: 6 × resolution, but min 5 min, max 1 day (capped for daily SSH)
    if gap_minutes is None:
        gap_minutes = max(5, min(resolution_minutes * 6, 1440))
        logger.info(
            "incident_engine: resolution=%dmin → auto gap=%dmin",
            resolution_minutes, gap_minutes,
        )

    cutoff = _parse_window_to_cutoff(window)
    events = _collect_events(conn, cutoff)

    if not events:
        logger.info("incident_engine: no events found in window %s", window)
        return []

    clusters_raw = _cluster_by_time_gap(events, gap_minutes=gap_minutes, min_events=min_events)

    # Enrich each cluster with topology root-cause inference
    topology = _load_topology(conn)

    incidents: list[dict] = []
    for idx, cluster_events in enumerate(clusters_raw):
        incident = _build_incident(
            cluster_id=f"INC-{idx + 1:03d}",
            events=cluster_events,
            topology=topology,
        )
        incidents.append(incident)

    # Sort by severity: more events + critical types first
    incidents.sort(key=lambda x: x["event_count"], reverse=True)
    return incidents


# ---------------------------------------------------------------------------
# Event collection
# ---------------------------------------------------------------------------


def _collect_events(conn: duckdb.DuckDBPyConnection, cutoff: datetime) -> list[dict]:
    """Collect events from all state tables into a unified stream."""
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    events: list[dict] = []

    queries = {
        # Fault events (high severity)
        "interface_down": f"""
            SELECT device_name,
                   interface AS detail,
                   COALESCE(CAST(created_at AS VARCHAR), '') AS ts_raw,
                   created_at
            FROM interfaces
            WHERE status != 'up'
              AND interface NOT ILIKE 'Loopback%'
              AND interface NOT ILIKE 'Management%'
              AND interface NOT ILIKE 'Vlan%'
              AND created_at >= TIMESTAMPTZ '{cutoff_str}'
        """,
        "bgp_down": f"""
            SELECT device_name,
                   neighbor_ip || ' (AS' || CAST(neighbor_as AS VARCHAR) || ' ' || state || ')' AS detail,
                   COALESCE(CAST(created_at AS VARCHAR), '') AS ts_raw,
                   created_at
            FROM bgp_neighbors
            WHERE state != 'Established'
              AND created_at >= TIMESTAMPTZ '{cutoff_str}'
        """,
        "ospf_not_full": f"""
            SELECT device_name,
                   neighbor_id || ' via ' || interface || ' (' || state || ')' AS detail,
                   COALESCE(CAST(created_at AS VARCHAR), '') AS ts_raw,
                   created_at
            FROM ospf_neighbors
            WHERE state NOT IN ('FULL', '2WAY')
              AND created_at >= TIMESTAMPTZ '{cutoff_str}'
        """,
        "topology_link_down": f"""
            SELECT source_device AS device_name,
                   source_interface || ' → ' || destination_device AS detail,
                   COALESCE(CAST(last_seen AS VARCHAR), '') AS ts_raw,
                   last_seen AS created_at
            FROM topology_links
            WHERE status = 'down'
              AND last_seen >= TIMESTAMPTZ '{cutoff_str}'
        """,
        "config_change": f"""
            SELECT device_name,
                   command || ' (+' || CAST(added_count AS VARCHAR) ||
                       '/-' || CAST(removed_count AS VARCHAR) || ' lines)' AS detail,
                   COALESCE(CAST(timestamp AS VARCHAR), '') AS ts_raw,
                   timestamp AS created_at
            FROM raw_diffs
            WHERE timestamp >= TIMESTAMPTZ '{cutoff_str}'
        """,
    }

    for event_type, sql in queries.items():
        try:
            result = conn.execute(sql)
            cols = [d[0] for d in result.description]
            rows = result.fetchall()
            for row in rows:
                r = dict(zip(cols, row, strict=False))
                ts = r.get("created_at")
                if ts is None:
                    continue
                # Normalise to timezone-aware datetime
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                if hasattr(ts, "tzinfo") and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                events.append({
                    "event_type": event_type,
                    "device_name": r.get("device_name", "unknown"),
                    "detail": r.get("detail", ""),
                    "ts": ts,
                })
        except Exception as exc:
            logger.debug("incident_engine: query for %r failed: %s", event_type, exc)

    return sorted(events, key=lambda x: x["ts"])


# ---------------------------------------------------------------------------
# Time-gap clustering
# ---------------------------------------------------------------------------


def _cluster_by_time_gap(
    events: list[dict],
    gap_minutes: int = 30,
    min_events: int = 2,
) -> list[list[dict]]:
    """Single-linkage time clustering.

    All events separated by <= gap_minutes are merged into the same cluster.
    Clusters with fewer than min_events are discarded (noise filter).
    """
    if not events:
        return []

    gap = timedelta(minutes=gap_minutes)
    clusters: list[list[dict]] = []
    current: list[dict] = [events[0]]

    for event in events[1:]:
        if event["ts"] - current[-1]["ts"] <= gap:
            current.append(event)
        else:
            if len(current) >= min_events:
                clusters.append(current)
            current = [event]

    if len(current) >= min_events:
        clusters.append(current)

    return clusters


# ---------------------------------------------------------------------------
# Topology loading + root-cause inference
# ---------------------------------------------------------------------------


def _load_topology(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Load L2 physical topology links for cascade root-cause inference.

    Uses v_topo_links_clean (strips domain suffixes, removes numeric OSPF nodes).
    Filters to L2 (CDP/LLDP) only — physical propagation is the right model
    for incident cascade analysis.
    """
    try:
        rows = conn.execute(
            "SELECT src, dst FROM v_topo_links_clean WHERE link_type = 'L2'"
        ).fetchall()
        return [{"src": r[0], "dst": r[1]} for r in rows]
    except Exception:
        # Fallback: raw table without L2 filter
        try:
            rows = conn.execute(
                "SELECT source_device, destination_device FROM topology_links"
            ).fetchall()
            return [{"src": r[0], "dst": r[1]} for r in rows]
        except Exception:
            return []


def _build_incident(
    cluster_id: str,
    events: list[dict],
    topology: list[dict],
) -> dict:
    """Build a single IncidentCluster dict with root-cause inference."""
    import networkx as nx

    start_ts = events[0]["ts"]
    end_ts = events[-1]["ts"]
    duration = int((end_ts - start_ts).total_seconds() / 60)

    affected = list({e["device_name"] for e in events})

    # Event type breakdown
    breakdown: dict[str, int] = {}
    for e in events:
        breakdown[e["event_type"]] = breakdown.get(e["event_type"], 0) + 1

    # ── Topology root-cause inference ─────────────────────────────────────
    G = nx.DiGraph()
    G.add_nodes_from(affected)
    for link in topology:
        if link["src"] in affected and link["dst"] in affected:
            G.add_edge(link["src"], link["dst"])

    # Root candidates = nodes with no in-cluster predecessors (in-degree 0
    # within the subgraph of affected devices)
    root_candidates = [n for n in G.nodes if G.in_degree(n) == 0]
    if not root_candidates:
        root_candidates = affected  # fully connected or no topology data

    # Cascade chain: BFS from root through affected devices
    cascade_chain = _build_cascade_description(G, root_candidates, breakdown)

    return {
        "cluster_id": cluster_id,
        "start_time": start_ts.isoformat(),
        "end_time": end_ts.isoformat(),
        "duration_mins": duration,
        "event_count": len(events),
        "devices_affected": affected,
        "event_types": breakdown,
        "root_cause_candidates": root_candidates,
        "cascade_chain": cascade_chain,
        "events": [
            {
                "event_type": e["event_type"],
                "device_name": e["device_name"],
                "detail": e["detail"],
                "ts": e["ts"].isoformat(),
            }
            for e in events
        ],
    }


def _build_cascade_description(
    G: nx.DiGraph,
    root_candidates: list[str],
    breakdown: dict[str, int],
) -> str:
    """Build a human-readable cascade chain string.

    E.g.:  "SW3 (topology_link_down) → R1, SW1 (interface_down, bgp_down) → SW2 (ospf_not_full)"
    """
    import networkx as nx

    if not root_candidates:
        return "Unknown cascade order (no topology data)"

    # BFS from each root
    visited: set[str] = set()
    layers: list[list[str]] = []
    frontier = list(root_candidates)

    while frontier:
        layers.append(list(frontier))
        visited.update(frontier)
        next_frontier = []
        for node in frontier:
            for succ in G.successors(node):
                if succ not in visited:
                    next_frontier.append(succ)
        frontier = next_frontier

    # Add any orphaned nodes (disconnected from topology)
    orphans = [n for n in G.nodes if n not in visited]
    if orphans:
        layers.append(orphans)

    parts = []
    for layer in layers:
        parts.append(", ".join(layer))

    return " → ".join(parts) if parts else ", ".join(root_candidates)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _parse_window_to_cutoff(window: str) -> datetime:
    window = window.strip().lower()
    if window.endswith("h"):
        delta = timedelta(hours=float(window[:-1]))
    elif window.endswith("m"):
        delta = timedelta(minutes=float(window[:-1]))
    elif window.endswith("d"):
        delta = timedelta(days=float(window[:-1]))
    else:
        delta = timedelta(hours=1)
    return datetime.now(tz=UTC) - delta
