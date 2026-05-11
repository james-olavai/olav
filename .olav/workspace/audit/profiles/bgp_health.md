---
name: bgp_health
version: '5.1'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_NEIGHBOR_COUNT
  type: sql
  severity: Critical
  section_prompt: 'Identify and flag any devices reporting zero BGP neighbors. Zero
    neighbors indicates complete BGP session failure on that device. Prioritize investigation:
    check device logs, BGP config, peer reachability, and ''show bgp summary''.'
  query: "SELECT\n  d.hostname AS device,\n  COALESCE(b.cnt, 0) AS metric_value,\n\
    \  'BGP Neighbor Count' AS metric_name,\n  CASE\n    WHEN COALESCE(b.cnt, 0) =\
    \ 0 THEN 'Critical'\n    ELSE 'Info'\n  END AS severity_hint\nFROM netops.devices\
    \ d\nLEFT JOIN (\n  SELECT device_name, COUNT(*) AS cnt\n  FROM netops.v_bgp_neighbors_auto\n\
    \  GROUP BY device_name\n) b ON d.hostname = b.device_name"
- name: BGP_SESSION_STATE
  type: sql
  severity: Warning
  section_prompt: 'Analyze BGP session states from the v_bgp_neighbors_auto view.
    Report per-device breakdown of Established vs non-Established sessions. Flag any
    sessions in Idle, Active, or unknown (NULL/empty) state — these indicate BGP peering
    failures. Include neighbor IPs and ASNs for failing sessions. A healthy network
    should show 100% Established sessions.'
  query: "SELECT\n  device_name AS device,\n  neighbor_ip,\n  neighbor_as,\n  COALESCE(state,\
    \ 'Unknown') AS state,\n  COUNT(*) AS metric_value,\n  'BGP Session State' AS\
    \ metric_name,\n  CASE\n    WHEN state = 'Established' THEN 'Info'\n    WHEN state\
    \ IS NULL OR state = '' THEN 'Warning'\n    ELSE 'Critical'\n  END AS severity_hint\n\
    FROM netops.v_bgp_neighbors_auto\nGROUP BY device_name, neighbor_ip, neighbor_as,\
    \ state\nORDER BY\n  CASE WHEN state = 'Established' THEN 1 ELSE 0 END ASC,\n\
    \  device_name, neighbor_ip"
- name: BGP_DATA_FRESHNESS
  type: sql
  severity: Warning
  section_prompt: 'Report the data freshness per device using the devices.last_seen
    timestamp. Flag devices not seen in the last 24 hours — stale data means the audit
    may miss current BGP failures.'
  query: "SELECT\n  hostname AS device,\n  last_seen,\n  EXTRACT(EPOCH FROM (NOW()\
    \ - last_seen)) / 3600 AS metric_value,\n  'Hours Since Last Seen' AS metric_name,\n\
    \  CASE\n    WHEN last_seen IS NULL THEN 'Critical'\n    WHEN NOW() - last_seen\
    \ > INTERVAL '7 days' THEN 'Critical'\n    WHEN NOW() - last_seen > INTERVAL '24\
    \ hours' THEN 'Warning'\n    ELSE 'Info'\n  END AS severity_hint\nFROM netops.devices\n\
    ORDER BY last_seen DESC NULLS LAST"
---

# BGP Health Audit Profile

This profile audits BGP health across three dimensions:

1. **BGP_NEIGHBOR_COUNT** (Critical): Devices with zero BGP neighbors — indicates complete BGP failure on that device.
2. **BGP_SESSION_STATE** (Warning): Per-session state from `netops.v_bgp_neighbors_auto` — flags any non-Established sessions (Idle, Active, Unknown).
3. **BGP_DATA_FRESHNESS** (Warning): Device data freshness from `netops.devices.last_seen` — flags devices not seen in the last 24 hours.

**Data Sources**: `netops.v_bgp_neighbors_auto` (parsed session state view, columns: device_name/snapshot_id/platform/neighbor_ip/neighbor_as/state/prefixes_received/vendor_family), `netops.devices` (hostname/last_seen).

**Healthy baseline**: 100% Established sessions, fresh data (<24h), all devices reporting neighbors.

**Schema migration note**: Pre-rev-262 the profile referenced `created_at` columns that don't exist on `v_bgp_neighbors_auto` — freshness now derives from `netops.devices.last_seen`. The view itself is point-in-time (snapshot-based), no per-row timestamp.
