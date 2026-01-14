---
name: daily-run
version: 1.0.0
description: Complete daily network operations pipeline
schedule: "0 6 * * *"
timeout: 30m
---

# Daily Run Workflow

Complete network snapshot workflow with L1-L4 health analysis.

## Usage

```bash
/snapshot                     # Complete execution (alias for /daily-run)
/snapshot --group core        # Specify device group
/snapshot --fast              # Skip LLM analysis stage
/snapshot --stage sync        # Execute specific stage only
```

## Stage Definition (Map-Reduce Pattern)

### Stage 1: sync (Tool)
- Tool: `sync_all()`
- Output: `data/sync/{date}/raw/`, `parsed/`
- Description: Pure data collection from all devices

### Stage 2: topology (Tool)
- Tool: `generate_topology_from_sync()`
- Output: `exports/visualizations/topology.html`
- Description: Network topology visualization

### Stage 3: inspect (Tool + LLM Map)
- Tool: `collect_inspection_data()` → Collect raw data
- LLM: Independent judgment for each device metric
- Output: `data/sync/{date}/map/inspect/*.json`
- Description: Map phase - independent judgment per command

### Stage 4: logs (Tool + LLM Map)
- Tool: `parse_device_logs()` → Parse structured events
- LLM: Independent analysis per device log
- Output: `data/sync/{date}/map/logs/*.json`
- Description: Map phase - keyword triggered, determine if needs escalation

### Stage 5: report (LLM Reduce)
- Skill: `@skills/daily-report/SKILL.md`
- Input: Anomaly summary (not raw data)
- Output: `exports/reports/snapshots/YYYYMMDD.md`
- Description: Reduce phase - global correlation analysis

## Stage Dependencies

```
sync ──┬──► topology ──┐
       │               │
       ├──► inspect ───┼──► report
       │   (Map)       │   (Reduce)
       └──► logs ──────┘
           (Map)
```

## Stage Responsibilities

| Stage | Executor | Mode | Input | Output |
|-------|----------|------|-------|--------|
| sync | Tool | - | Device list | Raw data |
| topology | Tool | - | CDP/LLDP data | HTML |
| **inspect** | **Tool+LLM** | **Map** | **Per device/command** | **Check results** |
| **logs** | **Tool+LLM** | **Map** | **Per device log** | **Event summary** |
| **report** | **LLM** | **Reduce** | Check results summary | **Final report** |

## Map Phase Details

### Inspect Map Phase (Per Device × Per Command)

```
Granularity: Device + Command + Check Item

R1 show cpu      ──► LLM ──► "R1 | cpu      | ⚠️ 62% exceeds 50% threshold"
R1 show memory   ──► LLM ──► "R1 | memory   | ✅ 45% normal"
R1 show int      ──► LLM ──► "R1 | int Gi0/1| ⚠️ CRC 127 errors"
R2 show cpu      ──► LLM ──► "R2 | cpu      | ✅ 23% normal"
...

Output: inspect_results.json
[
  {"device": "R1", "check": "cpu", "status": "warning", "value": "62%", "detail": "exceeds threshold"},
  {"device": "R1", "check": "memory", "status": "ok", "value": "45%"},
  {"device": "R1", "check": "interface", "status": "warning", "interface": "Gi0/1", "detail": "CRC 127"},
  ...
]
```

### Logs Map Phase (Per Device Log Analysis)

```
R1 logs ──► LLM ──► "R1 | ⚠️ 3 OSPF neighbors DOWN, 2 LINK flapping"
R2 logs ──► LLM ──► "R2 | ✅ No anomalies"
R3 logs ──► LLM ──► "R3 | ⚠️ 1 BGP session reset"
...

Output: log_results.json
[
  {"device": "R1", "status": "warning", "events": [
    {"type": "ospf_down", "count": 3, "neighbors": ["10.1.1.2"]},
    {"type": "flapping", "interface": "Gi0/2", "count": 5}
  ]},
  {"device": "R2", "status": "ok", "events": []},
  ...
]
```

## Reduce Phase Details

```
Input (summarized):
- inspect_results.json → Filtered: 3 anomalies + "15/18 normal"
- log_results.json → Filtered: 2 devices with alerts
- topology.html: Link reference

LLM Correlation Analysis:
- R1 CPU high + OSPF DOWN + Gi0/2 flapping → Link flapping causing route recalculation
- R3 temp high → Check fan/room cooling

Output: exports/reports/snapshots/YYYYMMDD.md
- Executive summary table (normal/anomaly stats)
- Issue list (correlation analysis + recommendations)
- [View Topology](./topology.html)
```

## Token Comparison

| Mode | Map Granularity | Report Input | Risk |
|------|-----------------|--------------|------|
| ❌ No Map | - | 6 devices × 20 commands ≈ **50K tokens** | Explosion + hallucination |
| ⚠️ Per Device Map | Device | Anomaly device summary ≈ **1-2K tokens** | Acceptable |
| ✅ **Per Command Map** | **Device×Command** | Anomalies + stats ≈ **500 tokens** | **Optimal** |

## Error Handling

| Stage | Error Type | Handling |
|-------|------------|----------|
| sync | Device unreachable | Log failure, continue with other devices |
| sync | Command timeout | Retry 3 times, skip if still failing |
| inspect Map | LLM call failed | Retry 3 times, mark check as `error` |
| logs Map | LLM call failed | Retry 3 times, skip device log analysis |
| report Reduce | LLM call failed | Retry 3 times, generate fallback report (stats only) |

### Fallback Report Example

```markdown
# Network Snapshot - 2026-01-14 (Fallback Mode)

> ⚠️ LLM analysis unavailable, showing statistics only

## Summary
- Total devices: 6
- Anomaly checks: 4
- Anomaly events: 3

## Anomaly List
| Device | Check | Status | Value |
|--------|-------|--------|-------|
| R1 | cpu | warning | 62% |
...

[View Topology](./topology.html)
```
