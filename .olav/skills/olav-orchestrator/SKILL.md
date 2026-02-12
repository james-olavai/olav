---
name: orchestrator
version: 1.0.0
description: Orchestrate specialist SubAgents (query, analysis, expert, cli) with intelligent routing and result synthesis
author: Network AI Team
type: agent
category: orchestration
intent: orchestration

prompts:
  system: $ref:./prompts/system.md

---

## Overview

Central coordinator that routes network queries to specialized SubAgents based on problem type.

## SubAgent Roles

| Agent | Purpose | Use When |
|-------|---------|----------|
| **query** | Data retrieval, export | Simple lookups, CSV/JSON generation |
| **analysis** | Health checks, anomaly detection | Health analysis, baseline comparison |
| **cli** | Command execution | Device verification, real-time data |
| **expert** | Root cause analysis, multi-layer diagnosis | Complex problems, topology analysis |

## Routing Logic

```
User Query
  ├─ Simple data lookup?
  │  └─ → query SubAgent
  ├─ Health/anomaly check?
  │  └─ → analysis SubAgent
  ├─ Device command?
  │  └─ → cli SubAgent
  └─ Complex diagnosis?
     └─ → expert SubAgent
```

## Key Principles

✅ **Automatic Escalation**
- "No SQL query possible" → Always escalate to CLI
- Empty result ≠ No data → Verify with CLI
- Multi-device problem → Escalate to expert

✅ **Multi-Step Validation (v0.11.4+)**
1. If data with values: Return to user
2. If "No SQL possible": Escalate to CLI
3. If empty/zeros: Verify with CLI
4. Compare DB vs CLI results
5. Synthesize with attribution

✅ **File Export Detection (v0.11.2+)**
- Detect format: csv, json, markdown, yaml, xml, pdf
- Include markers: `<export_format>FORMAT</export_format>`
- Auto-create files in exports/

✅ **Planning Mode (/plan prefix)**
1. Generate plan with numbered steps
2. Show risk warnings
3. Wait for user approval [Y/n/edit]
4. Execute sequentially
5. Report results

## Examples

### Simple Data Lookup
```
User: "list all Cisco devices"
→ query SubAgent
→ Returns: Device table or CSV
```

### Health Check
```
User: "check network health"
→ analysis SubAgent
→ Returns: Scores + anomalies + recommendations
```

### Command Execution
```
User: "show version on R1"
→ cli SubAgent
→ Returns: Version info
```

### Complex Diagnosis
```
User: "why is BGP flapping?"
→ expert SubAgent
→ Returns: Root cause + fix + prevention
```

### File Export
```
User: "list devices and export to CSV"
→ query SubAgent with <export_format>csv</export_format>
→ Auto-creates: exports/devices.csv
```

### Planning
```
User: "/plan sync data to NetBox"
→ Generate 5-step plan
→ Show risk warnings
→ Wait for approval
→ Execute step by step
```

## Simple vs Complex Problem Indicators

**→ query/analysis/cli:**
- List devices by site
- Show interface errors
- Check health score
- What's device version

**→ expert:**
- "Why is OSPF flapping?" (multi-layer)
- Connectivity between sites failing (topology)
- BGP route not appearing (multi-protocol)
- Network slower than baseline (anomaly + RCA)

## Mid-Conversation Escalation Triggers

- ❌ "Table doesn't exist" → Try expert
- ❌ "Cannot isolate root cause" → Escalate to expert
- ❌ "Multi-device correlation needed" → Escalate to expert

## Result Handling

- **Data Export:** Returns JSON → Convert to CSV/JSON
- **Health Reports:** Returns markdown → Display inline
- **Diagnosis:** Returns markdown → Display inline
- **No Reformatting:** Each SubAgent output is ready-to-use

## Advanced Features

See `reference/ARCHITECTURE.md` for:
- Multi-SubAgent workflows
- Complex escalation patterns
- Result synthesis strategies
- Performance optimization
