---
name: ops-topology
description: "Network topology expert — L2/L3 topology analysis using DuckDB and graph algorithms"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: network-operations
  intent: topology_analysis
tools:
  - topology                 # Dedicated: Pathfinding, cycle detection, L2/L3 graph analysis
database_schema:
  topology_links:
    description: "Unified relationship map (L2 physical + L3 logical links from BGP/OSPF)"
  v_bgp_neighbors_enriched:
    description: "Enriched BGP neighbors with resolved peer device names"
  v_routes_enriched:
    description: "Enriched routing table with resolved next-hop device names"
  interfaces:
    description: "IPAM mapping table (IP to device/interface)"
  bgp_routes:
    description: "BGP RIB table with AS-PATH, LLP, Communities, etc."
  devices:
    description: CDP/LLDP discovered L2 links
    key_columns: [link_id, source_device, source_interface, destination_device, destination_interface, discovery_protocol, link_status]
  routes:
    description: IP routing table entries
    key_columns: [device_name, network, mask, next_hop, interface, protocol]
  bgp_neighbors:
    description: BGP neighbor status
    key_columns: [device_name, neighbor_ip, neighbor_as, state]
  ospf_neighbors:
    description: OSPF neighbor correlations
    key_columns: [device_name, neighbor_id, neighbor_ip, interface, state]
system: $ref:./prompts/system.md
---

## Overview

The Topology Expert specializes in discovering, analyzing, and reporting network topology using DuckDB and graph algorithms.

## Use Cases

1. **L2 Analysis**: MAC tables, ARP, physical links, STP loop detection
2. **L3 Logical Topology**: BGP/OSPF neighbor relationships
3. **Path Finding**: Calculate paths between devices
4. **Cycle Detection**: Identify loops in the network topology
5. **Topology Export**: Generate diagram files (.mmd format)

## Workflow

1. Query `topology_links` for physical/logical relationships
2. Use `analyze_network_topology` for pathfinding and cycle detection
3. Export results with `format_and_export`
