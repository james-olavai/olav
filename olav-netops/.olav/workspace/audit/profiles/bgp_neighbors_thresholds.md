---
name: bgp_neighbors_thresholds
deprecated: true   # 2026-05-15: SQL references stale v_bgp_neighbors_auto (no netops. prefix, no canonical view name); use bgp_health.md v6.0 instead.
version: '4.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_DOWN_SESSIONS
  type: sql
  severity: Critical
  section_prompt: Count non-Established BGP sessions per device. Any down session
    (>0) is critical. Check state != 'Established'. Recommend checking logs for flaps
    or config mismatch.
  query: SELECT device_name AS device, COUNT(CASE WHEN LOWER(state) != 'established'
    THEN 1 END)::DOUBLE AS metric_value, 'Down BGP Sessions' AS metric_name, CASE
    WHEN COUNT(CASE WHEN LOWER(state) != 'established' THEN 1 END) > 0 THEN 'Critical'
    ELSE 'OK' END AS severity_hint FROM bgp_neighbors WHERE created_at >= NOW() -
    INTERVAL :window GROUP BY device_name HAVING COUNT(CASE WHEN LOWER(state) != 'established'
    THEN 1 END) > 0
- name: BGP_TOTAL_SESSIONS
  type: sql
  severity: Info
  section_prompt: Total BGP neighbors per device. Warn if count changes >20% or >50
    total.
  query: SELECT device_name AS device, COUNT(*)::DOUBLE AS metric_value, 'Total BGP
    Sessions' AS metric_name, 'Info' AS severity_hint FROM bgp_neighbors WHERE created_at
    >= NOW() - INTERVAL :window GROUP BY device_name
- name: AVG_PREFIXES_RECEIVED
  type: sql
  severity: Warning
  section_prompt: 'Average prefixes received per neighbor. Threshold: >500 warning
    (high load), analyze for anomalies.'
  query: SELECT device_name AS device, AVG(CAST(prefixes_received AS DOUBLE)) AS metric_value,
    'Avg Prefixes Received' AS metric_name, CASE WHEN AVG(prefixes_received) > 500
    THEN 'Warning' ELSE 'OK' END AS severity_hint FROM bgp_neighbors WHERE created_at
    >= NOW() - INTERVAL :window AND LOWER(state) = 'established' GROUP BY device_name
- name: MAX_PREFIXES_RECEIVED
  type: sql
  severity: Warning
  section_prompt: 'Max prefixes from any neighbor. Threshold: >1000 critical (potential
    route leak or full table).'
  query: SELECT device_name AS device, MAX(CAST(prefixes_received AS DOUBLE)) AS metric_value,
    'Max Prefixes Received' AS metric_name, CASE WHEN MAX(prefixes_received) > 1000
    THEN 'Critical' ELSE 'OK' END AS severity_hint FROM bgp_neighbors WHERE created_at
    >= NOW() - INTERVAL :window AND LOWER(state) = 'established' GROUP BY device_name
---

# BGP Neighbors Thresholds Audit Profile\n\nMonitors BGP session health, prefix counts, and anomalies using data from `bgp_neighbors` table.\n\n## Key Metrics\n- Down sessions: >0 Critical\n- Avg prefixes: >500 Warning\n- Max prefixes: >1000 Critical\n- Total sessions: Info (track changes)
