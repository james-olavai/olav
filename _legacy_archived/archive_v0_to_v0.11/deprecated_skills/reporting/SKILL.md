---
name: Reporting
description: Generate comprehensive network reports including daily summaries, log analysis, and event correlation. Use when user asks for "daily report", "generate report", "analyze logs", "event summary", or needs comprehensive network documentation.
version: 2.0.0

# OLAV Extended Fields
intent: report
complexity: complex

# Output Configuration
output:
  format: markdown
  language: auto
  sections:
    - summary
    - details
    - recommendations
---

# Reporting (Comprehensive Network Reports & Log Analysis)

## Overview

This skill provides two levels of reporting:
1. **Log Analysis (Map Phase)** - Per-device log event analysis with pattern recognition
2. **Report Generation (Reduce Phase)** - Global analysis and correlation across all devices

## Applicable Scenarios

### Log Analysis
- Per-device log event analysis
- Pattern recognition and anomaly detection
- Keyword-based event filtering
- Severity classification

### Report Generation
- Daily/weekly/monthly network reports
- Cross-device event correlation
- Issue summarization and prioritization
- Executive summaries and recommendations

## Identification Signals

User questions contain:
- "report", "summary", "daily report"
- "analyze logs", "log analysis"
- "events", "what happened"
- "correlation", "trends"
- "generate", "document"

---

# Part 1: Log Analysis (Map Phase)

## Input Data

Per-device log raw text or parsed NetworkEvent list:
- device: "R1"
- raw_log: show logging output (if unparsed)
- parsed_events: NetworkEvent JSON list (if pre-parsed)

## Keyword Trigger Rules

### Phase 1: Keyword Matching (Quick Filter)

| Category | Trigger Keywords | Severity |
|----------|------------------|----------|
| **Errors** | `%ERROR`, `%CRITICAL`, `%ALERT` | 0-3 |
| **Interface** | `UPDOWN`, `LINK-3-UPDOWN`, `changed state to down` | 3 |
| **Routing** | `OSPF-5-ADJCHG`, `ADJCHG`, `neighbor down`, `went down` | 5 |
| **BGP** | `BGP-5-ADJCHANGE`, `session reset`, `connection closed` | 5 |
| **STP** | `SPANTREE-2-`, `topology change`, `root change` | 2-5 |
| **Hardware** | `FAN`, `POWER`, `TEMP`, `%ENVMON` | 2-4 |
| **Security** | `SEC_LOGIN`, `AUTHEN`, `failed`, `denied` | 4-5 |
| **Restart** | `RESTART`, `RELOAD`, `BOOT`, `Initializing` | 5 |

### Phase 2: Reporting Decision (LLM Analysis)

After keyword matching, LLM determines if reporting is needed:

| Scenario | Decision | Report? |
|----------|----------|---------|
| Interface DOWN then UP immediately (flapping) | flap_count > 3 | ⚠️ WARNING |
| Interface DOWN without recovery | Persistent DOWN | 🔴 CRITICAL |
| Interface DOWN then normal recovery | During maintenance window | ❌ No Report |
| OSPF neighbor DOWN then recovery | Recovered <5min | ❌ No Report |
| OSPF neighbor persistent DOWN | Unrecovered >5min | ⚠️ WARNING |
| Multiple OSPF neighbors DOWN simultaneously | Device may be down | 🔴 CRITICAL |
| Single login failure | Normal occurrence | ❌ No Report |
| Multiple consecutive login failures | >3 failures | ⚠️ WARNING |
| Device restart | Unplanned | 🔴 CRITICAL |

## Anomaly Pattern Recognition

| Pattern | Definition | Status |
|---------|------------|--------|
| **Flapping** | Same interface >3 UP/DOWN cycles (within 1h) | WARNING |
| **Neighbor Loss** | OSPF/BGP neighbor DOWN unrecovered | WARNING |
| **Bulk Events** | >10 same-type events (within 1h) | WARNING |
| **Severe Events** | severity <= 3 | CRITICAL |
| **Restart Events** | Unplanned restart | CRITICAL |

## Output Format (Log Analysis)

### Anomalies Detected - Report Required
```json
{
  "device": "R1",
  "status": "warning",
  "event_count": 5,
  "events": [
    {
      "type": "ospf_neighbor_down",
      "severity": "warning",
      "count": 3,
      "neighbors": ["10.1.1.2", "10.1.1.3"],
      "first_seen": "2026-01-16T02:15:00Z",
      "last_seen": "2026-01-16T05:30:00Z",
      "recovered": false,
      "detail": "3 OSPF neighbors DOWN for >5 minutes, no recovery"
    },
    {
      "type": "link_flapping",
      "severity": "warning",
      "interface": "Gi0/1",
      "count": 7,
      "first_seen": "2026-01-16T01:00:00Z",
      "last_seen": "2026-01-16T02:00:00Z",
      "recovered": true,
      "detail": "Interface Gi0/1 flapped 7 times within 1 hour"
    }
  ],
  "summary": "2 issues detected: OSPF neighbor loss (3 neighbors), link flapping (Gi0/1, 7 times)"
}
```

