---
name: config-orchestrator
description: "Config & System Agent — Data ingestion, schema normalization, self-healing, and framework maintenance"
system_prompt_file: prompts/orchestrator.md
subagents:
  - path: ./discovery/SKILL.md
  - path: ./creator/SKILL.md
  - path: ./knowledge/SKILL.md
  - path: ./system/SKILL.md
  # sync and learner are netops-specific — injected by olav-netops via MANIFEST
---

## Overview

The Config Agent handles data ingestion, schema normalization, self-healing, and framework maintenance.

## Subagents

1. **discovery** — Schema Alignment: Fuzzy mapping, topology generation
2. **creator** — Skill Creator: Automating new system/API onboarding
3. **knowledge** — Knowledge Manager: KB indexing, cache management
4. **system** — Doctor/Self-Healing: System health, log analysis, Skill Builder

> **Domain Skills (injected by domain packages)**:
> - `sync` (olav-netops) — Snapshot & Sync: Device sync, SSH collection, TextFSM templates
> - `learner` (olav-netops) — Command Learner: TextFSM template generation

---

## Design Principle: LLM Native

**KISS = 数据驱动，不硬编码**

- Protocol recipes: `topology_protocol_recipes` 表驱动拓扑状态判断（无硬编码协议逻辑）
- View recipes: `view_recipes` 表驱动 LLM 动态编译视图（`v_*_auto` 代替预定义 JOIN）
- Sandbox discovery: 运行时查询数据库，自动适应网络拓扑变化

**核心**：新增协议/命令只需 `INSERT`，无需改代码。
