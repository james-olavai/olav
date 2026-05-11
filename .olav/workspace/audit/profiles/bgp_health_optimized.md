---
name: bgp_health_optimized
version: '4.0'
persist_findings_to_db: false
deprecated: true   # rev 266: variant of bgp_health.md with stale SQL (FROM v_bgp_neighbors_auto unqualified, MAX(created_at) on view that has no created_at column). Use bgp_health.md for canonical BGP health audit.
max_findings_per_job: 50
jobs:
- name: BGP_ESTABLISHED_PCT
  type: sql
  severity: Critical
  section_prompt: Per-device % of BGP neighbors in Established state. Low values indicate
    peering issues. Critical <30%, Warning <50%, Info otherwise. Include counts for
    context.
  query: WITH stats AS ( SELECT device_name, COUNT(*) as total_neighbors, SUM(CASE
    WHEN UPPER(TRIM(COALESCE(state, ''))) = 'ESTABLISHED' THEN 1 ELSE 0 END) as established
    FROM v_bgp_neighbors_auto GROUP BY device_name ) SELECT device_name as device,
    ROUND(established * 100.0 / total_neighbors, 2) as metric_value, '% BGP Neighbors
    Established' as metric_name, CASE WHEN (established * 100.0 / total_neighbors)
    < 30 THEN 'Critical' WHEN (established * 100.0 / total_neighbors) < 50 THEN 'Warning'
    ELSE 'Info' END as severity_hint FROM stats WHERE total_neighbors > 0 ORDER BY
    metric_value ASC
- name: BGP_ZERO_NEIGHBORS
  type: sql
  severity: Critical
  section_prompt: Identify routers/switches expected to run BGP but reporting zero
    neighbors. Indicates config issue, no peers, or data gap.
  query: SELECT hostname as device, 0 as metric_value, 'BGP Neighbors Count' as metric_name,
    'Critical - Zero Neighbors' as severity_hint FROM netops.devices WHERE (role ILIKE
    '%router%' OR platform ILIKE '%ios%' OR platform ILIKE '%eos%' OR platform ILIKE
    '%junos%') AND hostname NOT IN (SELECT DISTINCT device_name FROM v_bgp_neighbors_auto)
- name: BGP_NON_ESTABLISHED_SESSIONS
  type: sql
  severity: Warning
  section_prompt: Detail non-Established BGP sessions. Critical for problematic states
    like Idle/Active/Connect.
  query: 'SELECT device_name as device, neighbor_ip || '' (AS'' || neighbor_as ||
    '', State: '' || COALESCE(state, ''NULL'') || '')'' as metric_value, ''BGP Peer
    Detail'' as metric_name, CASE WHEN UPPER(TRIM(COALESCE(state, ''''))) IN (''IDLE'',
    ''CONNECT'', ''ACTIVE'', ''OPENSENT'') OR state IS NULL THEN ''Critical'' ELSE
    ''Warning'' END as severity_hint FROM v_bgp_neighbors_auto WHERE UPPER(TRIM(COALESCE(state,
    ''''))) != ''ESTABLISHED'' ORDER BY device_name, neighbor_ip'
- name: BGP_DATA_FRESHNESS
  type: sql
  severity: Info
  section_prompt: Age of latest BGP snapshot per device. Stale data (>24h Warning,
    >7d Critical) may hide current problems.
  query: SELECT device_name as device, EXTRACT(EPOCH FROM (NOW() - MAX(created_at)))
    / 3600.0 as metric_value, 'BGP Data Age (hours)' as metric_name, CASE WHEN MAX(created_at)
    < NOW() - INTERVAL '24 hours' THEN 'Warning' WHEN MAX(created_at) < NOW() - INTERVAL
    '7 days' THEN 'Critical' ELSE 'Info' END as severity_hint FROM v_bgp_neighbors_auto
    GROUP BY device_name ORDER BY metric_value DESC
---

# BGP Health Optimized Profile

## Overview
Comprehensive BGP monitoring profile optimized for current data schema (v_bgp_neighbors_auto).

## Checks
- **BGP_ESTABLISHED_PCT**: % Established neighbors per device (<30% Critical, <50% Warning)
- **BGP_ZERO_NEIGHBORS**: BGP-capable devices with no neighbor data
- **BGP_NON_ESTABLISHED_SESSIONS**: Detailed list of down/idle sessions
- **BGP_DATA_FRESHNESS**: Snapshot recency per device

**Thresholds data-driven**: Based on P50=47%, mean=33% established across 6 devices (low sample confidence).
