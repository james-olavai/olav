---
name: bgp_health_check
version: '4.0'
persist_findings_to_db: false
deprecated: true   # rev 266: variant of bgp_health.md with stale SQL (FROM v_bgp_neighbors_auto unqualified, MAX(created_at) on view that has no created_at column). Use bgp_health.md for canonical BGP health audit.
max_findings_per_job: 50
jobs:
- name: BGP_SESSIONS_DOWN_PCT
  type: sql
  severity: Critical
  section_prompt: Calculate percentage of BGP sessions not Established per device.
    Critical >50%, Warning >20%. Include counts.
  query: WITH stats AS (SELECT device_name, COUNT(*) as total, SUM(CASE WHEN LOWER(TRIM(COALESCE(state,
    ''))) = 'established' THEN 1 ELSE 0 END) as up FROM v_bgp_neighbors_auto GROUP
    BY device_name) SELECT device_name as device, ROUND(100.0 * (total - up) / total,
    2) as metric_value, '% BGP Sessions Down' as metric_name, total as total_neighbors,
    (total - up) as down_count, CASE WHEN 100.0 * (total - up) / total > 50 THEN 'Critical'
    WHEN 100.0 * (total - up) / total > 20 THEN 'Warning' ELSE 'Info' END as severity_hint
    FROM stats WHERE total > 0 ORDER BY metric_value DESC
- name: BGP_ZERO_NEIGHBORS
  type: sql
  severity: Critical
  section_prompt: Flag routers with no BGP neighbors detected.
  query: SELECT d.hostname as device, 0 as metric_value, 'BGP Neighbors Count' as
    metric_name, 'Critical - Zero Neighbors' as severity_hint FROM netops.devices
    d WHERE (d.role ILIKE '%router%' OR d.platform LIKE '%ios%' OR d.platform LIKE
    '%junos%') AND d.hostname NOT IN (SELECT DISTINCT device_name FROM v_bgp_neighbors_auto
    WHERE device_name IS NOT NULL)
- name: BGP_NON_ESTABLISHED_LIST
  type: sql
  severity: Warning
  section_prompt: 'Detailed list of non-Established sessions: device, peer IP/AS,
    state. Critical for Idle/Active/NULL.'
  query: SELECT device_name as device, neighbor_ip as metric_value, CONCAT(neighbor_as,
    ' - ', COALESCE(state, 'NULL')) as metric_name, CASE WHEN COALESCE(LOWER(state),
    '') IN ('idle', 'active', 'connect', 'opensent', '') THEN 'Critical' ELSE 'Warning'
    END as severity_hint FROM v_bgp_neighbors_auto WHERE LOWER(TRIM(COALESCE(state,
    ''))) != 'established' ORDER BY device_name, neighbor_ip
- name: BGP_DATA_AGE
  type: sql
  severity: Info
  section_prompt: Age of latest BGP data per device. Warn >24h, Critical >7d.
  query: SELECT device_name as device, DATEDIFF('day', MAX(created_at), NOW()) as
    metric_value, 'Days Since Last BGP Update' as metric_name, CASE WHEN MAX(created_at)
    < NOW() - INTERVAL '7 days' THEN 'Critical' WHEN MAX(created_at) < NOW() - INTERVAL
    '1 day' THEN 'Warning' ELSE 'Info' END as severity_hint FROM v_bgp_neighbors_auto
    GROUP BY device_name ORDER BY metric_value DESC
- name: BGP_PREFIXES_LOW
  type: sql
  severity: Warning
  section_prompt: Average prefixes received <10 per neighbor (potential peering issue).
  query: SELECT device_name as device, AVG(CAST(prefixes_received AS DOUBLE)) as metric_value,
    'Avg Prefixes/Neighbor' as metric_name, CASE WHEN AVG(prefixes_received) < 10
    THEN 'Warning' ELSE 'Info' END as severity_hint FROM bgp_neighbors WHERE prefixes_received
    IS NOT NULL GROUP BY device_name HAVING COUNT(*) > 0 ORDER BY metric_value ASC
---

# BGP Health Check Profile

Monitors BGP peering health across the network:

## Core Checks
- **Session Uptime**: % down sessions per device
- **Coverage**: Routers missing BGP data
- **Details**: All non-Established peers
- **Freshness**: Data staleness
- **Prefixes**: Low received route counts

Use with `olav --agent audit "run profile bgp_health_check"` for reports.
