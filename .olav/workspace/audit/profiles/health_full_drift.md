---
name: health_full_drift
version: "2.0"
description: >
  Comprehensive health audit + adaptive anomaly detection + incident clustering.
  CPU/Memory use per-device Z-score baseline (no fixed thresholds).
  Incident engine correlates events into fault clusters with topology root-cause.
  Covers: CPU, Memory, Interface, BGP, OSPF, STP, Syslog, drift, config changes.
  Total: 15 jobs + post-processing incident clustering.
persist_findings_to_db: true
deprecated: true   # rev 266: SQL references pre-netops-schema-migration tables (FROM parsed_outputs unqualified, etc.); needs full rewrite per current netops.* schema. 15-job profile is structurally rich but not runnable as-is. Use bgp_health.md as a working canonical example.
max_findings_per_job: 100
run_incident_clustering: true
snapshot_resolution: 1d
# gap auto-derived: 1d × 6 = 1440 min → one cluster per calendar day

jobs:

# ─────────────────────────────────────────────────────────────
# 1. Current-State Checks
# ─────────────────────────────────────────────────────────────

- name: CPU_Anomaly
  type: anomaly
  severity: Warning
  # RAW-05: if parsed_outputs has no CPU rows but raw_output_store does, surface
  # raw_only_data sentinels so a TextFSM parse failure doesn't look like a
  # clean bill of health.
  raw_fallback: true
  section_prompt: >
    Identify devices with CPU behaviour statistically anomalous relative to their own
    history (adaptive Z-score, not a fixed threshold). A device that normally runs
    at 80% CPU is healthy; one that spikes from 20% to 65% is flagged regardless
    of absolute value. Positive z_score = CPU spike; negative = sudden drop
    (possible process crash, route withdrawal, or maintenance event).
    Show z_score, current cpu value, and 1-min/5-min averages where available.
  anomaly:
    method: zscore
    threshold: 2.5
    group_col: device_name
    metric_cols: [cpu_5sec]
    query: >
      SELECT device_name,
             CAST(json_extract(parsed_data, '$.five_sec_cpu') AS DOUBLE) AS cpu_5sec,
             CAST(json_extract(parsed_data, '$.one_min_cpu')  AS DOUBLE) AS cpu_1min,
             CAST(json_extract(parsed_data, '$.five_min_cpu') AS DOUBLE) AS cpu_5min,
             snapshot_id,
             created_at
      FROM parsed_outputs
      WHERE command ILIKE '%processes cpu%'
        AND json_extract(parsed_data, '$.five_sec_cpu') IS NOT NULL
        AND created_at >= NOW() - INTERVAL :window
      ORDER BY device_name, created_at

- name: Memory_Anomaly
  type: anomaly
  severity: Warning
  # RAW-05: mirror the CPU_Anomaly flag — `show memory` parsing is another
  # common failure mode on non-IOS platforms.
  raw_fallback: true
  section_prompt: >
    Identify devices with memory utilization statistically anomalous vs their own
    historical baseline. Sustained upward drift across multiple consecutive snapshots
    is a strong memory-leak signal — the z_score will increase with each snapshot.
    Flag also sudden drops (possible process restart / memory reclaim).
    Show memory_used_pct, free_mb, z_score, and snapshot timeline.
  anomaly:
    method: zscore
    threshold: 2.5
    group_col: device_name
    metric_cols: [memory_used_pct]
    query: >
      SELECT device_name,
             ROUND(CAST(json_extract(parsed_data,'$.used_mem') AS DOUBLE) /
                   NULLIF(CAST(json_extract(parsed_data,'$.total_mem') AS DOUBLE),0)*100,1) AS memory_used_pct,
             ROUND((CAST(json_extract(parsed_data,'$.total_mem') AS DOUBLE) -
                    CAST(json_extract(parsed_data,'$.used_mem')  AS DOUBLE)) / 1024, 0) AS free_mb,
             snapshot_id,
             created_at
      FROM parsed_outputs
      WHERE command ILIKE '%memory%'
        AND json_extract(parsed_data,'$.used_mem') IS NOT NULL
        AND created_at >= NOW() - INTERVAL :window
      ORDER BY device_name, created_at

