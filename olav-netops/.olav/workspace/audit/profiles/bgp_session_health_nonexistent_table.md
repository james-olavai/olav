---
name: bgp_session_health_nonexistent_table
deprecated: true   # 2026-05-15: SQL references stale v_bgp_neighbors_auto (no netops. prefix, no canonical view name); use bgp_health.md v6.0 instead.
version: '4.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_SESSIONS_STATUS
  type: sql
  severity: Warning
  section_prompt: Check BGP session status for all devices. Flag any sessions not
    in 'Established' state. Report device_name, neighbor_ip, state for unhealthy sessions.
    Use recent data (last 24h).
  query: SELECT device_name, neighbor_ip, state, created_at FROM nonexistent_table_xyz_abc
    WHERE (state != 'Established' OR state IS NULL) AND created_at >= NOW() - INTERVAL
    '24' HOURS ORDER BY device_name, created_at DESC
---

# BGP Session Health Check (Nonexistent Table Test)\n\nThis profile queries BGP session status from `nonexistent_table_xyz_abc`. \n\n**Note:** Table does not exist (validation failed). This demonstrates error handling in audits.\n\n## Purpose\nHealth check for BGP peering status across all devices.\n\n## Expected Output\n- List of down/idle BGP sessions per device\n- Critical if >50% sessions down per device\n\n## Data Source\nIntended: nonexistent_table_xyz_abc (BGP neighbors table)
