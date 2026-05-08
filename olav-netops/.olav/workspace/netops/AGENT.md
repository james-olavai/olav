---
name: netops
description: "Network Operations — SSH collection, BGP/OSPF analysis, topology queries, simulation, drift detection, ContainerLab digital twin, parser learning"
system_prompt_file: prompts/orchestrator.md
route_keywords:
  - network device router switch firewall CLI SSH show
  - BGP OSPF EIGRP routing neighbor adjacency protocol session
  - topology link interface LLDP CDP VLAN STP MTU
  - snapshot collect probe ping traceroute liveness
  - diff drift compare baseline configuration
  - lab containerlab digital twin convergence SRL CAB
  - simulate what-if failure blast-radius decommission
  - learn parser textfsm command unparseable
  - 路由 拓扑 接口 采集 快照 故障 漂移 模拟 学习
# Patch D' Step 2 (2026-05-08): explicit tools whitelist.  Without
# this, orchestrator auto-loaded all 7-8 core/tools/ .py files,
# giving weak local LLMs wrong-tool options.  Orchestrator only
# legitimately needs single-step DB queries + memory recall +
# occasional web search.  All write/read-file ops delegate to
# sub-agents.
tools:
  - execute_sql
  - recall_memory
  - web_search
# R-AGENT-HIERARCHY Phase A (2026-05-09): topology + learner pulled
# back from top-level (workspace.yaml shrunk 6→3); analyze + lab +
# collect already nested.
subagents:
  - path: ./analyze/SKILL.md
  - path: ./sim/SKILL.md           # R-AGENT-HIERARCHY Phase B+C 2026-05-09:
                                   # split from analyze; owns CHANGE PLAN
                                   # writing in prose + render_tcf skill-script
  - path: ./collect/SKILL.md
  - path: ./lab/SKILL.md
  - path: ./topology/SKILL.md
  - path: ./learner/SKILL.md
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
