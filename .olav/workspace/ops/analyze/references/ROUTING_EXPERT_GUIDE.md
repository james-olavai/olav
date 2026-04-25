# 🕵️‍♂️ Routing Expert Reference Guide

This guide provides deterministic algorithms for routing analysis in Python simulation code.
All examples run inside `run_python_simulation` sandbox using `db`, `sim`, and `nx`.

> ⚠️ **Schema note**: code examples below reference
> ``v_routes_enriched`` — that view **does not exist** in the current
> schema.  Treat the SQL as *intent* rather than literal queries.
> For routing data, JSON-extract from
> ``netops.parsed_outputs.parsed_data`` where ``command='show ip route'``
> (IOS) or ``command='show route summary'`` (Junos).  See
> ``references/DB_SCHEMA.md`` in the ops workspace for the
> authoritative view + table list.

---

## 1. BGP Neighbor States

| State | Meaning | Troubleshoot |
|-------|---------|-------------|
| `Idle` | BGP disabled or no route to peer | Check config, check `v_routes_enriched` for route to peer IP |
| `Active` | Trying to connect — TCP 179 failing | MTU mismatch, ACL blocking TCP 179, or missing route to peer |
| `Connect` | TCP SYN sent, waiting for SYN-ACK | Firewall or routing issue |
| `OpenSent` | TCP connected, BGP Open sent | Hold-time mismatch, AS mismatch |
| `OpenConfirm` | Open received, waiting for Keepalive | Near-established |
| `Established` | Peering up, exchanging prefixes | ✅ |

---

## 2. BGP Path Selection (Priority Order)

For a given prefix, the best path is selected by the FIRST differing attribute:

1. **Weight** (Cisco only) — Highest wins. Local to router, not advertised.
2. **Local Preference** — Highest wins. Default 100. iBGP scope.
3. **Locally Originated** — Prefer locally originated (network/redistribute) over learned.
4. **AS Path Length** — Shortest wins. Count AS numbers in the path.
5. **Origin Type** — IGP (i) > EGP (e) > Incomplete (?).
6. **MED (Multi-Exit Discriminator)** — Lowest wins. Compare only between paths from same AS.
7. **eBGP over iBGP** — Prefer eBGP learned routes over iBGP.
8. **IGP Metric to Next-Hop** — Lowest OSPF/IS-IS cost to reach the BGP next-hop.
9. **Oldest path** — Prefer older eBGP path (stability).
10. **Router ID** — Lowest BGP Router ID wins.

### BGP Best-Path Algorithm (Python)

```python
def bgp_best_path(routes):
    """Select best BGP path from a list of route dicts.
    
    Each route dict must have: prefix, next_hop, weight, local_pref,
    as_path (list), origin, med, route_type (eBGP/iBGP), igp_metric, router_id
    """
    if not routes:
        return None
    
    def sort_key(r):
        as_path_len = len(r.get("as_path", []))
        origin_map = {"igp": 0, "egp": 1, "incomplete": 2, "i": 0, "e": 1, "?": 2}
        origin_val = origin_map.get(r.get("origin", "?").lower(), 2)
        route_type_val = 0 if r.get("route_type", "iBGP") == "eBGP" else 1
        return (
            -r.get("weight", 0),           # higher weight = better (negate for sort)
            -r.get("local_pref", 100),      # higher local_pref = better
            as_path_len,                    # shorter = better
            origin_val,                     # IGP=0 is best
            r.get("med", 0),                # lower med = better
            route_type_val,                 # eBGP=0 better than iBGP=1
            r.get("igp_metric", 0),         # lower metric = better
            r.get("router_id", "255.255.255.255"),  # lower router_id = better
        )
    
    return sorted(routes, key=sort_key)[0]


# Example: find best path for each prefix in DB
routes = db.query("""
    SELECT device_name, network, next_hop, local_pref, as_path_length,
           metric as med, route_source
    FROM v_routes_enriched
    WHERE device_name = 'R1'
""")
# Group by prefix and find best
from collections import defaultdict
by_prefix = defaultdict(list)
for r in routes:
    by_prefix[r["network"]].append(r)

best_paths = {prefix: bgp_best_path(paths) for prefix, paths in by_prefix.items()}
_result = {"best_paths": {p: str(b) for p, b in best_paths.items()}}
```

---

## 3. OSPF Shortest Path (Dijkstra with Cost Weights)

OSPF selects paths by lowest cumulative cost. Default cost = 10^8 / interface_bandwidth.

### Cost Accumulation Rule
- Total path cost = SUM of costs on outgoing interfaces along the path
- For bidirectional links, use the cost on the LOCAL interface (sending direction)

### OSPF Weighted Graph (Python)

