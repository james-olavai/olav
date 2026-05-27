---
name: bgp_health
version: '6.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_NEIGHBOR_COUNT
  type: sql
  severity: Critical
  section_prompt: 'Identify and flag any devices reporting zero BGP neighbors. Zero
    neighbors indicates complete BGP session failure on that device. Prioritize investigation:
    check device logs, BGP config, peer reachability, and ''show ip bgp summary''.'
  query: |
    SELECT
      d.hostname AS device,
      COALESCE(b.cnt, 0) AS metric_value,
      'BGP Neighbor Count' AS metric_name,
      CASE
        WHEN COALESCE(b.cnt, 0) = 0 THEN 'Critical'
        ELSE 'Info'
      END AS severity_hint
    FROM netops.devices d
    LEFT JOIN (
      SELECT device_name, COUNT(*) AS cnt
      FROM netops.v_show_ip_bgp_summary_auto
      GROUP BY device_name
    ) b ON d.hostname = b.device_name
- name: BGP_SESSION_STATE
  type: sql
  severity: Warning
  section_prompt: 'Analyze BGP session states. Report per-device breakdown of Established
    vs non-Established sessions. A numeric state_or_prefixes_received value means
    Established (prefix count); a text value (Idle, Active, etc.) means the session
    is not up. Flag any non-Established sessions — include neighbor IP and AS for
    failing sessions. A healthy network shows 100% Established sessions.'
  query: |
    SELECT
      device_name AS device,
      bgp_neighbor,
      neighbor_as,
      CASE
        WHEN TRY_CAST(state_or_prefixes_received AS INT) IS NOT NULL THEN 'Established'
        ELSE COALESCE(state_or_prefixes_received, 'Unknown')
      END AS state,
      state_or_prefixes_received AS raw_value,
      'BGP Session State' AS metric_name,
      CASE
        WHEN TRY_CAST(state_or_prefixes_received AS INT) IS NOT NULL THEN 'Info'
        WHEN state_or_prefixes_received IS NULL OR state_or_prefixes_received = '' THEN 'Warning'
        ELSE 'Critical'
      END AS severity_hint
    FROM netops.v_show_ip_bgp_summary_auto
    ORDER BY
      CASE WHEN TRY_CAST(state_or_prefixes_received AS INT) IS NOT NULL THEN 1 ELSE 0 END ASC,
      device_name, bgp_neighbor
- name: BGP_DATA_FRESHNESS
  type: sql
  severity: Warning
  section_prompt: 'Report the data freshness per device using the devices.last_seen
    timestamp. Flag devices not seen in the last 24 hours — stale data means the audit
    may miss current BGP failures.'
  query: |
    SELECT
      hostname AS device,
      last_seen,
      EXTRACT(EPOCH FROM (NOW() - last_seen)) / 3600 AS metric_value,
      'Hours Since Last Seen' AS metric_name,
      CASE
        WHEN last_seen IS NULL THEN 'Critical'
        WHEN NOW() - last_seen > INTERVAL '7 days' THEN 'Critical'
        WHEN NOW() - last_seen > INTERVAL '24 hours' THEN 'Warning'
        ELSE 'Info'
      END AS severity_hint
    FROM netops.devices
    ORDER BY last_seen DESC NULLS LAST
---

# BGP Health Audit Profile

This profile audits BGP health across three dimensions:

1. **BGP_NEIGHBOR_COUNT** (Critical): Devices with zero BGP neighbors — indicates complete BGP failure on that device.
2. **BGP_SESSION_STATE** (Warning): Per-session state from `netops.v_show_ip_bgp_summary_auto` — flags any non-Established sessions (Idle, Active, Unknown). Established is indicated by a numeric `state_or_prefixes_received` (prefix count); any text value means the session is not up.
3. **BGP_DATA_FRESHNESS** (Warning): Device data freshness from `netops.devices.last_seen` — flags devices not seen in the last 24 hours.

**Data Sources**:
- `netops.v_show_ip_bgp_summary_auto` — parsed from `show ip bgp summary`; columns: `device_name`, `snapshot_id`, `bgp_neighbor`, `neighbor_as`, `up_down`, `state_or_prefixes_received` (VARCHAR: numeric=Established, text=state name)
- `netops.devices` — `hostname`, `last_seen`

**Healthy baseline**: 100% Established sessions, fresh data (<24h), all devices reporting neighbors.
