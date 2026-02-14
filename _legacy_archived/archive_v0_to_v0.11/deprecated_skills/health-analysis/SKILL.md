---
name: Health Analysis
description: Comprehensive network health analysis including device health checks, deep fault analysis, and L1-L4 inspection framework. Use when user asks for "health check", "device status", "troubleshoot", "analyze network", "diagnose issues", or needs systematic health diagnostics.
version: 2.0.0

# OLAV Extended Fields
intent: diagnose
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

# Health Analysis (Comprehensive Network Health & Fault Diagnosis)

## Overview

This skill provides three levels of health analysis:
1. **Quick Health Check** - System resources and status overview
2. **Deep Fault Analysis** - Complex troubleshooting with subagent delegation
3. **L1-L4 Inspection** - Layer-by-layer framework analysis

## Data Access Methods

**Primary: Database Tools (Recommended - Instant)**
```python
# Full network health analysis with L1-L4 scoring
analyze_network_health()

# Single device health summary
get_device_health("R1")

# Network-wide statistics
get_network_summary()
```

**Secondary: query_database (Zero-ETL - Flexible)**
```sql
-- Query snapshot data directly
SELECT data[1].hostname, data[1].version
FROM read_json_auto('exports/snapshots/latest/parsed/R1/show-version.json')

-- Interface status across all devices
SELECT unnest(data).interface, unnest(data).status
FROM read_json_auto('exports/snapshots/latest/parsed/*/show-ip-interface-brief.json')
```

**Tertiary: Real-time (Only when needed)**
```python
# Live command execution
smart_query("R1", "interface")
```

## Applicable Scenarios

### Quick Health Check
- Device health status check (CPU, memory, uptime)
- System resource monitoring
- Interface status verification
- Regular health monitoring baseline

### Deep Fault Analysis
- Network fault troubleshooting
- Performance problem analysis
- Path tracing and connectivity issues
- Root cause identification
- Multi-device failures

### L1-L4 Inspection
- Per-command inspection analysis
- Layer-by-layer diagnostics
- Structured health metrics
- Threshold-based alerting

## Identification Signals

User questions contain:
- "health", "status", "check", "monitor"
- "troubleshoot", "diagnose", "analyze", "fault"
- "why", "not working", "cannot access", "slow"
- "cpu", "memory", "resources"
- "layer", "L1", "L2", "L3", "L4"

---

# Part 1: Quick Health Check

## Execution Strategy

**MANDATORY**: You MUST execute ALL of the following steps. Do not skip any metric category.

1. **List devices** using `list_devices` (default group or specified)
2. **For each device**:
   a. Search for commands using `search_device_commands(device, query)` for EACH category below
   b. Execute the discovered commands via `nornir_execute` or `smart_query`

3. **MANDATORY checks** (execute ALL, not just some):
   - `search_device_commands(device, "version")` → Get device version/uptime
   - `search_device_commands(device, "cpu")` → Get CPU utilization
   - `search_device_commands(device, "memory")` → Get memory usage
   - `search_device_commands(device, "interface")` → Get interface status
   - `search_device_commands(device, "environment")` → Get environmental status (if available)

4. **Generate comprehensive report** with ALL metrics in a table format
5. **Highlight critical issues** based on thresholds below

## Health Metrics to Check

### System Information
- **Device identity**: Model, serial number, OS version
- **Uptime**: System uptime (flag if <7 days - recent reload)
- **Time sync**: Current system time (verify NTP sync)

### Resource Utilization
- **CPU usage**: Current and average CPU utilization
  - Threshold: WARNING if >50%, CRITICAL if >80%
- **Memory usage**: Memory utilization across all pools
  - Threshold: WARNING if >75%, CRITICAL if >90%

### Interface Health
- **Port status**: Number of interfaces up/down
- **Error counters**: CRC errors, input/output errors, drops
- **Interface states**: Any ports in error-disabled or flapping

### Environmental Health (if available)
- **Temperature**: Device temperature status
- **Power supplies**: Power supply status (active/failed)
- **Fans**: Fan operational status

## Status Indicators
- ✅ **OK** - All metrics normal (CPU <50%, Mem <75%, Uptime >7d)
- ⚠️ **WARNING** - One metric abnormal (CPU 50-80%, Mem 75-90%, Uptime 2-7d)
- 🔴 **CRITICAL** - Multiple abnormal metrics or high load (CPU >80%, Mem >90%)

---

# Part 2: Deep Fault Analysis

## Execution Strategy

1. **Use write_todos to decompose problems**
2. Identify problem type and choose analysis direction
3. Delegate to appropriate Subagent
4. Synthesize analysis and provide conclusions and recommendations

## Subagent Delegation Strategy

### macro-analyzer (Macro Analysis Agent)

**When to Use**:
- "Which node is the problem"
- "Where is packet loss on the path"
- "How large is the fault scope"
- Need to view topology relationships
- End-to-end connectivity issues
- Multi-device failures
- Routing path analysis
- BGP/OSPF neighbor problems

**Delegation Method**:
```
task(subagent_type="macro-analyzer",
     task_description="Analyze the path from R1 to R3, locate which node causes packet loss. Please:
     1. Execute traceroute to trace the path
     2. Check BGP/OSPF neighbor status
     3. Determine fault domain and impact scope
     Return: Fault node location, impact scope description")
```

**Subagent Capabilities**:
- Network topology analysis (LLDP/CDP/BGP)
- Data path tracing (traceroute, routing table)
- End-to-end connectivity checks
- Fault domain identification

### micro-analyzer (Micro Analysis Agent)