```python
# Build OSPF-weighted graph from DB
ospf_nbrs = db.query("""
    SELECT device_name, neighbor_id, interface, cost, state
    FROM netops.v_ospf_neighbors_auto
    WHERE state = 'FULL'
""")

G = nx.DiGraph()
for row in ospf_nbrs:
    cost = row.get("cost") or 10  # default cost if missing
    G.add_edge(
        row["device_name"],
        row["neighbor_id"],
        weight=cost,
        interface=row.get("interface"),
    )

# Shortest path with cost
try:
    path = nx.dijkstra_path(G, "R1", "R4", weight="weight")
    path_cost = nx.dijkstra_path_length(G, "R1", "R4", weight="weight")
    _result = {"path": path, "cost": path_cost}
except nx.NetworkXNoPath:
    _result = {"path": None, "cost": None, "reason": "No OSPF path R1→R4"}
```

### All Shortest Paths (ECMP Detection)

```python
# Find all equal-cost paths (ECMP)
try:
    all_paths = list(nx.all_shortest_paths(G, "R1", "R4", weight="weight"))
    min_cost = nx.dijkstra_path_length(G, "R1", "R4", weight="weight")
    _result = {
        "ecmp_paths": all_paths,
        "path_count": len(all_paths),
        "min_cost": min_cost,
        "is_ecmp": len(all_paths) > 1,
    }
except nx.NetworkXNoPath:
    _result = {"ecmp_paths": [], "is_ecmp": False, "reason": "No path"}
```

---

## 4. ECMP Detection

ECMP (Equal-Cost Multi-Path) exists when 2+ paths to a destination have identical cost.

**Conditions for ECMP:**
- OSPF: same total cost, same area, same path type (intra > inter > external)
- BGP: identical local_pref + weight + AS-path length + origin + MED + IGP metric
- Static: multiple entries with same admin distance and metric

```python
# OSPF ECMP check
ecmp_links = {}
for src in G.nodes():
    for dst in G.nodes():
        if src == dst:
            continue
        try:
            paths = list(nx.all_shortest_paths(G, src, dst, weight="weight"))
            if len(paths) > 1:
                ecmp_links[(src, dst)] = {
                    "paths": paths,
                    "count": len(paths),
                    "cost": nx.dijkstra_path_length(G, src, dst, weight="weight"),
                }
        except nx.NetworkXNoPath:
            pass
_result = {"ecmp_pairs": {f"{s}→{d}": v for (s,d), v in ecmp_links.items()}}
```

---

## 5. Convergence Time Estimation

Approximate OSPF convergence time after a link failure:

| Event | Typical Time |
|-------|-------------|
| Link down detection (BFD) | 50–300ms |
| Link down detection (hello timer) | 10–40s (dead interval) |
| SPF computation | <1ms (modern hardware) |
| LSA flooding | 50–200ms |
| RIB/FIB update | 100ms–1s |
| BGP scan interval | 60s (default) |
| BGP graceful restart | up to 120s |

```python
# Estimate convergence for R2 failure scenario
scenario = {
    "failed_node": "R2",
    "detection_method": "hello_timer",  # or "bfd"
    "ospf_dead_interval": 40,           # seconds
    "spf_delay": 0.05,                  # 50ms
    "lsa_flood_time": 0.15,             # 150ms
    "fib_update": 0.5,                  # 500ms
}
if scenario["detection_method"] == "bfd":
    detect_time = 0.3  # 300ms
else:
    detect_time = scenario["ospf_dead_interval"]

total_seconds = detect_time + scenario["spf_delay"] + scenario["lsa_flood_time"] + scenario["fib_update"]
_result = {
    "scenario": scenario["failed_node"] + " failure",
    "detection_s": detect_time,
    "spf_s": scenario["spf_delay"],
    "total_convergence_s": round(total_seconds, 2),
    "packets_lost_estimate": int(total_seconds * 1000),  # at 1000pps
}
```

---

## 6. Common Troubleshooting Patterns

### BGP Not Establishing

```python
# Check BGP state and find likely cause
bgp = db.query("SELECT * FROM netops.v_bgp_neighbors_auto WHERE device_name = 'R1'")
routes = db.query("SELECT * FROM v_routes_enriched WHERE device_name = 'R1'")

for peer in bgp:
    if peer["state"] != "Established":
        # Check if route to peer exists
        peer_routes = [r for r in routes if peer["neighbor_ip"] in (r.get("network") or "")]
        _result = {
            "peer": peer["neighbor_ip"],
            "state": peer["state"],
            "has_route_to_peer": len(peer_routes) > 0,
            "likely_cause": "Missing route to peer" if not peer_routes else "Config mismatch (AS/auth)"
        }
```

### Path Shift Analysis

