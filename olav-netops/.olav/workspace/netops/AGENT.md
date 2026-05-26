---
name: netops
description: "Network Operations — SSH collection, BGP/OSPF analysis, topology queries, simulation, drift detection, ContainerLab digital twin, parser learning"
system_prompt_file: prompts/orchestrator.md
# 2026-05-15: gemma4:31b 全栈策略 — 仅 analyzer (PLAN-Act-Reflect 子代理)
# 用 thinking ON；orchestrator + 所有其他 sub-agent 走 thinking OFF.
# 编排器只做关键字路由 + dispatch，不需要 reasoning。早期 R-VERTICAL-SLICE
# 让 orchestrator think 是 qwen3 时代的设计；gemma4 nothink 在路由 layer
# 已实证够用 (rev 261/267/268)，多阶段推理交给 analyzer。
# FINDING-07: thinking_mode intentionally diverges between workspace copies:
# root workspace: enabled — reverted 2026-05-18 for dev + non-gemma4 deployments
#   (orchestrator intent-routing regression without it — Ch9b audit test).
# olav-netops (this file): disabled — gemma4:31b nothink strategy (dev_docs/77 §3.2);
#   routing layer proven sufficient without thinking in gemma4 deployment profile.
thinking_mode: disabled
route_keywords:
  - network device router switch firewall CLI SSH show
  - BGP OSPF EIGRP routing neighbor adjacency protocol session
  - topology link interface LLDP CDP VLAN STP MTU
  - snapshot collect probe ping traceroute liveness
  - diff drift compare baseline configuration
  - lab containerlab digital twin convergence SRL CAB
  - simulate what-if failure blast-radius decommission
  - learn parser textfsm command unparseable
  - explore audit autonomous investigation finding discover hypothesis
  - ingest bundle import rancid snapshot offline
  - 路由 拓扑 接口 采集 快照 故障 漂移 模拟 学习 探索 发现 离线 包 导入
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
  # 2026-05-26: analyzer split (ISSUE-AGENT-TOOL-BLOAT fix).
  # analyzer = Mode A (change planning, 4+3=7).
  # reporter = Mode B+C (investigation + blast radius, 4+3=7).
  - path: ./analyzer/SKILL.md      # Mode A: change-plan drafter.
                                   # 7 tools: execute_sql / describe_table /
                                   # inspect_devices / inspect_interfaces /
                                   # diff_configs / format_and_export.
                                   # Route: "plan / add / change / modify / 变更"
  - path: ./reporter/SKILL.md      # Mode B+C: investigation reporter + blast radius.
                                   # 7 tools: execute_sql / describe_table /
                                   # query_evidence / diff_snapshots /
                                   # inspect_blast_radius / format_and_export.
                                   # Route: "investigate / audit / why / blast radius / drift"
  - path: ./simulator/SKILL.md     # Batfish-backed config-layer evaluator
                                   # (dev_docs/77 §2 2026-05-14).  3 tools:
                                   # batfish_capability / batfish_q /
                                   # format_and_export.
  - path: ./collector/SKILL.md
  - path: ./importer/SKILL.md      # offline file gather — bundle / rancid /
                                   # vendor dump landed via the same downstream
                                   # as live SSH (dev_docs/80).
  - path: ./topology/SKILL.md
  - path: ./learner/SKILL.md       # parser learning (learn_commands / cmd_learn / draft_parser…)
  # 2026-05-19: explorer migrated to audit/explorer/ — it is an audit-domain
  # capability (open-ended health exploration), not a netops sub-agent.
  # Route: "find issues / autonomous scan / no specific question" → olav --agent audit
  # ./lab/SKILL.md is an enterprise-only sub-agent provided by
  # olav-ent — the free distribution does not ship it.
  - path: ../core/writer/SKILL.md  # format_and_export / save
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
