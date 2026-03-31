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
  - path: ./oc/SKILL.md
---

## Overview

The Operations Agent is the deep-dive troubleshooting expert. It orchestrates a team of specialized subagents to diagnose complex network faults, predict change impacts, and validate changes via ContainerLab digital twin emulation.

## Subagents

1. **sim** — BGP, OSPF, static routes, routing analysis + deterministic What-If simulation (networkx + netutils sandbox). Replaces `routing` (v1) and `simulation` (v0.1).
2. **topology** — MAC tables, ARP, physical links, loop detection (STP), CDP/LLDP
3. **probe** — Active liveness detection, latency testing, network segment exploration
4. **diff** — Time-series drift detection between snapshots
5. **lab** — ContainerLab digital twin emulation for CAB gate validation (deploys real SR Linux containers, pushes OC-derived config, asserts protocol convergence)
6. **oc** — OC Coverage Engineer. Audits OpenConfig transform coverage, generates missing LLM transforms, repairs openconfig-unknown rows, backfills historical snapshots.
