---
name: ops-orchestrator
description: "Operations Agent — Deep troubleshooting with full ReAct loop; includes lab emulation for CAB validation"
system_prompt_file: prompts/orchestrator.md
subagents:
  - path: ./sim/SKILL.md
  - path: ./topology/SKILL.md
  - path: ./probe/SKILL.md
  - path: ./diff/SKILL.md
  - path: ./lab/SKILL.md
  - path: ./netbox/SKILL.md
---

## Overview

The Operations Agent is the deep-dive troubleshooting expert. It orchestrates a team of specialized subagents to diagnose complex network faults, predict change impacts, and validate changes via ContainerLab digital twin emulation.

## Subagents

1. **sim** — BGP, OSPF, static routes, routing analysis + deterministic What-If simulation (networkx + netutils sandbox). Replaces `routing` (v1) and `simulation` (v0.1).
2. **topology** — MAC tables, ARP, physical links, loop detection (STP), CDP/LLDP
3. **probe** — Active liveness detection, latency testing, network segment exploration
4. **diff** — Time-series drift detection between snapshots
5. **lab** — ContainerLab digital twin emulation for CAB gate validation (deploys real SR Linux containers, pushes OC-derived config, asserts protocol convergence)
6. **netbox** — NetBox DCIM/IPAM agent; manage devices, IPs, VLANs, racks via REST API

## Sandbox Network Isolation Policy

When a tool calls `execute_in_sandbox(code, ...)`, it must declare whether the sandbox code needs external network access:

```python
# Pure computation — DB reads, networkx, local math → isolate
execute_in_sandbox(code, network_isolation=True)

# Needs external network — httpx to clab API, service calls → allow
execute_in_sandbox(code, network_isolation=False)
```

**Per-agent policy:**

| Agent | network_isolation | Reason |
|-------|------------------|--------|
| sim   | `True`           | Simulation is pure local computation (networkx, DuckDB) |
| diff  | `True`           | Config comparison is pure local computation |
| topology | `True`        | Graph analysis is pure local computation |
| lab   | `False`          | Sandbox pushes configs to ContainerLab exec API via httpx |
| probe | N/A              | No sandbox — uses execute_cli_parallel directly |

**When writing a new skill:**
- Default to `network_isolation=True` unless the sandbox code explicitly calls an external API
- If network is needed, document why in the tool's docstring
- `network_isolation=True` closes all network bypass vectors (urllib, aiohttp, raw socket, etc.) via `unshare --net` when `unshare` is available
