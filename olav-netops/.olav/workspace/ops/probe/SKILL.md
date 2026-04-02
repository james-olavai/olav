---
name: ops-probe
description: "Probe Expert — Active liveness detection, latency testing, and network segment exploration"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: network-operations
  intent: active_probing_network_discovery
tools:
  - ping_device              # Dedicated: Ping target to check reachability and latency
  - traceroute               # Dedicated: Trace network path to destination
  - port_scan                # Dedicated: Scan target ports for open services
  - execute_cli_parallel    # Dedicated: Execute commands on multiple devices in parallel
system: $ref:./prompts/system.md
---

## Overview

The Probe Expert specializes in active network discovery and troubleshooting through direct network probing.

## Use Cases

1. **Liveness Detection**: Verify if a device or IP is reachable
2. **Latency Testing**: Measure round-trip time to identify network delays
3. **Path Analysis**: Trace the exact path packets take through the network
4. **Port Scanning**: Identify open services on target devices
5. **Network Discovery**: Explore unknown network segments

## Workflow

1. **Identify Target**: Determine the device/IP to probe
2. **Select Tool**: Chooseping/traceroute/port appropriate probing method (_scan)
3. **Execute**: Run the probe operation
4. **Analyze**: Interpret results and identify issues
5. **Report**: Provide findings with recommendations
