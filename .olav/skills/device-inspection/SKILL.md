---
name: Device Inspection
description: Execute comprehensive L1-L4 network device inspection. Use when user asks to "inspect all devices", "run comprehensive health check", "full network audit", or needs systematic L1-L4 analysis across multiple devices.
version: 2.0.0

# OLAV Extended Fields
intent: inspect
complexity: medium

# Execution Configuration (v0.9.4 Map-Reduce)
execution:
  mode: map-reduce
  parallel: true
  intermediate_output: true
  orchestrator: inspect_orchestrator
  # Map Phase: 为每个设备创建独立的 ReAct Agent
  # Reduce Phase: 汇总所有设备报告，生成完整分析
  # Intermediate Files: exports/reports/inspection_{timestamp}/devices/*.json

# Output Configuration
output:
  format: markdown
  language: auto
  sections:
    - summary
    - details
    - recommendations
---

# Device Inspection - Comprehensive L1-L4

## Applicable Scenarios
- Comprehensive network health assessment (all test devices)
- Full stack network inspection (L1-L4)
- Network baseline establishment and verification
- Pre-maintenance complete audit

## Identification Signals
User questions contain: "inspect", "comprehensive", "full check", "all devices", "L1-L4"

## Execution Strategy (v0.9.4 Map-Reduce + ReAct)

**Architecture**: Python Orchestrator + Per-Device ReAct Agents

**Map Phase (Parallel/Serial)**:
1. Python loop ensures **all devices are processed** (no missing devices)
2. Each device gets a dedicated ReAct Agent for flexible L1-L4 analysis
3. Agent uses `query_database` for Zero-ETL data access
4. Intermediate results saved to `exports/reports/inspection_{timestamp}/devices/{device}.json`

**Reduce Phase (Aggregation)**:
5. Collect all device reports (from intermediate files or in-memory)
6. Generate summary table (Device | Version | L1 | L2 | L3 | L4 | Status)
7. Consolidate issues and recommendations
8. Output final Markdown report: `exports/reports/inspection_{timestamp}/report.md`

**Advantages**:
- ✅ **Completeness**: Python loop guarantees all devices inspected
- ✅ **Flexibility**: ReAct Agents adapt to each device's capabilities
- ✅ **Recoverability**: Intermediate files allow resume from failures
- ✅ **Auditability**: Full trace of per-device analysis
- ✅ **Scalability**: Parallel execution for large networks

### Data Access Methods

**Primary: query_database (Zero-ETL - Recommended)**
Use SQL queries on snapshot JSON files for fast analysis:

```sql
-- Version info for device
SELECT data[1].hostname, data[1].version, data[1].uptime
FROM read_json_auto('exports/snapshots/latest/parsed/R1/show-version.json')

-- Interface status
SELECT unnest(data).interface, unnest(data).status
FROM read_json_auto('exports/snapshots/latest/parsed/R1/show-ip-interface-brief.json')

-- ARP entries count
SELECT COUNT(*) FROM (
  SELECT unnest(data) FROM read_json_auto('exports/snapshots/latest/parsed/R1/show-arp.json')
)

-- OSPF neighbor st(v0.9.4)

**CLI Command**:
```bash
# Basic inspection (uses latest snapshot)
olav inspect

# With data collection
olav inspect --snapshot

# Device filtering
olav inspect --device R1,R2
olav inspect --role router
olav inspect --group core

# Execution modes
olav inspect --parallel          # Parallel map phase (default)
olav inspect --no-parallel       # Serial map phase (debugging)
olav inspect --no-intermediate   # Skip intermediate files
```

**Orchestrator**: `inspect_orchestrator.inspect_all_devices()`
- Python handles device iteration (not LLM)
- ReAct Agent analyzes each device independently
- Final report aggregates all device
- `get_device_health(device)` - Quick device health summary
- `analyze_network_health()` - Full network L1-L4 analysis

**Tertiary: Real-time (Only if no snapshot)**
- `smart_query(device, intent)` - Live command execution

### Implementation Details
- Use `sync_all(group="test")` for test devices (default)
- Use `sync_all(group="core")` for production inspection
- Nornir handles parallel execution (6 devices → ~10 seconds)
5. **Generate consolidated report** with device-by-device status
6. **Flag anomalies** across all layers

## Comprehensive Inspection Framework (L1-L4)

Use `search_device_commands(device, query)` to find appropriate commands for each layer.

### L1 - Physical Layer
**What to check**:
- Device model, serial number, uptime
- Hardware modules inventory (power supplies, fans, transceivers)
- Environmental status (temperature, power, fan status)
- Physical interface states and media types

**Search queries**: "version", "inventory", "environment", "interfaces physical"

**Thresholds**:
- Temperature: WARNING >60°C, CRITICAL >70°C
- Power supplies: WARNING if any inactive, CRITICAL if single PSU mode
- Fans: WARNING if any failed

### L2 - Data Link Layer
**What to check**:
- VLAN configuration and status
- Spanning Tree Protocol topology and port states
- CDP/LLDP neighbor discovery
- MAC address table status and size

**Search queries**: "vlan", "spanning-tree", "cdp neighbors", "lldp", "mac address-table"

**Thresholds**:
- STP: WARNING if not root but expected to be
- MAC table: WARNING if >80% capacity

### L3 - Network Layer
**What to check**:
- Routing table size and protocol summary
- OSPF neighbor status and states
- BGP neighbor status and session states
- VPN status (if applicable)

**Search queries**: "route", "ospf neighbor", "bgp summary", "vpn"

**Thresholds**:
- OSPF: WARNING if any neighbor not FULL
- BGP: WARNING if any session not ESTABLISHED
- Routes: INFO baseline count for trending

### L4 - Transport Layer & Services
**What to check**:
- TCP session counts
- CPU utilization and process breakdown
- Memory usage across pools
- Interface error counters and drops
- Packet drops and queue statistics

**Search queries**: "tcp", "cpu", "memory", "interface errors", "interface drops"

**Thresholds**:
- CPU: WARNING >50%, CRITICAL >80%
- Memory: WARNING >75%, CRITICAL >90%
- Interface errors: WARNING if increasing, CRITICAL if >0.1%

## Report Format

### Executive Summary
```
📋 test Network Comprehensive Inspection Report
Inspection Time: 2026-01-08 14:30:00
Total Devices: 8
Overall Status: 2 devices OK, 5 devices WARNING, 1 device CRITICAL