**When to Use**:
- "Why is this port not working"
- "Interface has errors"
- Need to troubleshoot specific device layer-by-layer
- Single port failure
- High interface error counts
- VLAN issues
- ARP/MAC problems

**Delegation Method**:
```
task(subagent_type="micro-analyzer",
     task_description="Perform TCP/IP layer-by-layer troubleshooting for R1's Gi0/1:
     1. Physical layer: Check interface status, CRC errors, optical power
     2. Data link layer: Check VLAN, MAC table, STP
     3. Network layer: Check IP configuration, routing, ARP
     Analyze layer by layer and return results for each layer")
```

**Subagent Capabilities**:
- TCP/IP layer-by-layer troubleshooting (physical to application layer)
- Deep device diagnostics
- Interface-level problem identification

---

# Part 3: L1-L4 Inspection Framework

## L1-L4 Check Framework

### L1 - Physical Layer (物理层)

| 检查项 | Intent 查询 | WARNING | CRITICAL |
|--------|-------------|---------|----------|
| temperature | "environment status" | >60°C | >70°C |
| power | "power status" | 任一 inactive | 单 PSU 模式 |
| fans | "environment status" | 任一 failed | - |
| uptime | "device version" | <24h (重启?) | - |

### L2 - Data Link Layer (数据链路层)

| 检查项 | Intent 查询 | WARNING | CRITICAL |
|--------|-------------|---------|----------|
| stp_role | "spanning-tree" | 非 root 但应为 root | - |
| mac_table | "mac address-table" | >80% 容量 | >95% 容量 |
| port_status | "interface status" | 关键端口 down | - |

### L3 - Network Layer (网络层)

| 检查项 | Intent 查询 | WARNING | CRITICAL |
|--------|-------------|---------|----------|
| ospf | "ospf neighbors" | 邻居非 FULL | 全部邻居丢失 |
| bgp | "bgp summary" | 会话非 ESTABLISHED | 全部会话 down |
| routes | "routing table" | 路由数异常波动 | 无路由 |

### L4 - Transport/Services (传输/服务层)

| 检查项 | Intent 查询 | WARNING | CRITICAL |
|--------|-------------|---------|----------|
| cpu | "cpu usage" | >50% | >80% |
| memory | "memory usage" | >75% | >90% |
| interface_errors | "interface counters" | CRC/错误 >0 | 错误率 >0.1% |
| interface_drops | "interface counters" | drops >0 | 持续增长 |

## Output Format (L1-L4 Inspection)

### Normal
```json
{
  "device": "R1",
  "layer": "L4",
  "check": "cpu",
  "status": "ok",
  "value": "23%"
}
```

### Warning
```json
{
  "device": "R1",
  "layer": "L4",
  "check": "cpu",
  "status": "warning",
  "value": "62%",
  "threshold": "50%",
  "detail": "CPU利用率超过警告阈值"
}
```

---

# Report Format

## Executive Summary (Quick Health Check)
```
📊 Health Analysis Report
Inspection Time: 2026-01-16 14:30:00
Total Devices: 8
Overall Status: ✅ OK

Device Status Summary:
├─ R1 (10.1.1.1)     ✅ OK        Uptime: 45d 12h    CPU: 12%    Memory: 65%
├─ R2 (10.1.1.2)     ✅ OK        Uptime: 30d 05h    CPU:  8%    Memory: 72%
├─ R3 (10.1.1.3)     ⚠️ WARNING   Uptime: 02d 18h    CPU: 45%    Memory: 88%
└─ R4 (10.1.1.4)     ✅ OK        Uptime: 12d 22h    CPU:  5%    Memory: 61%
```

## Fault Analysis Report (Deep Analysis)
```
🔍 Fault Analysis Report
Problem: "Cannot access server 10.3.1.100 from PC 10.1.1.50"

Analysis Process:
1. Macro Analysis: Traced path R1 → R2 → R3 → S1 → Server
   ✅ R1-R2: OK (BGP ESTABLISHED)
   ⚠️ R2-R3: Packet loss detected (traceroute timeout at R3)
   ✅ R3-S1: OK (OSPF FULL)

2. Micro Analysis: Investigated R3 interfaces
   🔴 Gi0/1: CRC errors (127 errors, 0.01% rate)
   ⚠️ Gi0/2: High drops (0.01%)

Root Cause: Physical layer degradation on R3 Gi0/1
Impact: Server 10.3.1.100 unreachable from 10.1.1.0/24
```

## L1-L4 Inspection Summary
```
Layer-by-Layer Health Status:
L1 (Physical):    ✅ OK (4/4 checks passed)
L2 (Data Link):   ⚠️ WARNING (3/4 checks passed, MAC table at 85%)
L3 (Network):     ✅ OK (3/3 checks passed)
L4 (Transport):   ⚠️ WARNING (CPU 62%, Memory 88%)

Overall: 10/12 checks passed (83%)
```

---

# Usage Examples

```
User: "Can you check device health?"
→ Executes quick health check on default device group
→ Returns system resources and status summary

User: "Troubleshoot why I can't access server 10.3.1.100"
→ Delegates to macro-analyzer for path tracing
→ Delegates to micro-analyzer for layer-by-layer diagnostics
→ Returns root cause and recommendations

User: "Analyze R1 with L1-L4 framework"
→ Executes L1-L4 inspection checks
→ Returns structured JSON output for each layer
→ Highlights thresholds and anomalies
```

---

# Migration Notes

This skill merges three previous skills:
- **health-check** (v1.0) → Quick health check functionality
- **deep-analysis** (v1.0) → Subagent delegation and fault analysis
- **inspect-analyzer** (v1.0) → L1-L4 framework

All functionality has been preserved and integrated into a comprehensive health analysis skill.
