---
name: bgp_health_full
version: '4.0'
persist_findings_to_db: false
deprecated: true   # rev 266: variant of bgp_health.md with stale SQL (FROM v_bgp_neighbors_auto unqualified, MAX(created_at) on view that has no created_at column). Use bgp_health.md for canonical BGP health audit.
max_findings_per_job: 50
jobs:
- name: BGP_SESSIONS_DOWN_PCT
  type: sql
  severity: Critical
  section_prompt: 'Calculate the percentage of BGP sessions not in ''Established''
    state per device. High percentages indicate widespread peering issues. Use thresholds:
    Critical >50%, Warning >20%, Info otherwise. Include total neighbors and down
    count for context.'
  query: WITH stats AS ( SELECT device_name, COUNT(*) as total, SUM(CASE WHEN state
    = 'Established' OR LOWER(TRIM(COALESCE(state, ''))) = 'established' THEN 1 ELSE
    0 END) as up FROM v_bgp_neighbors_auto GROUP BY device_name ) SELECT device_name
    as device, ROUND((1.0 * (total - up) / total * 100), 2) as metric_value, '% BGP
    Sessions Down' as metric_name, total as total_neighbors, (total - up) as down_neighbors,
    CASE WHEN ((total - up)*1.0 / total * 100) > 50 THEN 'Critical' WHEN ((total -
    up)*1.0 / total * 100) > 20 THEN 'Warning' ELSE 'Info' END as severity_hint FROM
    stats WHERE total > 0 ORDER BY metric_value DESC
- name: BGP_ZERO_NEIGHBORS
  type: sql
  severity: Critical
  section_prompt: Identify BGP-capable devices with zero neighbors reported. This
    indicates complete BGP failure or no data collection. Cross-reference with netops.devices.
  query: SELECT d.hostname as device, 0 as metric_value, 'BGP Neighbors' as metric_name,
    'Critical - No BGP Neighbors' as severity_hint FROM netops.devices d WHERE d.role
    ILIKE '%router%' OR d.platform ILIKE '%cisco%' AND hostname NOT IN (SELECT DISTINCT
    device_name FROM v_bgp_neighbors_auto)
- name: BGP_NON_ESTABLISHED_SESSIONS
  type: sql
  severity: Warning
  section_prompt: 'List all non-Established BGP sessions with details: device, neighbor_ip,
    neighbor_as, state. Prioritize Critical for Idle/Active/NULL states.'
  query: SELECT device_name as device, neighbor_ip, neighbor_as, COALESCE(state, 'NULL')
    as state, CASE WHEN state IS NULL OR LOWER(state) IN ('idle', 'active', 'connect',
    'opensent') THEN 'Critical' ELSE 'Warning' END as severity_hint, snapshot_id FROM
    v_bgp_neighbors_auto WHERE state != 'Established' AND LOWER(TRIM(COALESCE(state,
    ''))) != 'established' ORDER BY device_name, neighbor_ip
- name: BGP_DATA_FRESHNESS
  type: sql
  severity: Info
  section_prompt: Check recency of BGP data per device. Flag stale data (>24h old)
    as it may mask current issues.
  query: SELECT device_name as device, MAX(created_at) as metric_value, 'Last BGP
    Snapshot' as metric_name, CASE WHEN MAX(created_at) < NOW() - INTERVAL '24 hours'
    THEN 'Warning' WHEN MAX(created_at) < NOW() - INTERVAL '7 days' THEN 'Critical'
    ELSE 'Info' END as severity_hint FROM v_bgp_neighbors_auto GROUP BY device_name
    ORDER BY metric_value ASC
---

# BGP Health Full Audit Profile

Comprehensive BGP health monitoring focusing on session states, coverage, and data freshness.

## Key Checks:
- **BGP_SESSIONS_DOWN_PCT**: % down sessions per device (thresholds: >50% Critical, >20% Warning)
- **BGP_ZERO_NEIGHBORS**: Devices with no BGP data
- **BGP_NON_ESTABLISHED_SESSIONS**: Detailed list of failed sessions
- **BGP_DATA_FRESHNESS**: Stale data detection

**Expected Healthy State**: 0% down, all sessions Established, fresh data (<24h).

**Investigation Tips**:
- Check `show bgp summary` / `show ip bgp neighbors`
- Verify peer reachability (ping, IGP)
- Review logs for hold-timer expiry, AS mismatch
