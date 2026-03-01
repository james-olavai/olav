---
name: ops-orchestrator
description: "Operations Agent — Deep troubleshooting with full ReAct loop"
system_prompt_file: prompts/orchestrator.md
subagents:
  - path: ./routing-simulator/SKILL.md
  - path: ./topology/SKILL.md
  - path: ./probe/SKILL.md
  - path: ./diff/SKILL.md
  - path: ../log-analytics/SKILL.md
---

## Overview

The Operations Agent is the deep-dive troubleshooting expert. It orchestrates a team of specialized subagents to diagnose complex network faults and predict change impacts.

## Subagents

1. **routing-simulator** — BGP, OSPF, static routes, routing analysis + deterministic What-If simulation (networkx + netutils sandbox). Replaces `routing` (v1) and `simulation` (v0.1).
2. **topology** — MAC tables, ARP, physical links, loop detection (STP), CDP/LLDP
3. **probe** — Active liveness detection, latency testing, network segment exploration
4. **diff** — Time-series drift detection between snapshots
