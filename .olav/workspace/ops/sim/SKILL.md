---
name: ops-sim
description: >
  Unified routing analysis and network simulation agent.
  Queries BGP/OSPF/routing tables for live state; runs deterministic Python
  simulations via LLMExperimentSandbox (networkx + netutils) for What-If analysis.
  Does NOT guess outcomes — writes code to compute them.
metadata:
  version: 2.1.0
  replaces: [ops-routing v1.0.0, ops-simulation v0.1.0]
  type: agent
  category: network-operations
  intents: [routing_analysis, change_simulation, topology_analysis]
tools:
  - execute_sql              # Query: bgp_routes, routes, ospf_neighbors, bgp_neighbors, topology_links, interfaces
  - execute_cli              # Live: show ip bgp / show ip ospf neighbor / show ip route
  - run_python_simulation    # Sandbox: LLMExperimentSandbox with sim + networkx + netutils
  - format_and_export        # Output: CSV/JSON/Markdown report export
allowed_tables:
  - bgp_routes
  - routes
  - v_bgp_neighbors_auto
  - v_ospf_neighbors_auto
  - v_interfaces_auto
  - v_topology_l2_auto
  - v_arp_auto
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

Unified agent combining BGP/OSPF routing analysis with deterministic graph-based
simulation. For any "what happens if..." question, writes Python code to compute
the exact outcome using networkx and netutils in a secure sandbox.

## Use Cases

1. **Routing Analysis**: BGP AS-PATH, OSPF cost, route lookup, blackhole detection
2. **Change Impact**: Simulate link/device/neighbor failure via sandbox graph mutation
3. **Path Analysis**: OSPF/BGP shortest path with cost weights via networkx
4. **BGP Best-Path**: Deterministic best-path from local_pref, as_path, weight
5. **Multi-Layer Topology**: L2 (LLDP/CDP) + L3 (OSPF/BGP) enriched living graph
6. **Change Planning**: Produce structured change plans with Markdown reports

## Tool Notes

- `execute_cli` and `execute_sql` are shared with all other ops agents via symlink (`ops/tools/`).
  Any update to the canonical file propagates to sim automatically.
- `execute_cli` enforces the `commands` table whitelist/blacklist before connecting to any device.

## Replaced Agents

- `ops-routing` (v1.0.0): all capabilities migrated here
- `ops-simulation` (v0.1.0): `simulate_change` (NetworkSimulator) and
  `analyze_network_topology` (DuckPGQ) replaced by `run_python_simulation`
  backed by `LLMExperimentSandbox`

## Simulation Boundaries (v0.11.0)

| Capability | Status |
|---|---|
| L1/L2 topology reachability (networkx) | ✅ Ready |
| L3 OSPF path + cost (enriched edges) | ✅ Ready |
| L3 BGP overlay + best-path | ✅ Ready |
| L3 ECMP multi-path selection | ⚠️ Partial |
| STP topology change simulation | ❌ Blocked — no spanning_tree collection |
| VLAN isolation simulation | ❌ Blocked — no vlans/mac_table collection |
| L4 ACL packet filtering | ❌ Blocked — no acls collection |
