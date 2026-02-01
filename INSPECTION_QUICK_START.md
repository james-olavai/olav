# Professional Inspection Report Examples & Use Cases

## Quick Start Guide

### 1. Run Full Network Inspection
```bash
uv run olav inspect
```
**Output**: Comprehensive report in `exports/reports/inspection/latest.md`

### 2. Run Test Group (3 devices)
```bash
uv run olav inspect --test
```
**Best for**: Quick validation, demos, testing changes

### 3. Run Specific Device Group
```bash
uv run olav inspect --device-group core
```
**Best for**: Targeted analysis of production devices

### 4. Run Specific Layer Only
```bash
# L1 Physical layer analysis
uv run olav inspect --layer L1 --test

# L2 DataLink layer analysis
uv run olav inspect --layer L2 --test

# L3 Network layer analysis
uv run olav inspect --layer L3 --test

# L4 Application layer analysis
uv run olav inspect --layer L4 --test
```

### 5. Filter Specific Devices
```bash
uv run olav inspect --device-filter R1,R2,SW1
```

### 6. Export Report as JSON
```bash
uv run olav export --inspection --format json
```

---

## Report Structure Breakdown

### 1️⃣ Executive Summary Section
**Shows**:
- Overall health score (0-100%)
- Device count breakdown (Normal, Warning, Critical)
- At-a-glance status

**Example**:
```
| Metric | Value |
|--------|-------|
| Overall Health Score | **85%** ⚠️ WARNING |
| Normal Devices | 8/10 ✅ |
| Warning Devices | 1/10 ⚠️ |
| Critical Devices | 1/10 🔴 |
```

**Health Score Interpretation**:
- 90-100% ✅ HEALTHY → Green status
- 70-89% ⚠️ WARNING → Yellow status
- 0-69% 🔴 CRITICAL → Red status

---

### 2️⃣ Inspection Scope & Methodology
**Explains What Was Checked**:

```
| Layer | Scope | Items Checked |
|-------|-------|---------------|
| L1 Physical | Device Health | Uptime, CPU, Memory, Temperature, Power, Fans |
| L2 DataLink | Interface Status | State, Errors, Drops, VLAN, STP |
| L3 Network | Routing Health | Routes, OSPF Neighbors, BGP Sessions, VPN |
| L4 Application | Service Status | Protocol Sessions, Queue Depth, Health |
```

**Purpose**: Readers understand what was inspected and why

---

### 3️⃣ Device Status Matrix
**Shows Per-Device L1-L4 Health**

```
| Device | L1 Physical | L2 DataLink | L3 Network | L4 Application | Overall |
|--------|-------------|------------|-----------|----------------|---------|
| R1 | ✅ | ✅ | ✅ | ✅ | ✅ Normal |
| R2 | ✅ | ⚠️ | ✅ | ✅ | ⚠️ Warning |
| R3 | ✅ | ✅ | ✅ | ✅ | ✅ Normal |
| SW1 | 🔴 | 🔴 | ✅ | ⚠️ | 🔴 Critical |
```

**Reading Guide**:
- ✅ = Healthy / Normal
- ⚠️ = Warning / Degraded
- 🔴 = Critical / Failed

---

### 4️⃣ Expected vs Actual State Analysis
**Most Important Section** - Details each anomaly

**Format for Each Issue**:
```
**R2 - Interface Ethernet1/1 Status** [L2 DataLink]

- **Expected State**: admin up, operational up
- **Actual State**: admin up, operational down
- **Severity**: ⚠️ WARNING
- **Details**: Interface is administratively up but operationally down. 
  Check physical connection and transceiver.
```

**Organized By Severity**:
1. 🔴 Critical Issues (must fix now)
2. ⚠️ Warning Issues (should fix soon)

---

### 5️⃣ Root Cause & Impact Analysis
**LLM-Powered Global Analysis**

