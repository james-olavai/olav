# Orchestrator - Advanced Coordination Guide

## Multi-SubAgent Orchestration Patterns

### Pattern 1: Query → Analyze → Expert Escalation

**Scenario**: User asks "Is there a network issue?"

```
Step 1: Route to analysis SubAgent
  → Analyze current health scores
  → Detect anomalies?
    - NO → Return: "Network health normal"
    - YES → Proceed to Step 2

Step 2: Escalate to expert SubAgent
  → Expert runs diagnostics on anomaly
  → Is root cause identified?
    - YES → Return diagnosis report
    - NO → Return: "Needs more investigation"
```

**Implementation**:
1. Call analysis first (faster, cheaper)
2. If anomaly detected, call expert immediately
3. Don't try to fix with analysis — let expert handle it

---

### Pattern 2: Query + Storage (Single-Step Export)

**Scenario**: User asks "Export all devices to CSV"

```
Step 1: Route to query SubAgent
  → Execute: SELECT * FROM devices
  → Return: JSON array of records

Step 2: Synthesize (Orchestrator)
  → Pass raw JSON directly to export tool
  → Filename: "devices"
  → Format: "csv"

Step 3: Return
  → "✅ Exported to exports/devices.csv"
```

**Critical**: Pass raw JSON from query SubAgent directly to export tool. Do NOT reformat or summarize.

---

### Pattern 3: Multi-Layer Diagnosis (Expert)

**Scenario**: User asks "Why is BGP flapping?"

```
Expert SubAgent executes internally:

  Phase 1 (Assessment)
  ├─ Query: list BGP neighbors on affected device
  ├─ Query: check interface state
  └─ Query: check BGP timers config

  Phase 2 (Evidence)
  ├─ Query: BGP neighbor state history (last 1 hour)
  ├─ Query: interface errors/flaps (last 1 hour)
  ├─ Query: device logs for BGP errors
  └─ Topology: analyze neighbors

  Phase 3 (Hypothesis)
  ├─ H1: Authentication failure
  ├─ H2: Hold timer expiration
  └─ H3: Interface instability

  Phase 4 (Validation)
  ├─ Validate H1: Check config match with neighbors
  ├─ Validate H2: Check timers, check actual keepalive success rate
  └─ Validate H3: Check interface flap count, error rate

  Phase 5 (Root Cause)
  ├─ Correlate evidence
  └─ Deliver: Root cause + impact + fix

Orchestrator receives: Markdown report
Orchestrator returns: Report directly to user (or saves if user requested)
```

---

## Upgrade Decision Matrix

### When to Escalate to Expert

| Situation | Decision | Reason |
|-----------|----------|--------|
| Simple lookup (list devices) | Stay with query | Fast, no analysis needed |
| Health score <70 | Escalate to expert | Needs root cause investigation |
| Single-device command fails | Try cli, then expert if needed | CLI has limited context |
| "Why is X failing?" question | Escalate to expert IMMEDIATELY | Requires diagnostics |
| Multi-device correlation | Escalate to expert | Topology awareness needed |
| Performance trending (24h data) | Can use analysis, escalate if anomaly | Analysis can detect, expert diagnoses root cause |
| Design validation | Escalate to expert | Requires architectural thinking |
| Known issue in knowledge base | Escalate to expert | Needs case study matching |
| Multi-protocol issue (BGP+OSPF) | Escalate to expert | Cross-layer correlation |

---

## Output Formatting by SubAgent

### Query SubAgent Output

**Returns**: Structured JSON array
```json
[
  {"hostname": "R1", "ip_address": "10.0.0.1", "vendor": "Cisco"},
  {"hostname": "R2", "ip_address": "10.0.0.2", "vendor": "Cisco"}
]
```

**How Orchestrator Handles It**:
- For CSV/JSON export: Pass JSON directly to export tool
- For markdown display: Convert to markdown table
- Do NOT summarize or reformat — preserve structure

---

### Analysis SubAgent Output

**Returns**: Markdown with structure:
```markdown
## Health Analysis

**Overall Score**: 72/100 ⚠️ WARNING

### By Layer
- L1 Physical: 85/100 ✅ Healthy
- L2 Switching: 65/100 ⚠️ Warning
- L3 Routing: 55/100 🔴 Critical
- L4 Performance: 80/100 ✅ Healthy

### Recommendations
1. Investigate routing anomaly...
2. Check interface errors...
```

**How Orchestrator Handles It**:
- Display inline directly (markdown-ready)
- If user asks to save: Call export tool with markdown format
- If anomalies found: May escalate to expert

---

### Expert SubAgent Output

