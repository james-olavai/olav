---
name: config-orchestrator
description: "Config & System Agent — Data ingestion, schema normalization, self-healing, and framework maintenance"
system_prompt_file: prompts/orchestrator.md
subagents:
  - path: ./sync/SKILL.md
  - path: ./discovery/SKILL.md
  - path: ./creator/SKILL.md
  - path: ./learner/SKILL.md
  - path: ./knowledge/SKILL.md
  - path: ./system/SKILL.md
---

## Overview

The Config Agent handles data ingestion, schema normalization, self-healing, and framework maintenance.

## Subagents

1. **sync** — Snapshot & Sync: Device sync, SSH collection, TextFSM templates
2. **discovery** — Schema Alignment: Fuzzy mapping, topology generation
3. **creator** — Skill Creator: Automating new system/API onboarding
4. **learner** — Command Learner: TextFSM template generation
5. **knowledge** — Knowledge Manager: KB indexing, cache management
6. **system** — Doctor/Self-Healing: System health, log analysis, Skill Builder
