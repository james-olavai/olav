---
name: netops_ops
description: "Network Operations — SSH collection, BGP/OSPF analysis, topology simulation, drift detection, ContainerLab digital twin, script generation, service queries"
system_prompt_file: prompts/orchestrator.md
route_keywords:
  - network device router switch firewall CLI SSH show
  - BGP OSPF EIGRP routing neighbor adjacency protocol session
  - topology link interface LLDP CDP VLAN STP MTU
  - snapshot collect probe ping traceroute liveness
  - diff drift compare baseline configuration
  - lab containerlab digital twin convergence SRL CAB
  - simulate what-if failure blast-radius decommission
  - script backup devops automation netbox influxdb
  - 路由 拓扑 接口 采集 快照 故障 漂移 模拟
# Patch D' Step 2 (2026-05-08): explicit tools whitelist.  Without
# this, orchestrator auto-loaded all 7-8 core/tools/ .py files,
# giving weak local LLMs wrong-tool options (gemma4 nothink picked
# format_and_export instead of task("ops-analyze") for emit_tcf).
# Orchestrator only legitimately needs single-step DB queries +
# memory recall + occasional web search.  All write/read-file ops
# delegate to sub-agents.
tools:
  - execute_sql       # Single-row device info lookup, no investigation
  - recall_memory     # Explicit memory query (AutoRecall middleware
                      # uses this implicitly too — keeping it as @tool
                      # lets the agent re-query if the auto-injection
                      # missed something)
  - web_search        # Verification of unknown terms while routing
subagents:
  - path: ./analyze/SKILL.md
  - path: ./collect/SKILL.md
  - path: ./lab/SKILL.md
  # 2026-05-01: devops + infra promoted to top-level workspaces (see
  # workspace.yaml).  Use ``olav --agent devops_scripts`` /
  # ``olav --agent devops_infra`` directly, or olav_delegate
  # cross-agent if needed.
  # Cross-workspace platform sub-agent for format_and_export / save:
  - path: ../core/writer/SKILL.md
---

## Overview

Deep-dive troubleshooting agent.  Orchestrates specialized sub-agents
to diagnose complex faults, predict change impacts, and validate via
ContainerLab digital twin.  Workflow rules: see `prompts/orchestrator.md`.

## Sandbox network policy

`execute_in_sandbox(code, network_isolation=...)` declares whether the
sandbox needs external network.  Default `True` (pure computation:
DB reads, networkx, math).  Set `False` only when the sandbox calls
an external API (httpx → CLAB, service calls).

| Sub-agent | isolation | Why |
|---|---|---|
| analyze (sim) | `True` | networkx / DuckDB only |
| analyze (diff) | `True` | local comparison only |
| analyze (topology) | `True` | graph algorithms only |
| lab | `False` | pushes configs via httpx to ContainerLab |
| collect (probe) | N/A | no sandbox — uses execute_cli_parallel |

`network_isolation=True` closes all network egress (urllib / aiohttp /
raw socket) via `unshare --net` when available.
