---
name: ops-probe
description: "Probe Expert — Active liveness detection, latency testing, and network segment exploration"
metadata:
  version: 1.1.0
  type: agent
  category: network-operations
  intent: active_probing_network_discovery
tools:
  - ping_device              # Ping target — check reachability and latency
  - traceroute               # Trace network path to destination
  - port_scan                # Scan target ports for open services
  - execute_cli_parallel     # Run a CLI command on multiple devices in parallel (Nornir; whitelist/blacklist enforced)
system: $ref:./prompts/system.md
---

## Overview

The Probe Expert specializes in active network discovery and troubleshooting through direct network probing.

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