### No Anomalies - No Report Needed
```json
{
  "device": "R2",
  "status": "ok",
  "event_count": 0,
  "events": [],
  "summary": "No anomalies detected"
}
```

---

# Part 2: Report Generation (Reduce Phase)

## Input Data (Summarized, not raw)

- inspect_summary.json: Device inspection summary (with anomaly summary)
- log_summary.json: Device event summary
- topology_path: reports/topology.html (linked reference)

## Analysis Tasks

### 1. Issue Summary
Count devices with anomalies and classify by type

### 2. Correlation Analysis
Cross-device and cross-type correlation:
- High CPU + OSPF DOWN → Route instability
- CRC errors + BGP reset → Physical layer issue
- Multiple device alerts → Possible network event

### 3. Priority Ranking
- **CRITICAL**: Affects business operations
- **WARNING**: Requires attention
- **INFO**: Informational only

### 4. Report Generation

## Report Template

```markdown
# Network Daily Report - {{date}}

## 📊 Executive Summary

| Metric | Value | Status |
|--------|-------|--------|
| Total Devices | {{count}} | {{status}} |
| Devices with Anomalies | {{anomaly_count}} | {{anomaly_status}} |
| Check Items Pass Rate | {{ok_rate}}% | {{ok_status}} |

## 🗺️ Network Topology

[View Full Topology](./topology.html)

## 🔴 Issues Requiring Attention

### 1. {{title}} (CRITICAL)

**Symptoms**: {{symptom}}

**Root Cause**: {{root_cause}}

**Impact**: {{impact}}

**Recommendation**: {{recommendation}}

---

<details>
<summary>Detailed Data</summary>

### Inspection Results

{{detailed_checks}}

### Event Details

{{detailed_events}}

</details>
```

## Correlation Analysis Guidelines

### Cross-Device Correlation
1. **Time correlation**: Events occurring within same time window
2. **Topology correlation**: Events on physically connected devices
3. **Protocol correlation**: Related protocol failures (OSPF/BGP)

### Event Type Correlation
1. **Resource + Protocol**: High CPU + OSPF neighbor loss = CPU starvation
2. **Physical + Routing**: CRC errors + BGP reset = Physical layer affecting routing
3. **Multiple devices**: Same issue on multiple devices = Network-wide event

### Priority Assignment
- **CRITICAL**: Business impact, multiple devices, core infrastructure
- **WARNING**: Single device, potential impact, requires monitoring
- **INFO**: Informational, no immediate action needed

---

# Usage Examples

```
User: "Generate a daily report"
→ Analyzes logs from all devices
→ Correlates events across devices
→ Generates comprehensive markdown report
→ Saves to data/reports/daily-<date>.md

User: "Analyze logs for yesterday"
→ Processes log files
→ Detects anomalies and patterns
→ Summarizes key events
→ Highlights critical issues

User: "What happened on the network today?"
→ Quick log analysis
→ Event summary
→ Correlation analysis
→ Status overview
```

---

# Report Output Examples

## Example 1: Critical Issue Report

```markdown
# Network Daily Report - 2026-01-16

## 📊 Executive Summary

| Metric | Value | Status |
|--------|-------|--------|
| Total Devices | 8 | ✅ |
| Devices with Anomalies | 2 | ⚠️ |
| Check Items Pass Rate | 92% | ✅ |

## 🔴 Issues Requiring Attention

### 1. Core Router R3 CPU Starvation (CRITICAL)

**Symptoms**: R3 CPU utilization >80%, OSPF neighbors flapping

**Root Cause**: High CPU causing OSPF process to fail

**Impact**: Route instability affecting 3 sites

**Recommendation**:
1. Immediate: Check for routing loops or broadcast storms
2. Short-term: Schedule maintenance during off-peak hours
3. Long-term: Consider router upgrade

### 2. Access Switch S2 Interface Flapping (WARNING)

**Symptoms**: Gi0/1 flapped 7 times between 01:00-02:00

**Root Cause**: Possible physical layer issue (cable/port)

**Impact**: Intermittent connectivity for connected devices

**Recommendation**:
1. Check cable and physical connections
2. Monitor for 24 hours
3. Replace if flapping continues
```

## Example 2: Clean Report

```markdown
# Network Daily Report - 2026-01-16

## 📊 Executive Summary

| Metric | Value | Status |
|--------|-------|--------|
| Total Devices | 8 | ✅ |
| Devices with Anomalies | 0 | ✅ |
| Check Items Pass Rate | 100% | ✅ |

## Summary

All devices operating normally. No anomalies detected in the last 24 hours.

### Health Status
- All devices: ✅ OK
- CPU utilization: Average 12%
- Memory utilization: Average 68%
- Interface status: All critical links up
- Routing protocols: All neighbors established

### Recommendations
No immediate actions required. Continue regular monitoring schedule.
```

---

# Migration Notes

This skill merges two previous skills:
- **log-analyzer** (v1.0) → Log analysis and pattern recognition
- **daily-report** (v1.0) → Report generation and correlation

All functionality has been preserved and integrated into a comprehensive reporting skill with enhanced correlation capabilities.
