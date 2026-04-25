---
name: ops-orchestrator
description: "Network Operations — SSH collection, BGP/OSPF analysis, topology simulation, drift detection, ContainerLab digital twin, script generation, service queries"
system_prompt_file: prompts/orchestrator.md
route_keywords:
  - network device router switch firewall CLI SSH show
  - BGP OSPF EIGRP routing neighbor adjacency protocol session established
  - BGP邻居 路由 拓扑 接口 配置
  - topology link interface LLDP CDP VLAN STP ARP MAC
  - snapshot collect probe ping traceroute liveness
  - diff drift change compare baseline configuration running
  - lab containerlab deploy digital twin verify convergence SRL
  - simulate what-if failure blast radius decommission
  - script backup automation devops write generate
  - netbox influxdb infra service registry DCIM IPAM
  - 哪些接口 down 设备 采集 快照 模拟
subagents:
  - path: ./analyze/SKILL.md
  - path: ./collect/SKILL.md
  - path: ./lab/SKILL.md
  - path: ./devops/SKILL.md
  - path: ./infra/SKILL.md
  # Cross-workspace platform subagent — owns ``format_and_export`` for
  # all visualization / report-saving paths (R83.4 Chapter 4 fix:
  # without this entry, ops can't reach the only subagent that has
  # the save tool, and topology / sim / drift outputs only appeared
  # in chat, not on disk).
  - path: ../core/writer/SKILL.md
---

## Overview

The Operations Agent is the deep-dive troubleshooting expert. It orchestrates a team of specialized subagents to diagnose complex network faults, predict change impacts, and validate changes via ContainerLab digital twin emulation.

## Subagents

1. **analysis** — Routing analysis (BGP/OSPF), deterministic What-If simulation (networkx + netutils sandbox), and topology visualization (L2/L3 graphs, Mermaid diagrams, path analysis). Replaces `sim` (v2.1.0) and `topology` (v1.0.0).
2. **probe** — Active liveness detection, latency testing, network segment exploration
3. **diff** — Time-series drift detection between snapshots
4. **lab** — ContainerLab digital twin emulation for CAB gate validation (deploys real SR Linux containers, pushes OC-derived config, asserts protocol convergence)

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