- name: Interface_Down
  type: sql
  severity: Critical
  section_prompt: >
    List all non-up physical interfaces (excluding Loopback/Management/Vlan/Tunnel).
    Count failure count per device. Multiple simultaneous interface-downs on the same device may indicate a module failure or upstream link cut.
  query: >
    SELECT device_name, interface, status, description
    FROM interfaces
    WHERE status != 'up'
      AND interface NOT ILIKE 'Loopback%'
      AND interface NOT ILIKE 'Management%'
      AND interface NOT ILIKE 'Vlan%'
      AND interface NOT ILIKE 'Tunnel%'
      AND created_at >= NOW() - INTERVAL :window
    ORDER BY device_name, interface

- name: BGP_Not_Established
  type: sql
  severity: Critical
  section_prompt: >
    List all BGP neighbors not in Established state. Identify affected AS numbers;
    determine whether the fault impacts internet egress, MPLS backbone, or iBGP full-mesh.
    Correlate with Interface_Down findings to confirm physical root cause.
  query: >
    SELECT device_name, neighbor_ip, neighbor_as, state
    FROM bgp_neighbors
    WHERE state != 'Established'
      AND created_at >= NOW() - INTERVAL :window
    ORDER BY device_name

- name: OSPF_Not_Full
  type: sql
  severity: Warning
  section_prompt: >
    List OSPF neighbors not in FULL or 2WAY state. Flag multiple devices in the same area
    losing adjacency simultaneously (network segmentation risk).
    LOADING state stuck indicates MTU mismatch or oversized LSA database.
  query: >
    SELECT device_name, neighbor_id, neighbor_ip, interface, state
    FROM ospf_neighbors
    WHERE state NOT IN ('FULL', '2WAY')
      AND created_at >= NOW() - INTERVAL :window
    ORDER BY device_name

- name: STP_Error_Disable
  type: sql
  severity: Critical
  section_prompt: >
    List switch ports in err-disable state. Identify the most common reasons (BPDU Guard, Port Security, Loop Guard).
    Trunk ports in err-disable cause multi-VLAN outages and must be treated as Priority-1.
    Recommend confirming root cause before issuing shutdown/no shutdown or enabling errdisable recovery.
  query: >
    SELECT device_name, interface, status, description
    FROM interfaces
    WHERE (status ILIKE '%err%disable%' OR status ILIKE '%errdisable%')
      AND created_at >= NOW() - INTERVAL :window
    ORDER BY device_name, interface

- name: Critical_Syslog
  type: lancedb
  severity: Critical
  section_prompt: >
    List semantically matched critical syslog entries. Identify recurring fault keywords.
    Correlate log-source devices with those appearing in Interface_Down or BGP_Not_Established
    to validate alarm origin and support root-cause analysis.
  semantic_query: >
    critical error alert failure interface down link BGP reset flap
    memory OOM spanning-tree BPDU err-disable chassis hardware fault
  threshold: 0.82

# ─────────────────────────────────────────────────────────────
# 2. DB Data Drift Detection (Cross-Snapshot Drift Checks)
# Compare with previous snapshot, capture metric mutations / state flips / log surges
# ─────────────────────────────────────────────────────────────

