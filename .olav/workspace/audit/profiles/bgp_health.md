---
name: bgp_health
version: '5.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_NEIGHBOR_COUNT
  type: sql
  severity: Critical
  section_prompt: 'Identify and flag any devices reporting zero BGP neighbors within
    the audit window. Zero neighbors indicates complete BGP session failure on that
    device. Prioritize investigation: check device logs, BGP config, peer reachability,
    and ''show bgp summary''. Also flag if no recent data was collected (stale data
    risk).'
  query: "SELECT \n  d.hostname AS device,\n  COALESCE(b.cnt, 0) AS metric_value,\n\
    \  'BGP Neighbor Count' AS metric_name,\n  CASE \n    WHEN COALESCE(b.cnt, 0)\
    \ = 0 THEN 'Critical'\n    ELSE 'Info' \n  END AS severity_hint\nFROM netops.devices\
    \ d\nLEFT JOIN (\n  SELECT device_name, COUNT(*) AS cnt\n  FROM netops.v_bgp_neighbors_auto\
    \ \n  GROUP BY device_name\n)\
    \ b ON d.hostname = b.device_name"
- name: BGP_SESSION_STATE
  type: sql
  severity: High
  section_prompt: 'Analyze BGP session states from the v_bgp_neighbors_auto view.
    Report per-device breakdown of Established vs non-Established sessions. Flag any
    sessions in Idle, Active, or unknown (NULL/0) state — these indicate BGP peering
    failures. Include neighbor IPs and ASNs for failing sessions. If data is stale
    (no snapshots in last 24h), note the data freshness issue and report based on
    latest available data. A healthy network should show 100% Established sessions.'
  query: "SELECT\n  device_name AS device,\n  neighbor_ip,\n  neighbor_as,\n  COALESCE(state,\
    \ 'Unknown') AS state,\n  CASE\n    WHEN state = 'Established' THEN 'Info'\n \
    \   WHEN state IS NULL OR state = '0' OR TRIM(state) = '' THEN 'High'\n    ELSE\
    \ 'Critical'\n  END AS severity_hint,\n  MAX(created_at) AS last_seen\nFROM netops.v_bgp_neighbors_auto\n\
    GROUP BY device_name, neighbor_ip, neighbor_as, state\nORDER BY\n  CASE WHEN\
    \ state = 'Established' THEN 1 ELSE 0 END ASC,\n  device_name,\n  neighbor_ip"
- name: BGP_DATA_FRESHNESS
  type: sql
  severity: Medium
  section_prompt: 'Report the data freshness for BGP collection. Show the most recent
    snapshot per device and flag devices with no data in the last 24 hours. Stale
    data means the audit may miss current failures. Recommend running fresh collection
    if any device has no data in the last 24h.'
  query: "SELECT\n  device_name AS device,\n  MAX(created_at) AS last_collected,\n\
    \  COUNT(*) AS total_snapshots,\n  CASE\n    WHEN MAX(created_at) >= NOW() - INTERVAL\
    \ '24 hours' THEN 'Info'\n    WHEN MAX(created_at) >= NOW() - INTERVAL '7 days'\
    \ THEN 'Medium'\n    ELSE 'High'\n  END AS severity_hint,\n  CASE\n    WHEN MAX(created_at)\
    \ >= NOW() - INTERVAL '24 hours' THEN 'Fresh'\n    ELSE 'STALE (>' || CAST(CAST((NOW()\
    \ - MAX(created_at)) AS INTERVAL) AS VARCHAR) || ' old)'\n  END AS freshness_status\n\
    FROM netops.v_bgp_neighbors_auto\nGROUP BY device_name\nORDER BY last_collected ASC"
---

# BGP Health Audit Profile

This profile audits BGP health across three dimensions:

1. **BGP_NEIGHBOR_COUNT** (Critical): Devices with zero BGP neighbors in the collection window — indicates complete BGP failure.
2. **BGP_SESSION_STATE** (High): Per-session state from `v_bgp_neighbors_auto` — flags any non-Established sessions (Idle, Active, Unknown) across all historical data.
3. **BGP_DATA_FRESHNESS** (Medium): Data staleness per device — flags if last collection is >24h old.

**Data Sources**: `bgp_neighbors` (collection window), `v_bgp_neighbors_auto` (parsed session state view), `devices`.

**Healthy baseline**: 100% Established sessions, fresh data (<24h), all devices reporting neighbors.
