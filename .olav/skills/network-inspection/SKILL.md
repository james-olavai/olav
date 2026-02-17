---
name: network-inspection
version: 4.0.0
description: Automated network inspection workflow - Execute commands, aggregate results, generate reports
author: Network AI Team
type: agent
category: network-analysis
intent: inspection

tools:
  - execute_commands_in_parallel
  - aggregate_inspection_results
  - query_database

prompts:
  system: $ref:./prompts/system.md

# =========================================================================
# Inspection Items (What to Check)
# =========================================================================
# Agent automatically:
# 1. Detects device platform from Nornir inventory
# 2. Queries NTC templates database for commands
# 3. Executes commands in parallel (Map phase)
# 4. Compares against thresholds (Reduce phase)
# 5. Generates professional report using LLM

inspection_items:
  - name: device_info
    description: Device model, OS version, serial number
    
  - name: cpu_utilization
    description: CPU utilization percentage
    
  - name: memory_utilization
    description: Memory utilization percentage
    
  - name: environment
    description: Temperature, fan status, power supply status
    
  - name: interface_status
    description: Interface status and protocol state
    
  - name: interface_errors
    description: Interface error counters (CRC, input/output errors)
    
  - name: neighbor_discovery
    description: CDP/LLDP neighbor relationships
    
  - name: mac_address_table
    description: MAC address table entries
    
  - name: routing_table
    description: Routing table entries
    
  - name: ospf_neighbors
    description: OSPF neighbor status and adjacencies
    
  - name: bgp_neighbors
    description: BGP neighbor status and sessions
    
  - name: arp_table
    description: ARP table entries

tags:
  - network-inspection
  - health-check
  - compliance
  - intent-based
  - automated-workflow
---

## Agent Workflow (Fully Automated)

### Initial Execution
1. **Read SKILL.md** - Load inspection_items list
2. **Detect Platform** - Read device platform from Nornir inventory (cisco_ios, juniper_junos, etc.)
3. **Query NTC Database** - Find best command for each item on target platform
4. **Generate Thresholds** - Create default thresholds.yaml (user can customize later)

### Subsequent Executions
1. **Map Phase**: `execute_commands_in_parallel(devices, commands)`
   - Read configuration from thresholds.yaml
   - Find platform-specific commands for each inspection_item (NTC database)
   - Execute all commands in parallel (multi-device x multi-command - all combinations)
   - Return raw output

2. **Reduce Phase**: `aggregate_inspection_results(results, thresholds)`
   - Parse command output (using TextFSM)
   - Compare against thresholds.yaml values
   - Calculate health score
   - Identify anomalies (critical/warning/normal)

3. **Report Phase**: LLM generates professional report
   - Input: Aggregated results + anomalies + thresholds
   - Output: Markdown formatted diagnostic report
   - Includes: Health score, anomaly details, remediation suggestions

## User Customization

**Modify Thresholds** (auto-generated after first run):
```yaml
# .olav/skills/network-inspection/config/thresholds.yaml
cpu_utilization:
  warning: 70
  critical: 90

interface_errors:
  warning: 1
  critical: 10
```

**Add Inspection Items** (edit SKILL.md):

To add a custom inspection item:
1. Open SKILL.md
2. Under `inspection_items:`, add a new entry with `name` and `description`
3. Example: `name: your_custom_check` with `description: Check custom status field`

Agent automatically finds commands from NTC database - no manual command definition needed!