- name: CPU_Drift
  type: sql
  severity: Warning
  section_prompt: >
    List devices where 5-second CPU changed significantly vs the previous snapshot (drift alert).
    Output includes `cpu_delta`, `time_gap_h`, and `cpu_delta_per_hour` columns.
    Use `cpu_delta_per_hour` as the primary signal — a large raw delta over a very long gap
    may be insignificant, while a small delta in 30 minutes is a spike.
    Positive delta = CPU spike; negative delta = sudden CPU drop (possible process restart or BGP withdrawal).
    `cpu_delta_per_hour` >= 20 should be flagged Critical; >= 5 is Warning.
  query: >
    WITH ranked AS (
      SELECT device_name,
             snapshot_id,
             created_at,
             CAST(json_extract(parsed_data, '$.five_sec_cpu') AS DOUBLE) AS cpu,
             ROW_NUMBER() OVER (PARTITION BY device_name ORDER BY snapshot_id DESC) AS rn
      FROM parsed_outputs
      WHERE command ILIKE '%processes cpu%'
        AND json_extract(parsed_data, '$.five_sec_cpu') IS NOT NULL
    )
    SELECT curr.device_name,
           curr.snapshot_id  AS current_snapshot,
           prev.snapshot_id  AS prev_snapshot,
           ROUND(curr.cpu, 1) AS cpu_now,
           ROUND(prev.cpu, 1) AS cpu_before,
           ROUND(curr.cpu - prev.cpu, 1) AS cpu_delta,
           ROUND(EXTRACT(EPOCH FROM (curr.created_at - prev.created_at)) / 3600.0, 2)
               AS time_gap_h,
           ROUND((curr.cpu - prev.cpu) /
                 NULLIF(EXTRACT(EPOCH FROM (curr.created_at - prev.created_at)) / 3600.0, 0), 2)
               AS cpu_delta_per_hour
    FROM ranked curr
    JOIN ranked prev
      ON curr.device_name = prev.device_name AND prev.rn = 2
    WHERE curr.rn = 1
      AND ABS(curr.cpu - prev.cpu) >= 5
    ORDER BY ABS(curr.cpu - prev.cpu) DESC

- name: Memory_Drift
  type: sql
  severity: Warning
  section_prompt: >
    List devices where memory utilization changed by >=10% vs the previous snapshot.
    Sustained positive drift across multiple consecutive snapshots is a strong memory-leak signal;
    recommend process-level investigation.
  query: >
    WITH ranked AS (
      SELECT device_name,
             snapshot_id,
             created_at,
             ROUND(CAST(json_extract(parsed_data,'$.used_mem') AS DOUBLE) /
                   NULLIF(CAST(json_extract(parsed_data,'$.total_mem') AS DOUBLE),0)*100,1) AS mem_pct,
             ROW_NUMBER() OVER (PARTITION BY device_name ORDER BY snapshot_id DESC) AS rn
      FROM parsed_outputs
      WHERE command ILIKE '%memory%'
        AND json_extract(parsed_data,'$.used_mem') IS NOT NULL
        AND json_extract(parsed_data,'$.total_mem') IS NOT NULL
    )
    SELECT curr.device_name,
           curr.snapshot_id  AS current_snapshot,
           prev.snapshot_id  AS prev_snapshot,
           curr.mem_pct      AS mem_now,
           prev.mem_pct      AS mem_before,
           ROUND(curr.mem_pct - prev.mem_pct, 1) AS mem_delta,
           ROUND(EXTRACT(EPOCH FROM (curr.created_at - prev.created_at)) / 3600.0, 2)
               AS time_gap_h,
           ROUND((curr.mem_pct - prev.mem_pct) /
                 NULLIF(EXTRACT(EPOCH FROM (curr.created_at - prev.created_at)) / 3600.0, 0), 3)
               AS mem_delta_pct_per_hour
    FROM ranked curr
    JOIN ranked prev
      ON curr.device_name = prev.device_name AND prev.rn = 2
    WHERE curr.rn = 1
      AND ABS(curr.mem_pct - prev.mem_pct) >= 3
    ORDER BY ABS(curr.mem_pct - prev.mem_pct) DESC

- name: Interface_State_Drift
  type: sql
  severity: Warning
  section_prompt: >
    Use raw_diffs to detect devices where interface state lines (containing 'line protocol' or 'is up/down') changed between snapshots.
    Positive added_count = new down lines (interface fault); positive removed_count = down lines gone (interface recovered).
    High-frequency flapping (same interface in multiple diffs) indicates physical-layer instability.
  query: >
    SELECT device_name,
           snapshot_id_1 AS snap_before,
           snapshot_id_2 AS snap_after,
           added_count,
           removed_count,
           added_count + removed_count AS total_delta,
           SUBSTR(diff_content, 1, 800) AS diff_preview
    FROM raw_diffs
    WHERE command ILIKE '%show interfaces%'
      AND (added_count + removed_count) > 0
      AND (diff_content ILIKE '%line protocol%'
           OR diff_content ILIKE '% is up%'
           OR diff_content ILIKE '% is down%'
           OR diff_content ILIKE '%administratively down%')
    ORDER BY total_delta DESC, device_name