**Returns**: Markdown report with sections:
```markdown
## Diagnosis Report: BGP Flapping

### Root Cause
[Technical explanation]

### Evidence
- Database findings
- Topology context
- Timeline

### Impact
- Devices affected: [list]
- Services down: [list]

### Recommended Fix
[Step-by-step commands]

### Validation
[How to verify fix worked]

### Prevention
[Design/operational changes]
```

**How Orchestrator Handles It**:
- Display inline directly (markdown-ready)
- If user asks to save: Call export tool with markdown format
- If report has commands section: User can execute via cli SubAgent

---

### CLI SubAgent Output

**Returns**: Raw command output + structured metadata
```
Command: show bgp summary
Output:
  BGP router identifier 10.0.0.1, local AS number 65000
  Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State...

Metadata:
  device: R1
  command: show bgp summary
  timestamp: 2026-02-06T10:30:00Z
  status: success
```

**How Orchestrator Handles It**:
- Parse structured metadata
- Display output inline
- If output needs analysis: Escalate to expert

---

## Result Synthesis Strategy

### Combining Multiple SubAgent Results

**Scenario**: Complex diagnosis involving query + expert

```
User: "List interfaces with errors and diagnose why"

Step 1: query SubAgent
  Returns: [{"interface": "Gi0/0/1", "crc_errors": 847, "status": "up"}, ...]

Step 2: expert SubAgent
  Input: This query result
  Returns: Diagnosis markdown explaining error cause

Step 3: Orchestrator Synthesis
  Combine:
  - Query results (structured data)
  - Expert diagnosis (narrative)
  
  Output: "Interfaces with errors: [query results]. Root cause: [expert diagnosis]"
```

**Rule**: Don't merge/reformat results unnecessarily — preserve each SubAgent's output structure.

---

## Error Recovery & Escalation

### Pattern: Graceful Degradation

```
Query SubAgent tries simple lookup
  ├─ ✅ Success → Return results directly
  │
  └─ ❌ Fails (table not found, no data)
     └─ "The query returned no data. Do you want to:"
        1. Check database schema with expert?
        2. Try broader search?
        3. Escalate to expert for investigation?
```

**Don't**: Auto-escalate on every failure
**Do**: Inform user and ask permission to escalate

---

### Pattern: Cascading Diagnostics

```
User: "Device R1 is slow"

Step 1: analysis SubAgent
  Checks: CPU, memory, interface queue
  Result: "CPU 85%, interface queue 1000 packets — bottleneck detected"
  
  Decision: Analysis found cause, but not root cause
  Escalate: To expert

Step 2: expert SubAgent
  Investigates: Why is CPU high?
  Query: Process accounting, BGP/OSPF convergence, logging rate
  Result: "High CPU due to BGP route processor churn (1000 updates/sec)"
  
  Decision: Found root cause
  Return: Diagnosis + fix (adjust BGP timers, reduce flapping)
```

---

## Handling Export Requests

### Pattern 1: Data Export (Query → Export)

```
User: "Export all R1 interfaces to CSV"

Path:
  query SubAgent:
    SELECT interface, status, bandwidth, type
    FROM interfaces
    WHERE hostname = 'R1'
  
  Returns: [{"interface": "Gi0/0/1", "status": "up", ...}, ...]

Orchestrator:
  → Pass raw JSON to export tool
  → Format: "csv"
  → Filename: "r1_interfaces"
  
Output: "✅ Exported to exports/r1_interfaces.csv"
```

### Pattern 2: Report Export (Expert → Export)

```
User: "Diagnose OSPF issue and save report"

Path:
  expert SubAgent:
    → Runs diagnostics
    → Returns: Markdown report text
  
Orchestrator:
  → Save markdown report with export tool
  → Format: "markdown"
  → Filename: "ospf_diagnosis_2026-02-06"
  
Output: "✅ Report saved to exports/reports/ospf_diagnosis_2026-02-06.md"
```

---

## Advanced: Multi-Step ReAct Loops

### Example: Network Outage Investigation

```
User: "Our network is down. What happened?"

Orchestrator ReAct Loop:

Step 1: Define Problem Scope
  → Thought: "Need to understand what 'down' means"
  → Action: query SubAgent → "Which devices are unreachable?"
  → Observation: "Core switches R1, R2, Border R10, R11 unreachable"
  → Revised scope: "Core network segment failure"

Step 2: Gather Evidence (branching)
  → Parallel calls:
     a) query: Interface status on core devices
     b) query: BGP neighbor states
     c) cli: Real-time status check (if devices accessible)
  → Observations: Interfaces down, BGP neighbors down

Step 3: Pattern Matching
  → Thought: "Looks like physical layer problem"
  → Action: expert SubAgent → "Help diagnose multi-device failure"
  → Expert workflow:
     - Analyze topology (which devices should be connected)
     - Check physical layer failures
     - Correlate with maintenance windows
     - Query historical incidents
  → Root cause: "Fiber cut between R1 and R2 (maintenance team hit fiber)"

Step 4: Recovery Planning
  → Thought: "Need remediation plan"
  → Expert returns: Fix + timeline + prevention
  → Orchestrator returns: Full diagnostic report + recovery steps

Output: Comprehensive outage report with root cause and recovery plan
```