Device Summary:
├─ R1 (10.1.1.1) ✅ OK - L1:✅ L2:✅ L3:✅ L4:✅
├─ R2 (10.1.1.2) ⚠️ WARNING - L1:⚠️ L2:✅ L3:✅ L4:✅
├─ R3 (10.1.1.3) ⚠️ WARNING - L1:✅ L2:✅ L3:✅ L4:⚠️
├─ R4 (10.1.1.4) ⚠️ WARNING - L1:⚠️ L2:✅ L3:✅ L4:✅
├─ S1 (10.2.1.1) ✅ OK - L1:✅ L2:✅ L3:✅ L4:✅
├─ S2 (10.2.1.2) ⚠️ WARNING - L1:✅ L2:⚠️ L3:✅ L4:✅
├─ A1 (10.3.1.1) ⚠️ WARNING - L1:✅ L2:✅ L3:⚠️ L4:✅
└─ A2 (10.3.1.2) ❌ CRITICAL - L1:❌ L2:✅ L3:✅ L4:⚠️
```

### Device-by-Device Detailed Results
Each device gets a full L1-L4 report:
```
╔══════════════════════════════════════════════════════╗
║ Device: R1 (10.1.1.1) - Core Router                 ║
║ Platform: Cisco IOS XE                              ║
║ Status: ✅ ALL SYSTEMS OK                           ║
╚══════════════════════════════════════════════════════╝

Layer 1 (Physical):
  CPU Utilization: 15% (5min avg) ✅
  Memory Usage: 62% (avaitestle: 8.2GB) ✅
  Temperature: 42°C (threshold: 70°C) ✅
  Power Supplies: 2/2 ACTIVE ✅
  Fans: 6/6 SPINNING ✅

Layer 2 (Data Link):
  VLAN Count: 45 ✅
  Active Ports: 48/48 UP ✅
  STP Root: YES (Priority: 24576) ✅
  LLDP Neighbors: 4 discovered ✅

Layer 3 (Network):
  IPv4 Routes: 2,847 routes ✅
  OSPF Neighbors: 3 FULL ✅
  BGP Neighbors: 2 ESTABLISHED ✅
  Routing Errors: 0 ✅

Layer 4 (Transport):
  Interface Errors: 0 (24h avg) ✅
  Dropped Packets: 0 (24h avg) ✅
  TCP Sessions: 45 active ✅
  UDP Flows: 128 active ✅
```

### Anomaly Details & Recommendations
```
⚠️ WARNING: R2 - Temperature trending high
Current: 58°C | Trend: +2°C/hour | Threshold: 70°C
Recommendation: Monitor closely, ensure adequate airflow

❌ CRITICAL: A2 - Power supply #1 degraded
Status: FAILED | Uptime before failure: 847 days
Recommendation: Replace PSU immediately before other PSU fails
```

### Consolidated Findings
```
Critical Issues (Immediate Action):
1. A2 Power Supply Failure - Replace PSU
2. A1 BGP Neighbor Flapping - Check link stability

Warnings (Monitor):
1. R2 Temperature trending up - Check cooling
2. S2 STP Bridge Priority - May need rebalancing
3. R3 Interface FCS Errors increasing - Check optics

Informational (Good Status):
- All core devices operating normally
- test network stable and well-managed
```

## Multi-Device Inspection Process

1. **Device Collection**: Query all devices in 'test' group
2. **Parallel Execution**: Execute inspection template on each device
3. **Data Aggregation**: Collect and normalize results
4. **Analysis**: Compare against health baselines
5. **Reporting**: Generate comprehensive multi-device report with:
   - Overall network health score
   - Device-by-device status
   - Cross-layer dependency analysis
   - Consolidated recommendations

## Output Artifact
```
reports/test-comprehensive-inspection-20260108-143000.md
├─ Executive Summary Dashboard
├─ Device Status Matrix
├─ Layer-by-Layer Details (8 devices × 4 layers = 32 sections)
├─ Anomaly Analysis
├─ Historical Comparison (vs. previous inspection)
└─ Recommendations & Actions
```
