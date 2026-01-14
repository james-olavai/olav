---
name: Log Analyzer
description: Per-device log event analysis (Map phase) with keyword triggers
version: 1.0.0
intent: analyze
mode: map  # Per-device independent invocation
---

## Log Analyzer - Log Analysis (Map Phase)

### Input

Per-device log raw text or parsed NetworkEvent list:
- device: "R1"
- raw_log: show logging output (if unparsed)
- parsed_events: NetworkEvent JSON list (if pre-parsed)

### Keyword Trigger Rules

#### Phase 1: Keyword Matching (Quick Filter)

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

#### Phase 2: Reporting Decision (LLM Analysis)

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

### Anomaly Pattern Recognition

| Pattern | Definition | Status |
|---------|------------|--------|
| **Flapping** | Same interface >3 UP/DOWN cycles (within 1h) | WARNING |
| **Neighbor Loss** | OSPF/BGP neighbor DOWN unrecovered | WARNING |
| **Bulk Events** | >10 same-type events (within 1h) | WARNING |
| **Severe Events** | severity <= 3 | CRITICAL |
| **Restart Events** | Unplanned restart | CRITICAL |

## Output Format (Must Follow Strictly)

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
      "first_seen": "2026-01-13T02:15:00Z",
      "last_seen": "2026-01-13T05:30:00Z",
      "recovered": false,
      "detail": "3 OSPF neighbors DOWN for >5 minutes, no recovery"
    },
    {
      "type": "link_flapping",
      "severity": "warning",
      "interface": "Gi0/2",
      "flap_count": 5,
      "detail": "Interface UP/DOWN 5 times within 1 hour"
    }
  ]
}
```

### No Anomalies or Recovered
```json
{
  "device": "R2",
  "status": "ok",
  "event_count": 0,
  "events": [],
  "note": "Detected 2 OSPF events but both recovered, no report needed"
}
```

### Keywords Matched But Assessed as Normal
```json
{
  "device": "R3",
  "status": "ok",
  "event_count": 0,
  "events": [],
  "filtered": [
    {"type": "interface_down", "interface": "Gi0/3", "reason": "Normal operation during maintenance window"},
    {"type": "ospf_adjchg", "reason": "Neighbor recovered within 2 minutes"}
  ]
}
```

## Important Notes

1. **Match keywords first**, then decide if reporting is needed
2. **Consider time context**: Has the event recovered?
3. **Consider quantity**: Single event vs repeated events
4. **Record even when no report**: In `filtered` field explain why
5. **Structured output** for easy aggregation in Reduce phase