```python
# Compare routes between two snapshots
snap1 = db.query("""
    SELECT device_name, network, next_hop, snapshot_id
    FROM v_routes_enriched WHERE snapshot_id = (
        SELECT snapshot_id FROM netops.parsed_outputs ORDER BY created_at ASC LIMIT 1
    )
""")
snap2 = db.query("""
    SELECT device_name, network, next_hop, snapshot_id
    FROM v_routes_enriched WHERE snapshot_id = (
        SELECT snapshot_id FROM netops.parsed_outputs ORDER BY created_at DESC LIMIT 1
    )
""")
# Raw fallback note (RAW-05): commands whose TextFSM parser failed (common on
# Junos / SR Linux) land in netops.raw_output_store with the same snapshot_id.
# The snapshot-boundary query above only sees snapshots that produced *any*
# parsed row; if an entire snapshot parsed empty, widen the boundary via
# UNION ALL:
#
#     SELECT snapshot_id, created_at FROM netops.parsed_outputs
#     UNION ALL
#     SELECT snapshot_id, created_at FROM netops.raw_output_store
#     ORDER BY created_at DESC LIMIT 1
#
# Find routes that changed next_hop
snap1_map = {(r["device_name"], r["network"]): r["next_hop"] for r in snap1}
snap2_map = {(r["device_name"], r["network"]): r["next_hop"] for r in snap2}
shifts = []
for key, nh1 in snap1_map.items():
    nh2 = snap2_map.get(key)
    if nh2 and nh2 != nh1:
        shifts.append({"device": key[0], "prefix": key[1], "from": nh1, "to": nh2})
_result = {"path_shifts": shifts, "count": len(shifts)}
```

---

## NetworkModel Recipes (ARCH-06 / ARCH-14)

Every `run_python_simulation` sandbox call gets `model = load_network_model()`
auto-injected — construction is lazy, so simply having it in scope costs
nothing. Touch a layer attribute to trigger the DuckDB read. The model
tolerates an empty / missing DB by returning layers whose collections are
empty (no raises on sandbox import).

### Pattern A — DuckDB + networkx via `model.physical`

L1 physical topology already comes back as a `networkx.Graph`; use it for
shortest-path / cut-vertex / ECMP queries without re-querying
`topology_links`.

```python
import networkx as nx

# All pairs shortest path from the LLDP graph.
g = model.physical.graph
if g is None or g.number_of_nodes() == 0:
    _result = {"error": "no topology for active snapshot"}
else:
    paths = dict(nx.all_pairs_shortest_path_length(g))
    _result = {
        "diameter": max(max(d.values()) for d in paths.values()),
        "R1_reach": paths.get("R1", {}),
    }
```

### Pattern A* — cross-layer trace via `model.l3.ospf` + `model.physical`

```python
# Does an OSPF adjacency have a backing physical link?
adj = model.l3.ospf.adjacencies
phys = model.physical.graph
orphans = []
for a in adj:
    dev = a["device"]
    rid = a["neighbor_id"]
    if phys is not None and rid not in phys.neighbors(dev):
        orphans.append(a)
_result = {"ospf_adjacencies_without_l1_link": orphans, "count": len(orphans)}
```

### Pattern B — LanceDB semantic search (recall_memory alongside NoM)

LanceDB-backed semantic recall (`recall_memory`) is not exposed through
`model.*` directly — its purpose is text-document retrieval, which lives
outside the network-object model. Use it alongside the NoM when a query
needs both structured network state *and* matching operator knowledge:

```python
# Pattern B — NoM + semantic recall composition.
unhealthy = model.l3.bgp.unhealthy()
# Then (outside sandbox, in the agent layer) the orchestrator calls
# recall_memory("past BGP stuck in Active resolutions") and feeds the
# joined context to the LLM.
_result = {
    "unhealthy_sessions": unhealthy,
    "next_step": "recall_memory('stuck BGP Active recovery')",
}
```

### Pattern C — Deterministic route-map evaluation via `model.l4`

```python
# Does R1's export policy to 10.0.12.2 permit a prefix that matched
# CUST_PREFIXES? Deterministic — no LLM needed.
decision = model.l4.policy(
    device="R1",
    neighbor="10.0.12.2",
    direction="out",
    matches={"ip address prefix-list CUST_PREFIXES": True},
)
_result = {
    "action": decision["action"],
    "policy_name": decision["policy_name"],
    "sets": decision["sets"],
    "trace_summary": [(e["seq"], e["action"], e["matched"]) for e in decision["trace"]],
}
```

When `matches` is a callable, the walker asks each match condition one by
one — plug in an LLM-backed matcher for "prefix-list CUSTOMERS matches
10.1.0.0/16" style judgements that need domain knowledge.
