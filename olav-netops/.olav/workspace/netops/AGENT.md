---
name: netops
description: "Network Operations — SSH collection, BGP/OSPF analysis, topology queries, simulation, drift detection, ContainerLab digital twin, parser learning"
system_prompt_file: prompts/orchestrator.md
# R-VERTICAL-SLICE 2026-05-09 (dev_docs/74): hybrid thinking — orchestrator
# uses reasoning ON for multi-step planning + capability dispatch; each
# sub-agent declares thinking_mode: disabled so its tool calls execute
# fast.  Verified gemma4:31b clean tool calls in both modes.
thinking_mode: enabled
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
  - log syslog event error warning 日志 为什么 故障定位 evidence why
# Patch D' Step 2 (2026-05-08): explicit tools whitelist.  Without
# this, orchestrator auto-loaded all 7-8 core/tools/ .py files,
# giving weak local LLMs wrong-tool options.
#
# R-VERTICAL-SLICE 2026-05-09 (dev_docs/74): execute_sql REMOVED from
# orchestrator level.  In hybrid thinking tests both gemma4:31b and
# qwen3.6:27b ignored the dispatch table and ran 12-21 direct SQL
# queries (many duplicates) instead of delegating to task("analyze").
# Removing the tool forces the architectural separation: orchestrator
# routes intent → sub-agent does data work.
tools:
  - recall_memory
  - web_search
# R-AGENT-HIERARCHY Phase A (2026-05-09): topology + learner pulled
# back from top-level (workspace.yaml shrunk 6→3); analyze + lab +
# collect already nested.
subagents:
  - path: ./analyze/SKILL.md       # Inspector-based read-side analysis
                                   # (NetworkX inspectors): topology +
                                   # routing + drift_* + blast_radius +
                                   # Mermaid visualisation paths.
  - path: ./analyzer/SKILL.md      # DEFAULT entry point (dev_docs/77 §2.6).
                                   # SQL state + Markdown report writer.
                                   # Owns Workflow A (change plan) +
                                   # Workflow D (investigation report).
                                   # Delegates cross-domain to sim.
  - path: ./sim/SKILL.md           # Batfish-backed config-layer evaluator
                                   # (dev_docs/77 §2 2026-05-14).  3 tools:
                                   # batfish_capability / batfish_q /
                                   # format_and_export.  Replaced the
                                   # R-CAB-THREE-STAGE Python pipeline.
  - path: ./investigate/SKILL.md   # Evidence drilldown — syslog,
                                   # command output, config text.
  - path: ./collect/SKILL.md
  - path: ./topology/SKILL.md
  - path: ./learner/SKILL.md
  # ./lab/SKILL.md is an enterprise-only sub-agent provided by
  # olav-ent — the free distribution does not ship it.
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
| analyze (inspectors) | `True` | networkx / DuckDB only |
| analyze (diff) | `True` | local comparison only |
| analyze (topology) | `True` | graph algorithms only |
| sim | N/A | no sandbox — Batfish HTTP via batfish_q @tool |
| lab (enterprise) | `False` | pushes configs via httpx to ContainerLab |
| collect (probe) | N/A | no sandbox — uses execute_cli_parallel |

`network_isolation=True` closes all network egress (urllib / aiohttp /
raw socket) via `unshare --net` when available.
