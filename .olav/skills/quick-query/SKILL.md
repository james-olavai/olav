---
name: Quick Query
description: Execute network status queries using intelligent database or direct commands. Use for "check device status", "show interface", "query routing table", "find IP location", "network health analysis", or any read-only information retrieval.
version: 2.0.0

# OLAV Extended Fields
intent: query
complexity: simple

# Output Configuration
output:
  format: markdown
  language: auto
  sections:
    - summary
---

# Quick Query (Enhanced with DB Federation)

## Applicable Scenarios
- **Database Queries** (Preferred - Fast, Historical):
  - Find IP location (ARP/routes)
  - Device health summary
  - Network-wide statistics
  - Multi-device correlation
  - Health scoring & anomaly detection
- **Direct Command Queries** (For real-time data):
  - Current interface status
  - Live routing tables
  - Real-time BGP/OSPF states

## Identification Signals
User questions contain: "find", "locate", "where", "health", "analyze", "check", "see", "status", "show", "display"

## Execution Strategy

### Priority 1: Database Query (Preferred)
For these queries, use database tools (faster, more powerful):
- **IP Location**: `find_ip_location(ip_address)`
- **Device Health**: `get_device_health(device_name)`
- **Network Summary**: `get_network_summary()`
- **IP Search**: `search_ip_across_network(ip_pattern)`
- **Health Analysis**: `analyze_network_health(snapshot_date)`
Example 1: IP Location Query (Database)
**Trigger**: "Where is IP 10.1.12.1?", "Find 10.1.12.1"
**Method**: Database query (instant)
**Code**:
```python
from olav.tools.database_tools import find_ip_location
result = find_ip_location("10.1.12.1")
```
**Output**:
```
IP 10.1.12.1 Location
├─ Device: R2
├─ Interface: GigabitEthernet1
└─ MAC: 5000.000a.0000
```

### Example 2: Device Health Query (Database)
**Trigger**: "R1 health", "How is R1 doing?"
**Method**: Database query (instant)
**Code**:
```python
result = get_device_health("R1")
```
**Output**:
```
R1 Health Summary
├─ Platform: cisco_ios (border)
├─ ARP Entries: 9
├─ Routes: 4
├─ Neighbors: 6
└─ Commands: 64
```

### Example 3: Network Health Analysis (Database)
**Trigger**: "Network health", "Analyze network", "Any problems?"
**Method**: Database analysis with L1-L4 scoring
**Code**:
```python
result = analyze_network_health()
print(result["markdown_report"])
```
**Output**: Comprehensive health report with scores

### Example 4: Interface Status (Direct Command - Fallback)
**Trigger**: "R1 Gi0/1 real-time status"
**Method**: Direct command (for real-time data)
**Command**: `show interfaces GigabitEthernet0/1`
**Extract**: up/down, speed, error counts
### find_ip_location_tool(ip_address)
Find where an IP address is located in the network.

**Usage**:
```python
from olav.tools.database_tools import find_ip_location_tool
result = find_ip_location_tool("10.1.12.1")
```

**Returns**:
```json
{
  "found": true,
  "ip": "10.1.12.1",
  "device_name": "R2",
  "interface": "GigabitEthernet1",
  "mac_address": "5000.000a.0000",
  "vlan": null
}
```

### get_device_health(device_name)
Get comprehensive health info for a device.

**Usage**:
```python
result = get_device_health("R1")
```

**Returns**:
```json
{
  "found": true,
  "device_name": "R1",
  "platform": "cisco_ios",
  "role": "border",
  "arp_count": 9,
  "route_count": 4,
  "neighbor_count": 6,
  "command_count": 64
}
```

### get_network_summary()
Get network-wide statistics.

**Usage**:
```python
result = get_network_summary()
```

**Returns**:
```json
{
  "total_devices": 6,
  "total_links": 22,
  "total_arp_entries": 36,
  "total_routes": 18,
  "platforms": ["cisco_ios", "cisco_nxos"]
}
```

### search_ip_across_network(ip_pattern)
Search for IPs matching a pattern.

**Usage**:
```python
result = search_ip_across_network("10.1%")
```

**Returns**: List of IP locations

### analyze_network_health(snapshot_date=None)
Generate comprehensive health analysis with L1-L4 scoring.

**Usage**:
```python
result = analyze_network_health()
print(result["markdown_report"])
```

**Returns**:
```json
{
  "overall_score": 100,
  "overall_status": "HEALTHY",
  "layer_scores": {"L3": 100},
  "device_health": [...],
  "anomalies": [],
  "markdown_report": "..."
}
```

## Decision Flow
```
User Query
    ↓
[Is it DB-queryable?]
    ├─ YES → Use database_tools (find_ip_location, get_device_health, etc.)
    │         → Fast, rich, historical data
    │
    └─ NO → Use direct commands
              → Parse alias → search_capabilities → nornir_execute
              → Real-time, device-specific data
```

**DB-Queryable Queries**:
- IP location, device health, network summary
- IP search patterns, health analysis
- Multi-device correlation, historical trends

**Command-Only Queries**:
- Real-time interface stats (packet counters)
- Live BGP/OSPF negotiation states
- Current CPU/memory usagerigger**: "R1 Gi0/1 status", "show interface status"
**Command**: `show interfaces GigabitEthernet0/1` or `show interface brief`
**Extract**: up/down, speed, error counts

### IP/MAC Location
**Trigger**: "What port is 10.1.1.100 on", "Find this MAC"
**Process**:
1. `show arp | include 10.1.1.100` → Get MAC
2. `show mac address-table address <mac>` → Get port

### Version Information
**Trigger**: "Device version", "show version"
**Command**: `show version` or `display version`
**Extract**: Device model, software version, uptime

### CPU/Memory Query
**Trigger**: "CPU usage", "Memory status"
**Command**: `show processes cpu history`, `show memory statistics`
**Extract**: Current usage, trends

## Command Templates

Some commands require parameters. When you see `!VARIABLE_NAME` in a template:
- **Replace it** with the actual value from user context
- **Never send `!VARIABLE_NAME` literally** to the device

Examples:
| Template | User Request | Actual Command |
|----------|--------------|----------------|
| `show interface !INTERFACE_NAME` | "Check Gi0/1" | `show interface GigabitEthernet0/1` |
| `show ip bgp neighbors !NEIGHBOR_IP` | "BGP from 10.1.1.2" | `show ip bgp neighbors 10.1.1.2` |
| `show mac address-table address $MAC_ADDRESS` | "Find aabb.cc00.1100" | `show mac address-table address aabb.cc00.1100` |

See knowledge/command-templates.md for full variable reference.

## Workflow
```
User query → Parse alias → search_capabilities → Replace !VARIABLES → nornir_execute → Format output
```

## Output Format
Keep it concise, highlight key information:
```
R1 (10.1.1.1) - Interface Status
├─ Gi0/1: up, line protocol up
│  ├─ Input: 1000 Mbps, 0 errors
│  └─ Output: 1000 Mbps, 0 errors
├─ Gi0/2: administratively down
└─ Gi0/3: up, line protocol up
   └─ CRC errors: 0
```

## Notes
- Only execute read-only commands
- No configuration changes
- Output must be clear and concise
- If device doesn't exist, confirm with list_devices first
