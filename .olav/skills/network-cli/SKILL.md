---
name: network-cli
version: 1.0.0
description: Network device CLI command execution and configuration management. Executes show and configuration commands via Nornir on network devices.
author: Network AI Team
type: agent
category: network-operations
intent: cli_execute

tools:
  - nornir_execute
  - query_database
  - list_devices

caching:
  enabled: true
  default_ttl_seconds: 3600
  max_cache_entries: 10000
  cached_command_patterns:
    - show version
    - show interfaces brief
    - show ip route summary
    - show bgp summary
    - show processes cpu
    - show memory statistics
    - show environment all
    - show inventory
  command_ttl_overrides:
    show version: 86400
    show interfaces brief: 60
    show ip route summary: 300
    show bgp summary: 900
    show processes cpu: 30
    show memory statistics: 30

prompts:
  system: |
    You are a CLI Command Execution Specialist for network device management and verification.

    Your core responsibilities:
    1. Execute show commands to gather device information and status
    2. Device interaction - Connect to and manage network devices
    3. Command execution - Run commands via Nornir automation framework
    4. Configuration changes - Apply configurations when authorized
    5. Verification - Confirm command execution results

    Workflow:
    1. Parse command/configuration requirement
    2. Identify target device(s) for execution
    3. Execute using nornir_execute() tool
    4. Verify results and report status
    5. Provide summarized output

    Available Tools:
    - nornir_execute: Execute commands on network devices
    - query_database: Query device inventory and CLI output history
    - list_devices: Get available devices

    Important Rules:
    - Always verify device availability before execution
    - Use device hostnames from devices table for targeting
    - Cache frequently used show commands
    - Confirm command safety before execution on production devices
    - If execution fails or requires multi-device coordination, inform orchestrator to upgrade to Expert
---

## CLI Command Executor

Direct command execution and device management via Nornir automation framework.

## Quick Start: Command Execution

1. **Target Identification**: Which device(s) need commands?
2. **Command Selection**: What to execute (show/config)?
3. **Execution**: Use nornir_execute() with device hostname
4. **Verification**: Confirm successful execution
5. **Output Formatting**: Return clear, structured results

## Security: Command Blacklist

This skill includes a command blacklist in `config/blacklist.txt` that automatically prevents execution of dangerous commands:

**Blocked Command Categories**:
- System destruction: `erase`, `reload`, `shutdown`
- Configuration deletion: `delete`, `clear config`
- Password/Keys: `secret`, `crypto key`
- Critical network changes: `no vlan`, `no interface`
- Resource intensive: `debug all`

**How It Works**:
1. Agent requests command execution: `nornir_execute("device", "show version")`
2. NetworkExecutor checks command against `config/blacklist.txt`
3. Safe commands execute, dangerous ones are blocked automatically
4. Result is returned to agent

**To Customize**:
- Edit `.olav/skills/network-cli/config/blacklist.txt`
- Add one pattern per line (case-insensitive matching)
- Commands are checked before execution (no partial matches)

## Caching Strategy

The `caching` configuration enables intelligent caching of CLI command results:

**Default Behavior**:
- Caching enabled by default for all show commands
- Default TTL: 1 hour (3600 seconds)
- Maximum 10,000 results in cache

**Per-Command TTL**:
- `show version`: 24 hours (stable data)
- `show interfaces brief`: 1 minute (frequently changes)
- `show ip route summary`: 5 minutes (route changes possible)
- `show bgp summary`: 15 minutes (relatively stable)
- `show processes cpu`: 30 seconds (real-time metrics)
- `show memory statistics`: 30 seconds (real-time metrics)

**Cache Invalidation**:
- Manual: Can be flushed via cache management tools
- Time-based: Entries expire after TTL
- Size-based: Oldest entries dropped when max_cache_entries exceeded

**Benefits**:
- Reduced network load for repeated queries
- Faster response times for cached data
- Lower execution times for read operations

## Common Commands

### Device Status Verification
```
show version          # Device version and uptime
show interfaces brief # Interface operational status
show ip route summary # Routing table summary
show bgp summary      # BGP peer status
```

### Health Metrics
```
show processes cpu          # CPU utilization
show memory statistics      # Memory usage
show ip sla statistics      # SLA probe status
show environment all        # Hardware/temperature status
```

