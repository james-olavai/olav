---
name: interface_health
version: '1.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: INTERFACE_DOWN
  type: sql
  severity: Critical
  section_prompt: 'Identify operationally down interfaces. A `link_status` other than
    `up` indicates a Layer-1/2 problem (no carrier, admin down, error-disabled). Ignore
    Null0 / Loopback interfaces — those are software-only. Cross-correlate with the
    interface description to assess blast radius (uplink vs access).'
  query: "SELECT\n  device_name AS device,\n  interface,\n  link_status,\n  protocol_status,\n\
    \  COALESCE(description, '') AS description,\n  1 AS metric_value,\n  'Interface\
    \ Status' AS metric_name,\n  CASE\n    WHEN link_status = 'up' THEN 'Info'\n  \
    \  WHEN interface ILIKE 'Null%' OR interface ILIKE 'Loopback%' THEN 'Info'\n  \
    \  WHEN link_status = 'administratively down' THEN 'Warning'\n    ELSE 'Critical'\n\
    \  END AS severity_hint\nFROM netops.v_show_interfaces_auto\nWHERE link_status\
    \ <> 'up'\n  AND interface NOT ILIKE 'Null%'\n  AND interface NOT ILIKE 'Loopback%'\n\
    ORDER BY device_name, interface"
- name: INTERFACE_ERROR_DELTA
  type: sql
  severity: Warning
  section_prompt: 'Compare interface error counters between the two most recent snapshots
    and flag interfaces where errors INCREASED. A cumulative counter > 100 on a long-running
    device proves nothing (could be old); a delta > 10 between snapshots is a real
    rate-of-change signal. When only one snapshot exists, this section is empty by
    design — see SNAPSHOT_RECENCY in device_inventory profile for the cause.'
  query: "WITH snap_pair AS (\n  SELECT snapshot_id\n  FROM (SELECT DISTINCT snapshot_id\
    \ FROM netops.v_show_interfaces_auto)\n  ORDER BY snapshot_id DESC\n  LIMIT 2\n\
    ),\nlatest AS (\n  SELECT * FROM netops.v_show_interfaces_auto\n  WHERE snapshot_id\
    \ = (SELECT MAX(snapshot_id) FROM snap_pair)\n),\nprev AS (\n  SELECT * FROM netops.v_show_interfaces_auto\n\
    \  WHERE snapshot_id IN (\n    SELECT snapshot_id FROM snap_pair\n    EXCEPT SELECT\
    \ MAX(snapshot_id) FROM snap_pair\n  )\n)\nSELECT\n  l.device_name AS device,\n\
    \  l.interface,\n  CASE WHEN p.snapshot_id IS NULL THEN NULL\n       ELSE TRY_CAST(l.input_errors\
    \ AS BIGINT) - TRY_CAST(p.input_errors AS BIGINT) END\n    AS input_errors_delta,\n\
    \  CASE WHEN p.snapshot_id IS NULL THEN NULL\n       ELSE TRY_CAST(l.crc AS BIGINT)\
    \ - TRY_CAST(p.crc AS BIGINT) END\n    AS crc_delta,\n  CASE WHEN p.snapshot_id\
    \ IS NULL THEN NULL\n       ELSE TRY_CAST(l.output_errors AS BIGINT) - TRY_CAST(p.output_errors\
    \ AS BIGINT) END\n    AS output_errors_delta,\n  GREATEST(\n    CASE WHEN p.snapshot_id\
    \ IS NULL THEN 0\n         ELSE TRY_CAST(l.input_errors AS BIGINT) - TRY_CAST(p.input_errors\
    \ AS BIGINT) END,\n    CASE WHEN p.snapshot_id IS NULL THEN 0\n         ELSE TRY_CAST(l.crc\
    \ AS BIGINT) - TRY_CAST(p.crc AS BIGINT) END,\n    CASE WHEN p.snapshot_id IS NULL\
    \ THEN 0\n         ELSE TRY_CAST(l.output_errors AS BIGINT) - TRY_CAST(p.output_errors\
    \ AS BIGINT) END\n  ) AS metric_value,\n  'Interface Error Delta (vs prev snapshot)'\
    \ AS metric_name,\n  CASE\n    WHEN p.snapshot_id IS NULL THEN 'Info'\n    WHEN\
    \ GREATEST(\n      TRY_CAST(l.input_errors AS BIGINT) - TRY_CAST(p.input_errors\
    \ AS BIGINT),\n      TRY_CAST(l.crc AS BIGINT) - TRY_CAST(p.crc AS BIGINT),\n \
    \     TRY_CAST(l.output_errors AS BIGINT) - TRY_CAST(p.output_errors AS BIGINT)\n\
    \    ) > 100 THEN 'Critical'\n    WHEN GREATEST(\n      TRY_CAST(l.input_errors\
    \ AS BIGINT) - TRY_CAST(p.input_errors AS BIGINT),\n      TRY_CAST(l.crc AS BIGINT)\
    \ - TRY_CAST(p.crc AS BIGINT),\n      TRY_CAST(l.output_errors AS BIGINT) - TRY_CAST(p.output_errors\
    \ AS BIGINT)\n    ) > 10 THEN 'Warning'\n    ELSE 'Info'\n  END AS severity_hint\n\
    FROM latest l\nLEFT JOIN prev p ON l.device_name = p.device_name AND l.interface\
    \ = p.interface\nWHERE p.snapshot_id IS NOT NULL\n  AND (\n    TRY_CAST(l.input_errors\
    \ AS BIGINT) > TRY_CAST(p.input_errors AS BIGINT)\n    OR TRY_CAST(l.crc AS BIGINT)\
    \ > TRY_CAST(p.crc AS BIGINT)\n    OR TRY_CAST(l.output_errors AS BIGINT) > TRY_CAST(p.output_errors\
    \ AS BIGINT)\n  )\n  AND l.interface NOT ILIKE 'Null%'\n  AND l.interface NOT ILIKE\
    \ 'Loopback%'\nORDER BY metric_value DESC"
