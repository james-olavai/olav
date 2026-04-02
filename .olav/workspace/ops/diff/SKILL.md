---
name: ops-diff
description: "Diff Expert — Time-series drift detection. Compares two snapshot_ids to find exactly what changed in the network."
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: network-operations
  intent: state_comparison_drift_detection
tools:
  - diff_sql_state          # Dedicated: Compare any table between snapshots
  - diff_topology_drift    # Dedicated: Physical link state changes
  - diff_routing_drift    # Dedicated: Routing path shifts
  - diff_configs           # Dedicated: Raw config file comparison
system: $ref:./prompts/system.md
---

## Overview

The Diff Expert specializes in time-series drift detection, comparing two snapshots to identify exactly what changed in the network.

## Use Cases

1. **State Comparison**: Compare any table between two snapshots
2. **Topology Drift**: Identify physical link status changes
3. **Routing Drift**: Detect routing path shifts, BGP prefix loss
4. **Config Diff**: Compare raw configuration files between snapshots

## Workflow

1. **Select Snapshots**: Choose two snapshot_ids to compare (T1=before, T2=after)
2. **Choose Analysis Type**:
   - `diff_sql_state` — For any table (ospf_neighbors, interfaces, etc.)
   - `diff_topology_drift` — For topology_links changes
   - `diff_routing_drift` — For routes/bgp_routes changes
   - `diff_configs` — For raw config file comparison
3. **Analyze Results**: Review the delta (missing in T2, new in T2)
4. **Report**: Provide findings with root cause analysis

## Tools Detail

### diff_sql_state
Compare any operational table between two snapshots. Returns JSON with:
- `missing_in_t2`: Rows that existed in T1 but not in T2
- `new_in_t2`: Rows that exist in T2 but not in T1

### diff_topology_drift
Specialized topology comparison focusing on:
- Links that went DOWN
- Links that came UP
- Status changes (up→down, protocol change)

### diff_routing_drift
Routing-specific comparison focusing on:
- Lost prefixes (reachable in T1, missing in T2)
- Next-hop shifts (same prefix, different next-hop)
- BGP AS-PATH changes