**Contains**:
- **Root Cause Analysis**: "Is the BGP session down because of the link loss?"
- **Business Impact**: "This affects traffic between DC1 and DC2"
- **Correlation**: "Why are multiple interfaces down on SW1?"

**Example**:
```
### Root Cause Analysis
The interface failures on SW1 are likely due to a linecard failure 
or power supply issue, as all interfaces on that linecard are down.

### Business Impact Assessment
Traffic through SW1 is currently rerouted through backup links.
Performance degradation expected if backup links are already congested.
```

---

### 6️⃣ Recommendations & Action Plan
**Prioritized Actionable Steps**

**Three Priority Levels**:

#### 🚨 Immediate Actions Required
Things that must be done NOW:
- Emergency failover
- Critical service restart
- Emergency maintenance

Example:
```
**Step 1**: Power cycle the failed linecard on SW1
**Step 2**: Verify all interfaces come up after restart
**Step 3**: Monitor for 5 minutes for stability
```

#### 📅 Planned Actions
Things to do in next maintenance window:
- Configuration changes
- Software updates
- Planned maintenance

Example:
```
**Step 1**: Update BGP configuration on R1 with new peer
**Step 2**: Enable BFD for faster failure detection
**Step 3**: Add link redundancy between DC1-DC2
```

#### 🔧 Optimization Suggestions
Nice-to-have improvements:
- Performance tuning
- Cost optimization
- Preventive measures

Example:
```
**Step 1**: Implement QoS on core links to prioritize critical traffic
**Step 2**: Add SNMP monitoring alerts for interface errors
**Step 3**: Schedule quarterly health audits
```

---

### 7️⃣ Next Steps - Command Reference
**Actual Commands to Execute** (not hardcoded, uses templates)

```bash
# Query inspection database for specific device
olav query --inspection --device R1

# Search for specific metric anomalies
olav search --metric interface_errors --severity warning

# Compare current vs previous inspection
olav inspect --compare-baseline

# Run focused inspection on specific layer
olav inspect --layer L2 --device-group core

# Export detailed report for analysis
olav export --inspection --format json > inspection_20260201.json
```

---

## Real-World Scenario Examples

### Scenario 1: Healthy Network ✅ HEALTHY (100%)
```
3 devices inspected
All normal status
No anomalies

Recommendation: 
✅ Continue routine monitoring per schedule
```

### Scenario 2: Interface Issues ⚠️ WARNING (80%)
```
10 devices inspected
- 9 normal
- 1 warning

Issue Detected:
Device: SW1
Expected State: Interface Eth2/1 admin up, operational up
Actual State: admin up, operational down
Severity: ⚠️ WARNING

Action:
1. Check physical cable connection on SW1 Eth2/1
2. Verify transceiver is properly seated
3. Run command: olav query --inspection --device SW1 --interface Eth2/1
```

### Scenario 3: Service Failure 🔴 CRITICAL (45%)
```
10 devices inspected
- 8 normal
- 1 warning  
- 1 critical

Critical Issue:
Device: R1
Metric: BGP Session - ISP1
Expected State: ESTABLISHED
Actual State: IDLE
Severity: 🔴 CRITICAL
Layer: L3 Network

Root Cause: BGP neighbor unreachable - possible ISP link down

Business Impact: Traffic to ISP1 is rerouted to ISP2. 
If ISP2 is already congested, expect 30-40% throughput reduction.

Immediate Actions:
1. [CRITICAL] Contact ISP1 to verify link status
2. [CRITICAL] Check routing to ISP1 BGP neighbor IP
3. [CRITICAL] Verify BGP configuration on R1:
   - Run: olav query --inspection --device R1 --metric bgp_state
   - Run: show ip bgp summary (on R1)
   - Run: show ip route bgp (on R1)
4. [CRITICAL] If link down, activate failover to ISP2
5. [URGENT] Monitor ISP2 link for congestion

Planned Actions:
1. Add BFD to BGP session for faster failure detection
2. Configure BGP session logging
3. Review BGP timers (keepalive, holdtime)
```

