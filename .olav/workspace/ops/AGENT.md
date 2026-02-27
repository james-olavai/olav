---
name: ops-orchestrator
description: "Operations Agent — Deep troubleshooting with full ReAct loop"
system_prompt_file: prompts/orchestrator.md
subagents:
  - path: ./routing/SKILL.md
  - path: ./topology/SKILL.md
  - path: ./probe/SKILL.md
  - path: ./diff/SKILL.md
---

## Overview

The Operations Agent is the deep-dive troubleshooting expert. It orchestrates a team of specialized subagents to diagnose complex network faults.

## Subagents

1. **routing** — BGP, OSPF, static routes, routing blackholes
2. **topology** — MAC tables, ARP, physical links, loop detection (STP), CDP/LLDP
3. **probe** — Active liveness detection, latency testing, network segment exploration
4. **diff** — Time-series drift detection between snapshots