---

## When NOT to Escalate

### Keep with query SubAgent

- "List all devices" ← Simple inventory
- "Show me interfaces on R1" ← Direct lookup
- "Export device list to CSV" ← Data retrieval
- "How many devices we have?" ← Aggregate query

**Reason**: Adds unnecessary latency and cost. Query SubAgent is optimized for these.

### Keep with analysis SubAgent

- "Check health of network" ← Health scoring
- "Find devices with high CPU" ← Anomaly detection
- "Compare current vs baseline" ← Trend analysis

**Reason**: Analysis is designed for these patterns. Escalate only if root cause unclear.

### Keep with cli SubAgent

- "Show running config on R1" ← Direct command
- "Set IP address on interface" ← Configuration
- "Reload device" ← Execution

**Reason**: CLI is optimized for device interaction. Expert for diagnosis, CLI for execution.

---

## Common Mistakes & How to Avoid

### Mistake 1: Escalating Everything to Expert

❌ User: "List all devices"
→ ❌ Wrong: Route to expert (overkill)
→ ✅ Correct: Route to query (fast)

**Impact**: Slow responses, unnecessary cost

---

### Mistake 2: Trying to Diagnose with Query Alone

❌ User: "Why is BGP flapping?"
→ ❌ Wrong: query SubAgent returns data, Orchestrator tries to reason
→ ✅ Correct: Escalate to expert SubAgent immediately

**Impact**: Shallow analysis, missed root causes

---

### Mistake 3: Not Preserving SubAgent Outputs

❌ Expert returns JSON diagnostic results
→ ❌ Wrong: Orchestrator reformats it to prose
→ ✅ Correct: Return structured data as-is

**Impact**: Loss of information, harder for downstream tools

---

### Mistake 4: Forgetting the Upgrade Criteria

❌ Waiting for SubAgent to fail before escalating
→ ❌ Wrong: Creates poor user experience
→ ✅ Correct: Recognize upgrade triggers upfront and route immediately

**Upgrade Triggers**:
- Multi-device problem
- "Why" questions
- Topology-aware queries
- Complex protocols
- Root cause needed

---

## Performance Tuning

### Caching Strategy

**What to Cache**:
- Frequently queried data (VLAN list, device inventory)
- Topology snapshots (neighbor relationships, stable for hours)
- Health scores (calculated every 5min)

**What NOT to Cache**:
- Real-time interface stats (changes per second)
- BGP neighbor state (can flap frequently)
- CPU/memory metrics (changes per minute)

### Parallel Execution

```
Expert diagnosing multi-device failure:

  ❌ Sequential (slow):
    Query device-a → Query device-b → Query device-c
    Time: 3 queries × 1s = 3s

  ✅ Parallel (fast):
    Query [device-a, device-b, device-c] simultaneously
    Time: 1s
```

**When parallel helps**: Diagnosing multi-device issues, checking neighbors
**When parallel doesn't help**: Data dependencies (second query needs first result)

---

## SubAgent Communication Protocol

### Upgrade Message Format

SubAgent recognizes it needs escalation and returns:

```
{
  "status": "need_escalation",
  "reason": "Multi-device correlation required",
  "escalate_to": "expert",
  "context": {
    "devices_involved": ["R1", "R2", "R3"],
    "issue_type": "routing_convergence",
    "data_collected": {...}
  }
}
```

Orchestrator recognizes this and immediately calls expert SubAgent.

---

## Testing Orchestration Workflows

### Test Case 1: Correct Routing

```
Test: "list devices"
Expected: Route to query SubAgent
Verify: Returns device list within 1s
```

### Test Case 2: Escalation Detection

```
Test: "why is BGP flapping?"
Expected: Route directly to expert SubAgent
Verify: Expert returns diagnosis within 30s
```

### Test Case 3: Graceful Degradation

```
Test: query SubAgent returns empty (no data)
Expected: Orchestrator offers graceful options
Verify: User can escalate or refine query
```

### Test Case 4: Export With Structure Preservation

```
Test: Export query results to CSV
Expected: Raw JSON preserved as CSV
Verify: CSV has all columns, no data loss
```

---

**Version**: Advanced orchestration reference guide for OLAV v0.9.8
