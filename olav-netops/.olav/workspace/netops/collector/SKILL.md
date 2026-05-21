---
name: collector
agent_type: api  # skip TodoListMiddleware (NETOPS sub-agents are tool-execution, not plan-and-iterate)
# R-VERTICAL-SLICE 2026-05-09: sub-agent uses no-think for
# fast tool execution; orchestrator handles planning.
thinking_mode: disabled
description: "Live data collection — parallel CLI / Nornir, liveness + latency probing, fresh snapshots."
metadata:
  version: 2.0.0
  replaces: [ops-probe v1.2.0]
  type: agent
  agent_type: api
  category: network-operations
  intent: active_live_data_collection
tools:
  - execute_cli_parallel     # Run a CLI command on multiple devices in parallel (Nornir; whitelist/blacklist enforced)
# Portability manifest — YAML knowledge files under ./references/
dynamic_context:
  - path: ./references/take_snapshot_when_db_stale.guide.yaml
system: $ref:./prompts/system.md
---

## Overview

The Collect agent specialises in **active live-network data collection** — the
broader successor to the former ops-probe. It covers both pure probing
(ping/traceroute/port scan via shell) and batch CLI collection (parallel
`show` commands across devices via Nornir). Data lands in DuckDB for
downstream analysis by `ops-analyze`.

See [ADR-0005](../../../docs/adr/0005-probe-to-collect-rename-lab-stays-standalone.md)
for the rename rationale and why `ops/lab` remains a separate sub-agent
rather than merging into this one.

> **Note:** `ping`, `traceroute`, and `port_scan` are simple shell commands.
> Use the platform `run_shell` tool for these operations:
> - Ping: `run_shell("ping -c 4 <host>")`
> - Traceroute: `run_shell("traceroute <host>")`
> - Port scan: `run_shell("nc -zv <host> <port>")`

## `execute_cli_parallel` — Safety Model

Commands are validated against the `commands` table before any connection is attempted:
- `blacklisted = true` → rejected for all devices
- `pipe_allowed = false` + command contains `|` → rejected
- Device names must match `[a-zA-Z0-9_\-.]` — no injection

If the `commands` table is not yet populated, validation is skipped with a warning (fail-open).

## Use Cases

1. **Liveness Detection**: Verify if a device or IP is reachable
2. **Latency Testing**: Measure round-trip time to identify network delays
3. **Path Analysis**: Trace the exact path packets take through the network
4. **Port Scanning**: Identify open services on target devices
5. **Batch CLI Collection**: Run a show command across all devices simultaneously

## Workflow

1. **Identify Target**: Determine the device/IP to probe
2. **Select Tool**: Choose ping / traceroute / port_scan / execute_cli_parallel
3. **Execute**: Run the probe operation
4. **Analyze**: Interpret results and identify issues
5. **Report**: Provide findings with recommendations
