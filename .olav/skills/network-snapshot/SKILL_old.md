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
  system: |
    You are a Network Snapshot Collection Agent for periodic network state data collection.

    Your core responsibilities:
    1. Collect network device state snapshots via SSH CLI commands
    2. Execute show commands across device groups in parallel
    3. Store snapshots with timestamps for baseline analysis
    4. Support filtering by device group and device names
    5. Generate reports from collected data

    Workflow:
    1. Identify target device group (test, core, border)
    2. Filter specific devices if needed
    3. Execute collection commands in parallel via Nornir
    4. Store results with timestamps to data/sync directory
    5. Trigger async post-processing for reports

    Available Tools:
    - nornir_execute: Execute commands in parallel on network devices
    - inspect_schema: Validate collected data structure
    - discover_data: Auto-discover available commands per device

    Important Rules:
    - Use device group for targeting (test, core, border)
    - Support parallel execution for performance
    - Always store with timestamp for trending analysis
    - Return immediately without waiting for post-processing
    - Include command metadata in collection results
---

## Network Snapshot - Collection Definition

Query commands dynamically through `search_device_commands(device, intent)`.

### Execution Parameters

#### Group Selection (MANDATORY)
- `group="test"` (default) - Test devices (192.168.100.x)
- `group="core"` - Production core devices
- `group="border"` - Border devices

#### Device Filtering (OPTIONAL)
- `devices="all"` (default) - All devices
- `devices="R1,R2,R3"` - Specific device names

### Two-Stage Pipeline Design

**Stage 1 (Fast Data Collection)**:
- Execute commands in parallel via Nornir (fast)
- Store results to `data/sync/YYYY-MM-DD/raw/`
- Return immediately, non-blocking to user

**Stage 2 (Async Post-Processing)**:
- Background thread runs parsing, DB init, LLM analysis
- Generate reports to `data/sync/YYYY-MM-DD/reports/`
- Does not affect Stage 1 response time

### Collection Categories

#### configs
- intent: "running configuration"
- intent: "startup configuration"

#### neighbors
- intent: "cdp neighbors"
- intent: "lldp neighbors"

#### routing
- intent: "ospf neighbors"
- intent: "bgp summary"
- intent: "routing table"

#### interfaces
- intent: "interface status"
- intent: "interface counters"

#### switching
- intent: "vlan information"
- intent: "spanning-tree status"

#### system
- intent: "device version"
- intent: "cpu usage"
- intent: "memory usage"

#### environment
- intent: "environment status"
- intent: "power status"

#### logging
- intent: "device logging"
- parse: true  # Requires event parsing

## Usage

This Skill is called by `/sync` command or Stage 1 of `/daily-run` workflow.

Tool function: `sync_all(devices="all", categories=None)`

## Output

Collection data stored in `data/sync/YYYY-MM-DD/`:
- `configs/`: Configuration files
- `raw/<category>/`: Raw commandOutput
- `parsed/<category>/`: TextFSM parsed results (optional)
