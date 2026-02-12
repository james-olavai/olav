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
  system: $ref:./prompts/system.md

security:
  blacklist: $ref:./config/blacklist.txt
  description: "Command blacklist prevents execution of dangerous commands"

caching_notes: |
  Default Behavior:
  - Caching enabled by default for all show commands
  - Default TTL: 1 hour (3600 seconds)
  - Maximum 10,000 results in cache
  
  Per-Command TTL Examples:
  - show version: 24 hours (stable data)
  - show interfaces brief: 1 minute (frequently changes)
  - show processes cpu: 30 seconds (real-time metrics)

tags:
  - network-cli
  - command-execution
  - nornir
  - automation
  - caching
---

## Quick Start: Command Execution

1. **Target Identification**: Which device(s) need commands?
2. **Command Selection**: What to execute (show/config)?
3. **Execution**: Use nornir_execute() with device hostname
4. **Verification**: Confirm successful execution
5. **Output Formatting**: Return clear, structured results

## Command Blacklist

Dangerous command patterns are automatically blocked before execution.

## Common Commands

### Device Status Verification
- show version
- show interfaces brief
- show ip route summary
- show bgp summary

### Health Metrics
- show processes cpu
- show memory statistics
- show ip sla statistics
- show environment all
