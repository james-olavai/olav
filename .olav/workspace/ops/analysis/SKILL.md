---
name: ops-analysis
description: >
  Pure-compute network analysis engine: routing analysis, deterministic simulation,
  and topology visualization. Reads production DB; runs Python simulations via
  execute_in_sandbox (db + sim + networkx + netutils). Does not access live devices.
  For fresh data, request the orchestrator to delegate to ops-probe first.
metadata:
  version: 1.1.0
  replaces: [ops-sim v2.1.0, ops-topology v1.0.0]
  type: agent
  network_isolation: "true"
  category: network-operations
  intents: [routing_analysis, change_simulation, topology_analysis, topology_visualization]
tools:
  - run_python_simulation    # Sandbox: db + sim + networkx + netutils (covers all analysis needs)
allowed_tables:
  - bgp_routes
  - routes
  - v_bgp_neighbors_auto
  - v_ospf_neighbors_auto
  - v_interfaces_auto
  - v_topology_l2_auto
  - v_arp_auto
  - v_topo_links_clean
  - v_device_neighbors_summary
  - v_bgp_neighbors_enriched
  - v_routes_enriched
  - netops.topology_links
  - netops.devices
  - netops.parsed_outputs
  - netops.oc_outputs
  - schema_catalog
  - view_recipes
static_context:
  - path: ./references/ROUTING_EXPERT_GUIDE.md
system: $ref:./prompts/system.md
---

## Overview

Unified agent combining:
1. **Routing Analysis** — BGP/OSPF/routing table analysis using DuckDB snapshot data
2. **Change Simulation** — Deterministic what-if simulation via networkx + netutils sandbox
3. **Topology Visualization** — L2/L3 graph analysis, path finding, Mermaid diagram export

## Use Cases

1. **Routing Analysis**: BGP AS-PATH, OSPF cost, route lookup, blackhole detection
2. **Change Impact**: Simulate link/device/neighbor failure via sandbox graph mutation
3. **Path Analysis**: OSPF/BGP shortest path with cost weights via networkx
4. **BGP Best-Path**: Deterministic best-path from local_pref, as_path, weight
5. **Topology Diagrams**: L2 (LLDP/CDP) + L3 (OSPF/BGP) Mermaid visualizations
6. **Loop Detection**: STP loop analysis, cycle detection in topology graph
7. **Device Resolution**: IP → hostname mapping via topology joins

## Tool Notes

- `run_python_simulation` — sandbox with `db` (read-only DB proxy), `sim` (writable in-memory clone), `nx` (networkx), `netutils`. Network isolation via `OLAV_SANDBOX_NETNS=1` env var.
- **sandbox_guard SQL rule**: `sim.execute()` with literal SQL starting with CREATE/INSERT/etc. must use a variable:
  ```python
  _sql = "CREATE TABLE sim_x (col VARCHAR)"
  sim.execute(_sql)  # NOT: sim.execute("CREATE TABLE ...")
  ```

## Design Feasibility Check — Common BLOCKER Patterns

Always query these from DB, never assume:

| Required Info | DB Source | BLOCKER if missing |
|---|---|---|
| Peer AS number | `v_bgp_neighbors_auto` (device's own neighbors or peer's view of device) | Yes — cannot design session type |
| BGP link IP | `v_interfaces_auto` joined with `v_topo_links_clean` | Yes — Phase 0 must assign IPs |
| Direct physical link | `v_topo_links_clean WHERE src=X AND dst=Y` | Warning (not blocker if using intermediate hops) |
| IGP between peers | `v_ospf_neighbors_auto` | Blocker for iBGP design |
| Route to loopback | `v_routes_enriched WHERE device_name=X AND network=<loopback>/32` | Blocker for multihop eBGP |

If ANY BLOCKER is found: **state it explicitly in the change plan** as a Phase 0 prerequisite. Do NOT assume or invent values.

## Sandbox Network Policy

**`network_isolation=True`** — analysis sandbox is fully network-isolated.

All simulation is pure local computation (networkx, DuckDB in-memory clone, netutils).
```python
execute_in_sandbox(code, network_isolation=True)  # always for analysis agent
```

## Migration Notes

- Replaces `ops-sim` (v2.1.0) and `ops-topology` (v1.0.0)
- All capabilities from both agents are available in this unified agent
- `ops-sim` intents: routing_analysis, change_simulation, topology_analysis
- `ops-topology` intents: topology_analysis, topology_visualization
