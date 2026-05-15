---
name: ospf_health
version: '1.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: OSPF_ADJACENCY_STATE
  type: sql
  severity: Critical
  section_prompt: 'Analyze OSPF neighbor adjacency states across Cisco (v_show_ip_ospf_neighbor_auto)
    and Juniper (v_show_ospf_neighbor_auto). Healthy adjacencies are in ''Full'' state
    (or any state starting with ''Full/'' like Full/BDR, Full/DR). Flag any neighbors
    in Init, 2-Way, ExStart, Exchange, Loading, or Down — these indicate OSPF peering
    instability. Include the device, neighbor_id, interface, and state for each non-Full
    neighbor.'
  query: "SELECT\n  device_name AS device,\n  neighbor_id,\n  interface,\n  state,\n\
    \  'OSPF Adjacency State' AS metric_name,\n  1 AS metric_value,\n  CASE\n    WHEN\
    \ state LIKE 'Full%' THEN 'Info'\n    WHEN state IS NULL OR state = '' THEN 'Warning'\n\
    \    ELSE 'Critical'\n  END AS severity_hint\nFROM (\n  SELECT device_name, neighbor_id,\
    \ interface, state FROM netops.v_show_ip_ospf_neighbor_auto\n  UNION ALL\n  SELECT\
    \ device_name, neighbor_id, interface, state FROM netops.v_show_ospf_neighbor_auto\n\
    ) ORDER BY\n  CASE WHEN state LIKE 'Full%' THEN 1 ELSE 0 END ASC,\n  device_name,\
    \ neighbor_id"
- name: OSPF_NEIGHBOR_COUNT
  type: sql
  severity: Warning
  section_prompt: 'Report per-device OSPF neighbor count. Devices participating in OSPF
    should report at least one Full-state neighbor. Zero neighbors on a device expected
    to run OSPF indicates either a misconfigured area, an interface down, or a parser
    gap. Cross-check against topology expectations before alerting.'
  query: "WITH all_neighbors AS (\n  SELECT device_name, state FROM netops.v_show_ip_ospf_neighbor_auto\n\
    \  UNION ALL\n  SELECT device_name, state FROM netops.v_show_ospf_neighbor_auto\n\
    )\nSELECT\n  device_name AS device,\n  COUNT(*) AS metric_value,\n  SUM(CASE WHEN\
    \ state LIKE 'Full%' THEN 1 ELSE 0 END) AS full_count,\n  'OSPF Neighbor Count'\
    \ AS metric_name,\n  CASE\n    WHEN COUNT(*) = 0 THEN 'Warning'\n    WHEN SUM(CASE\
    \ WHEN state LIKE 'Full%' THEN 1 ELSE 0 END) = 0 THEN 'Critical'\n    ELSE 'Info'\n\
    \  END AS severity_hint\nFROM all_neighbors\nGROUP BY device_name\nORDER BY metric_value\
    \ ASC"
---

# OSPF Health Audit Profile

This profile audits OSPF adjacency health across Cisco IOS and Juniper Junos:

1. **OSPF_ADJACENCY_STATE** (Critical): Per-neighbor adjacency state — flags any neighbor not in `Full` / `Full/*`.
2. **OSPF_NEIGHBOR_COUNT** (Warning): Per-device neighbor count + full-count — flags devices reporting OSPF data but zero Full-state neighbors.

**Data Sources**:
- `netops.v_show_ip_ospf_neighbor_auto` (Cisco — columns: device_name, snapshot_id, neighbor_id, priority, state, dead_time, ip_address, interface)
- `netops.v_show_ospf_neighbor_auto` (Juniper — columns: device_name, snapshot_id, ip_address, interface, state, neighbor_id, priority, dead_time)

Both share `(device_name, neighbor_id, interface, state)`, used via UNION ALL.

**Healthy baseline**: 100% of neighbors in `Full` or `Full/BDR` / `Full/DR` state.

**Common non-healthy states** and what they mean:
- `Init` / `2-Way` — adjacency starting, may be normal on broadcast networks
- `ExStart` / `Exchange` / `Loading` — stuck DBD/LSR exchange, often MTU mismatch
- `Down` — adjacency lost; check interface + dead-timer