- name: BGP_Drift
  type: sql
  severity: Critical
  section_prompt: >
    Use raw_diffs to detect snapshot pairs where BGP neighbor state lines changed.
    'Established' deleted or 'Idle'/'Active' added indicates a BGP session flap.
    Correlate with Interface_State_Drift to determine whether triggered by an underlying link failure.
  query: >
    SELECT device_name,
           snapshot_id_1 AS snap_before,
           snapshot_id_2 AS snap_after,
           added_count,
           removed_count,
           SUBSTR(diff_content, 1, 800) AS diff_preview
    FROM raw_diffs
    WHERE command ILIKE '%bgp%'
      AND (added_count + removed_count) > 0
      AND (diff_content ILIKE '%Established%'
           OR diff_content ILIKE '%Idle%'
           OR diff_content ILIKE '%Active%'
           OR diff_content ILIKE '%OpenSent%')
    ORDER BY (added_count + removed_count) DESC, device_name

- name: OSPF_Drift
  type: sql
  severity: Warning
  section_prompt: >
    Use raw_diffs to detect snapshot pairs where OSPF neighbor state lines changed.
    'FULL' deleted or 'LOADING'/'EXSTART'/'DOWN' added indicates adjacency loss.
    Multiple devices in the same area experiencing simultaneous OSPF_Drift: prioritize area-level connectivity investigation.
  query: >
    SELECT device_name,
           snapshot_id_1 AS snap_before,
           snapshot_id_2 AS snap_after,
           added_count,
           removed_count,
           SUBSTR(diff_content, 1, 800) AS diff_preview
    FROM raw_diffs
    WHERE command ILIKE '%ospf%'
      AND (added_count + removed_count) > 0
      AND (
        -- ISSUE-007: require directional state change, not just keyword presence.
        -- Catches: FULL removed AND non-FULL added (same diff hunk)
        regexp_matches(diff_content,
          '(?s)\n?-[^\n]*(FULL|Full)[^\n]*\n\+[^\n]*(LOADING|EXSTART|Loading|ExStart|Down|DOWN|Attempt|ATTEMPT|Init|INIT)[^\n]*')
        -- Also catches: a non-FULL state line was newly added (neighbor appeared in bad state)
        OR regexp_matches(diff_content,
          '(?m)^\+[^\n]*(LOADING|EXSTART|Loading|ExStart|Down|DOWN|Attempt|ATTEMPT|Init|INIT)[^\n]*')
      )
    ORDER BY (added_count + removed_count) DESC, device_name

- name: STP_Drift
  type: sql
  severity: Warning
  section_prompt: >
    Use raw_diffs to detect spanning-tree topology changes: port role/state transitions (FWD/BLK/ROOT/ALT/ERR) and new err-disable state lines.
    Repeated STP topology changes within a short window are a precursor to bridging loops; investigate immediately.
  query: >
    SELECT device_name,
           snapshot_id_1 AS snap_before,
           snapshot_id_2 AS snap_after,
           added_count,
           removed_count,
           SUBSTR(diff_content, 1, 800) AS diff_preview
    FROM raw_diffs
    WHERE command ILIKE '%spanning-tree%'
      AND (added_count + removed_count) > 0
      AND (diff_content ILIKE '%FWD%'
           OR diff_content ILIKE '%BLK%'
           OR diff_content ILIKE '%ROOT%'
           OR diff_content ILIKE '%err-disable%'
           OR diff_content ILIKE '%Topology%change%')
    ORDER BY (added_count + removed_count) DESC, device_name

- name: Log_Spike
  type: sql
  severity: Warning
  section_prompt: >
    Use raw_diffs to detect syslog (show logging) content spikes between snapshots.
    High added_count indicates a burst of new alarm log lines; combine with Critical_Syslog
    semantic search for root-cause analysis. Log spike >50 new lines requires immediate investigation.
  query: >
    SELECT device_name,
           snapshot_id_1 AS snap_before,
           snapshot_id_2 AS snap_after,
           added_count   AS new_log_lines,
           removed_count AS purged_log_lines,
           SUBSTR(diff_content, 1, 1200) AS diff_preview
    FROM raw_diffs
    WHERE command ILIKE '%show logging%'
      AND added_count > 10
    ORDER BY added_count DESC, device_name

