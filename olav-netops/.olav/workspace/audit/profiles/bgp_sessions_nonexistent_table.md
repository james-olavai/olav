---
name: bgp_sessions_nonexistent_table
deprecated: true   # 2026-05-15: SQL references stale v_bgp_neighbors_auto (no netops. prefix, no canonical view name); use bgp_health.md v6.0 instead.
version: '4.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_SESSIONS_ALL_DEVICES
  type: sql
  severity: Warning
  section_prompt: 'Query BGP session status for all devices. The requested table ''nonexistent_table_xyz_abc''
    does not exist; using correct view v_bgp_neighbors_auto joined with netops.devices
    for device inventory. Compute per-device: total BGP sessions, down sessions (non-Established).
    Healthy if 100% Established (down_sessions=0). Flag Warning if any down sessions.'
  query: SELECT d.hostname AS device, COALESCE(b.total_sessions, 0) AS metric_value,
    'Total BGP Sessions' AS metric_name, CASE WHEN COALESCE(b.down_sessions, 0) >
    0 THEN 'Warning' WHEN COALESCE(b.total_sessions, 0) = 0 THEN 'Info' ELSE 'Info'
    END AS severity_hint FROM netops.devices d LEFT JOIN (SELECT device, COUNT(*)
    AS total_sessions, COUNT(*) FILTER (WHERE state != 'Established') AS down_sessions
    FROM v_bgp_neighbors_auto GROUP BY device) b ON d.hostname = b.device
---

# BGP Session Health Check (Nonexistent Table Corrected)

## Purpose
Health check for BGP peering status across **all devices**. 

**Note**: Requested table `nonexistent_table_xyz_abc` does not exist in schema. Automatically corrected to use:
- `v_bgp_neighbors_auto` (BGP neighbors view: device, neighbor_ip, state, etc.)
- `netops.devices` (device inventory: hostname, platform, role)

## Expected Healthy State
- All BGP sessions `Established`
- No down/idle sessions per device
- Switches/edge devices may have 0 sessions (Info)

## Metrics Reported
| Metric | Description | Warning Trigger |
|--------|-------------|-----------------|
| Total BGP Sessions | Count of all peers per device | Any non-Established |