- name: INTERFACE_COUNT_BY_DEVICE
  type: sql
  severity: Info
  section_prompt: 'Per-device interface inventory: total interfaces parsed, how many
    up, how many down. Use this as a sanity check — a device reporting zero interfaces
    suggests a parser failure rather than a real outage. Compare against expected device
    profile (router vs switch).'
  query: "SELECT\n  device_name AS device,\n  COUNT(*) AS metric_value,\n  SUM(CASE\
    \ WHEN link_status = 'up' THEN 1 ELSE 0 END) AS up_count,\n  SUM(CASE WHEN link_status\
    \ <> 'up' AND interface NOT ILIKE 'Null%' AND interface NOT ILIKE 'Loopback%' THEN\
    \ 1 ELSE 0 END) AS physical_down_count,\n  'Interface Count' AS metric_name,\n\
    \  CASE\n    WHEN COUNT(*) = 0 THEN 'Warning'\n    ELSE 'Info'\n  END AS severity_hint\n\
    FROM netops.v_show_interfaces_auto\nGROUP BY device_name\nORDER BY device_name"
---

# Interface Health Audit Profile

This profile audits L1/L2 interface health across all devices:

1. **INTERFACE_DOWN** (Critical): Operationally down physical interfaces — flags any non-software interface with `link_status != 'up'`.
2. **INTERFACE_ERROR_DELTA** (Warning): Interfaces where input_errors / crc / output_errors INCREASED between the two most recent snapshots. Cumulative counters alone are noise (a 6-month-old device with 250 input_errors is fine); delta > 10 per window is a real rate-of-change signal. Single-snapshot environments emit no findings here (see device_inventory.SNAPSHOT_RECENCY).
3. **INTERFACE_COUNT_BY_DEVICE** (Info): Per-device interface inventory — catches parser failures (device with 0 interfaces is suspicious).

**Data Source**: `netops.v_show_interfaces_auto` (parsed Cisco/Juniper `show interfaces` view; columns: device_name, interface, link_status, protocol_status, description, ip_address, input_errors, crc, output_errors, plus many traffic counters).

**Healthy baseline**: All physical interfaces with descriptions are `up`, error counters near zero, every device reports interface data.

**Notes**:
- `Null0`, `Loopback*`, etc. are software interfaces — excluded from the down-state check.
- Error counters use `TRY_CAST` because the parsed values are stored as strings in DuckDB.
- `INTERFACE_COUNT_BY_DEVICE` is intentionally `Info`-severity — it's a diagnostic, not an alert.
