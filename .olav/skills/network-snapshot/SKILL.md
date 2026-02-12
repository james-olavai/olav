---
name: network-snapshot
version: 2.0.0
description: Collect network device state through SSH CLI commands (show interfaces, routing tables, protocol status). Use for periodic data collection, baseline snapshots, and real-time command execution across device groups.
author: Network AI Team
type: agent
category: network-operations
intent: snapshot

tools:
  - nornir_execute
  - inspect_schema
  - discover_data

prompts:
  system: $ref:./prompts/system.md

execution:
  group_selection:
    - group: test
      description: Test devices (192.168.100.x)
    - group: core
      description: Production core devices
    - group: border
      description: Border devices
  device_filtering: Optional - specify devices="R1,R2,R3" or devices="all"
  
pipeline_stages:
  stage_1:
    name: Fast Data Collection
    execution: Parallel via Nornir
    storage: data/sync/YYYY-MM-DD/raw/
    blocking: No - returns immediately
  stage_2:
    name: Async Post-Processing
    execution: Background thread
    output: data/sync/YYYY-MM-DD/reports/
    blocking: No - does not affect user response

collection_categories:
  - name: configs
    intents:
      - "running configuration"
      - "startup configuration"
  - name: neighbors
    intents:
      - "cdp neighbors"
      - "lldp neighbors"
  - name: routing
    intents:
      - "ospf neighbors"
      - "bgp summary"
      - "routing table"
  - name: interfaces
    intents:
      - "interface status"
      - "interface counters"
  - name: switching
    intents:
      - "vlan information"
      - "spanning-tree status"
  - name: system
    intents:
      - "device version"
      - "cpu usage"
      - "memory usage"
  - name: environment
    intents:
      - "environment status"
      - "power status"
  - name: logging
    intents:
      - "device logging"

tags:
  - network-snapshot
  - collection
  - baseline
  - periodic-sync
---

## Quick Start

**Group Selection**: test (default), core, or border
**Device Filtering**: all (default) or specific hostnames
**Tool**: `sync_all(devices="all", categories=None)`

## Output Structure

Data stored in `data/sync/YYYY-MM-DD/`:
- `configs/` - Configuration files
- `raw/<category>/` - Raw command output
- `parsed/<category>/` - TextFSM parsed results (optional)
