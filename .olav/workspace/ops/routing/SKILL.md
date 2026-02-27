---
name: ops-routing
description: "Routing expert — BGP, OSPF, static routes, routing blackholes, and optimal path analysis"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: network-operations
  intent: routing_analysis
tools:
  - execute_sql              # Dedicated: Query bgp_routes, routes, bgp_neighbors, ospf_neighbors
  - execute_cli              # Dedicated: For live routing protocol state
  - format_and_export        # Dedicated: For exporting route tables
allowed_tables:
  - bgp_routes
  - routes
  - bgp_neighbors
  - ospf_neighbors
  - devices
table_schemas:
  bgp_routes:
    description: "BGP RIB table with AS-PATH, local_pref, communities, and next-hop info"
    key_columns: [device_name, network, mask, next_hop, as_path, local_pref, origin, peer]
  routes:
    description: "IP routing table entries (static, connected, OSPF)"
    key_columns: [device_name, network, mask, next_hop, interface, protocol, metric]
  bgp_neighbors:
    description: "BGP neighbor status and session state"
    key_columns: [device_name, neighbor_ip, neighbor_as, state, uptime, messages]
  ospf_neighbors:
    description: "OSPF neighbor correlations and adjacency state"
    key_columns: [device_name, neighbor_id, neighbor_ip, interface, state, cost]
  devices:
    description: "Device inventory for routing analysis"
    key_columns: [name, hostname, platform, site]
system: $ref:./prompts/system.md
static_context:
  - path: ./references/ROUTING_EXPERT_GUIDE.md
---

## Overview

The Routing Expert specializes in BGP, OSPF, static routes, routing blackholes, and optimal path analysis.

## Use Cases

1. **BGP Analysis**: AS-PATH, communities, prefix filtering, neighbor state
2. **OSPF Analysis**: Area relationships, cost calculation, adjacency state
3. **Route Lookup**: Trace packet path through the routing table
4. **Blackhole Detection**: Identify unreachable destinations
5. **Path Optimization**: Analyze optimal routing paths

## Workflow

1. Query `bgp_routes` and `routes` tables for routing information
2. Check `bgp_neighbors` and `ospf_neighbors` for protocol state
3. Use `execute_cli` for live verification when needed
4. Export results with `format_and_export`
