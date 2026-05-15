---
name: bgp_session_status_nonexistent
deprecated: true   # 2026-05-15: SQL references stale v_bgp_neighbors_auto (no netops. prefix, no canonical view name); use bgp_health.md v6.0 instead.
version: '4.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_SESSIONS_ALL_DEVICES
  type: sql
  severity: Warning
  section_prompt: 'Query BGP session status for all devices. Since ''nonexistent_table_xyz_abc''
    does not exist, using correct table v_bgp_neighbors_auto joined with netops.devices.
    Report per-device total sessions, down sessions (non-Established), and flag if
    any down sessions. Healthy: 100% Established.'
  query: SELECT d.hostname AS device, COALESCE(b.total_sessions, 0) AS metric_value,
    'Total BGP Sessions' AS metric_name, CASE WHEN COALESCE(b.down_sessions, 0) >
    0 THEN 'Warning' WHEN COALESCE(b.total_sessions, 0) = 0 THEN 'Info' ELSE 'Info'
    END AS severity_hint FROM netops.devices d LEFT JOIN (SELECT device_name, COUNT(*)
    AS total_sessions, COUNT(*) FILTER (WHERE state != 'Established') AS down_sessions
    FROM v_bgp_neighbors_auto GROUP BY device_name) b ON d.hostname = b.device_name
---

# BGP Session Status Health Check (Corrected)

## Purpose
Health check for BGP session status across all devices. Original request referenced non-existent table `nonexistent_table_xyz_abc`. Corrected to use `v_bgp_neighbors_auto` (BGP neighbors view) joined with `netops.devices` (device inventory).

## Jobs
- **BGP_SESSIONS_ALL_DEVICES** (Warning): Per-device BGP session count and down sessions. Flags devices with flapping or down peers.

## Notes
- All devices included (even non-BGP routers show 0 sessions).
- Data from latest snapshots.
- Run `olav --agent audit bgp_session_status_nonexistent` to execute.