# ─────────────────────────────────────────────────────────────
# 3. Configuration Changes (Config Drift)
# ─────────────────────────────────────────────────────────────

- name: Config_Drift
  type: sql
  severity: Warning
  section_prompt: >
    List configuration change records (running-config / show configuration) within the time window.
    Sum added/removed lines per device; flag total_changes > 50 as high-risk change.
    Cross-reference change timestamps with BGP_Drift / OSPF_Drift onset times to identify change-induced outages.
  query: >
    SELECT device_name,
           command,
           snapshot_id_1 AS snap_before,
           snapshot_id_2 AS snap_after,
           added_count,
           removed_count,
           added_count + removed_count AS total_changes,
           SUBSTR(diff_content, 1, 1200) AS diff_preview
    FROM raw_diffs
    WHERE (command ILIKE '%running-config%'
           OR command ILIKE '%show configuration%'
           OR command ILIKE '%display current-configuration%')
      AND added_count + removed_count > 0
    ORDER BY total_changes DESC
---

## Network Full-Health + Drift Audit Profile

Comprehensive health audit + cross-snapshot DB drift detection, **15 jobs** in total.

### Job Coverage

| # | Job | Type | Severity | Monitors |
|---|-----|------|----------|----------|
| 1 | CPU_High | SQL | Warning/Critical | Real-time CPU utilization >75% |
| 2 | Memory_High | SQL | Warning/Critical | Real-time memory utilization >80% |
| 3 | Interface_Down | SQL | Critical | Non-up physical interfaces |
| 4 | BGP_Not_Established | SQL | Critical | BGP neighbors not in Established state |
| 5 | OSPF_Not_Full | SQL | Warning | OSPF adjacencies not in FULL/2WAY |
| 6 | STP_Error_Disable | SQL | Critical | Ports in err-disable state |
| 7 | Critical_Syslog | LanceDB | Critical | Semantically matched critical fault logs |
| 8 | CPU_Drift | SQL | Warning | CPU change >=20% vs previous snapshot |
| 9 | Memory_Drift | SQL | Warning | Memory change >=10% vs previous snapshot |
| 10 | Interface_State_Drift | SQL | Warning | Interface state lines flipping across snapshots |
| 11 | BGP_Drift | SQL | Critical | BGP neighbor state changes across snapshots |
| 12 | OSPF_Drift | SQL | Warning | OSPF adjacency state changes across snapshots |
| 13 | STP_Drift | SQL | Warning | STP topology changes across snapshots |
| 14 | Log_Spike | SQL | Warning | Syslog line count spike >10 new lines |
| 15 | Config_Drift | SQL | Warning | Running-config changes across snapshots |

## Global Correlation Analysis Instructions

After all job sections are complete, perform cross-section analysis:

1. **Physical → Protocol cascade**: Interface_Down / Interface_State_Drift co-occurring with BGP_Drift / OSPF_Drift on the same device → physical link failure causing routing-protocol avalanche.

2. **Change-triggered failure**: Align Config_Drift timestamps with BGP_Drift / OSPF_Drift first-occurrence times → human change induced outage; recommend linking to change-management record.

3. **STP cascading impact**: STP_Drift port-role flap + burst of STP_Error_Disable → possible bridging loop or BPDU Guard triggering mass shutdown, affecting multiple VLANs.

4. **Resource leak trend**: Memory_Drift sustaining positive growth over multiple snapshots + CPU_Drift rising in parallel → process-level memory leak; recommend off-peak process restart.

5. **Alarm storm localization**: Log_Spike burst window + Critical_Syslog semantic matches → cross-validate alarm source device and specific fault event.

6. **Prioritized action list**: Provide the top 3 most urgent remediation steps (🔴 Critical / ⚠️ Warning), with rationale.

7. **Health verdict**: Conclude with a single-line health statement (🔴 Critical / ⚠️ At Risk / ✅ Healthy).
