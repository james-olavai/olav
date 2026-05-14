---
name: device_inventory
version: '1.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: DEVICE_LAST_SEEN
  type: sql
  severity: Critical
  section_prompt: 'Report all devices and their last-seen timestamp. Flag devices not
    polled in the last 24 hours as Warning; not polled in 7 days as Critical. Stale
    devices in the inventory may mean the collector is broken for that device, or that
    the device was retired but not removed from inventory.'
  query: "SELECT\n  hostname AS device,\n  last_seen,\n  ROUND(EXTRACT(EPOCH FROM (NOW()\
    \ - last_seen)) / 3600.0, 1) AS metric_value,\n  'Hours Since Last Seen' AS metric_name,\n\
    \  CASE\n    WHEN last_seen IS NULL THEN 'Critical'\n    WHEN NOW() - last_seen\
    \ > INTERVAL '7 days' THEN 'Critical'\n    WHEN NOW() - last_seen > INTERVAL '24\
    \ hours' THEN 'Warning'\n    ELSE 'Info'\n  END AS severity_hint\nFROM netops.devices\n\
    ORDER BY last_seen ASC NULLS FIRST"
- name: DEVICE_PARSE_COVERAGE
  type: sql
  severity: Warning
  section_prompt: 'For each device, count how many distinct parsed-output views (v_show_*)
    contain at least one row. Devices with very low coverage suggest a parser/template
    gap, not a real fault. Cross-correlate against `netops.devices.platform` so that
    parser-gap findings are framed by platform.'
  query: "WITH dv AS (\n  SELECT d.hostname, d.platform\n  FROM netops.devices d\n\
    ),\nparsed AS (\n  SELECT DISTINCT device_name, command\n  FROM netops.parsed_outputs\n\
    )\nSELECT\n  dv.hostname AS device,\n  dv.platform,\n  COUNT(parsed.command) AS\
    \ metric_value,\n  'Distinct Parsed Commands' AS metric_name,\n  CASE\n    WHEN\
    \ COUNT(parsed.command) = 0 THEN 'Critical'\n    WHEN COUNT(parsed.command) < 5\
    \ THEN 'Warning'\n    ELSE 'Info'\n  END AS severity_hint\nFROM dv\nLEFT JOIN parsed\
    \ ON parsed.device_name = dv.hostname\nGROUP BY dv.hostname, dv.platform\nORDER\
    \ BY metric_value ASC"
- name: SNAPSHOT_RECENCY
  type: sql
  severity: Warning
  section_prompt: 'Surface the most recent snapshot per device from parsed_outputs.
    The audit reads from views that aggregate across snapshots — a device whose newest
    snapshot is days old means audit findings for that device reflect stale data, even
    if the device itself is currently reachable.'
  query: "SELECT\n  device_name AS device,\n  MAX(snapshot_id) AS latest_snapshot,\n\
    \  COUNT(DISTINCT snapshot_id) AS metric_value,\n  'Distinct Snapshots' AS metric_name,\n\
    \  CASE\n    WHEN COUNT(DISTINCT snapshot_id) = 0 THEN 'Critical'\n    WHEN COUNT(DISTINCT\
    \ snapshot_id) < 2 THEN 'Warning'\n    ELSE 'Info'\n  END AS severity_hint\nFROM\
    \ netops.parsed_outputs\nGROUP BY device_name\nORDER BY metric_value ASC"
---

# Device Inventory Audit Profile

This profile audits the inventory + parser-coverage health of the device fleet —
a meta-audit that catches gaps in the collection pipeline before they masquerade
as a clean bill of health on every other profile.

1. **DEVICE_LAST_SEEN** (Critical): Devices not polled recently — `netops.devices.last_seen`.
2. **DEVICE_PARSE_COVERAGE** (Warning): How many distinct commands have parsed output per device. Low coverage = parser/template gap.
3. **SNAPSHOT_RECENCY** (Warning): Snapshot count per device. Zero or one snapshot suggests collection issues.

**Data Sources**:
- `netops.devices` (hostname, platform, last_seen)
- `netops.parsed_outputs` (device_name, command, snapshot_id — the raw parsed-output store keyed by command)

**Healthy baseline**: every device polled within the last 24 hours, parses ≥ 5 distinct commands, has ≥ 2 snapshots.

**Why this matters**: every other audit profile (BGP / OSPF / interfaces) reads from the parsed view layer.
If a device's parsers fail, those audits silently report "no findings" and the device looks healthy when it isn't. This profile detects that failure mode.