---

## Code Reference

### Location of Report Generator
**File**: `src/olav/tools/report_formatter.py`
**Function**: `generate_professional_inspection_report()`

**Parameters**:
```python
def generate_professional_inspection_report(
    metadata: dict[str, Any],                    # Inspection metadata
    anomalies: dict[str, list[dict[str, Any]]],  # Detected anomalies
    llm_analysis: dict[str, Any],                # LLM analysis results
    layers_config: list[dict[str, Any]] | None = None,  # Optional layer config
) -> str:
    """Returns professional markdown report"""
```

### Data Flow
```
1. InspectionOrchestrator.run_inspection()
   ↓
2. MapPhase - Collect L1-L4 metrics from database
   ↓
3. ThresholdAgent - Detect anomalies
   ↓
4. ReducePhase - LLM global analysis
   ↓
5. ReportRenderer - Format professional report
   ↓
6. generate_professional_inspection_report() - Create markdown
   ↓
7. Saved to: exports/reports/inspection/report_YYYYMMDD_HHMMSS.md
```

---

## Performance Benchmarks

| Scope | Devices | Duration | Report Size |
|-------|---------|----------|-------------|
| Test | 3 | 5-10s | ~50KB |
| Small Group | 5 | 10-15s | ~80KB |
| Medium Group | 10 | 15-30s | ~150KB |
| Large Group | 50 | 1-2m | ~500KB |

---

## Integration with Monitoring Systems

### Send Report via Email
```bash
# Get latest report and email it
REPORT=$(cat exports/reports/inspection/latest.md)
echo "$REPORT" | mail -s "Network Inspection Report" ops-team@company.com
```

### Send Alerts to Slack
```bash
# Extract critical issues and send to Slack
CRITICAL=$(grep "🔴 CRITICAL" exports/reports/inspection/latest.md)
if [ ! -z "$CRITICAL" ]; then
    curl -X POST $SLACK_WEBHOOK -d "{\"text\": \"$CRITICAL\"}"
fi
```

### Upload to Monitoring Dashboard
```bash
# Export as JSON and upload to dashboard
uv run olav export --inspection --format json | \
  curl -X POST http://dashboard.company.com/api/reports \
    -H "Content-Type: application/json" \
    -d @-
```

---

## Customization Guide

### Adjust Health Score Weights
**File**: `src/olav/tools/report_formatter.py`
**Function**: `generate_professional_inspection_report()`

Current weights:
```python
health_score = 100 - (critical_count * 20 + warning_count * 5)
```

To change (e.g., make warnings count more):
```python
health_score = 100 - (critical_count * 30 + warning_count * 10)
```

### Add Custom Checks
**File**: `.olav/skills/network-inspection/SKILL.md`

Add new SQL query to layers:
```yaml
inspection:
  layers:
    - name: L1_Custom
      sql: |
        SELECT device, custom_metric FROM v_custom_table
```

### Change Report Template
**File**: `src/olav/tools/report_formatter.py`
**Function**: `generate_professional_inspection_report()`

Modify report sections or reorder them.

---

## Troubleshooting

### Q: Report shows "No anomalies detected" but I know there are issues
A: Check if database views are created:
```bash
# Regenerate views
uv run olav knowledge index

# Collect fresh data
uv run olav snapshot --group test
```

### Q: Health score seems wrong
A: Check calculation at line 94-98 of report_formatter.py
Check that anomalies are being properly detected

### Q: L1 Physical section empty
A: Check if v_device_status view is populated:
```bash
# Query directly
uv run olav query --sql "SELECT * FROM v_device_status LIMIT 5"
```

### Q: LLM analysis missing
A: Check LLM service availability:
```bash
# Verify LLM configuration
cat config/settings.py | grep -A 5 "LLM"
```

---

**Documentation Version**: 2.0
**Last Updated**: 2026-02-01
**OLAV Version**: v0.9.8
