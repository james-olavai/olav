---
name: Network Snapshot
description: Network data collection definitions (formerly daily-sync)
version: 2.0.0
intent: snapshot
# schedule controlled by daily-run workflow，not defined here
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
