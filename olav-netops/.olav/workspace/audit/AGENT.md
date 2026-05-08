---
name: audit-orchestrator
description: "Audit & Learning — health check profiles, compliance reports, TextFSM template learning, schema discovery, trace analysis"
system_prompt_file: prompts/orchestrator.md
route_keywords:
  - audit health check compliance report profile SLA
  - 审计 健康检查 合规 报告
  - create design build profile threshold baseline
  - run execute audit report summary executive
  - learn command TextFSM template generate teach
  - schema discover map field column view
  - trace analyze failure pattern improve self-healing
# Patch D' Step 2.5 (2026-05-08): orchestrator is pure delegation —
# the prompt explicitly routes Design / Execute requests to the
# Designer / Auditor sub-agents.  No direct execute_sql, no
# write-class tools.  Whitelist 2 low-risk reads only; everything
# else delegates.
tools:
  - recall_memory   # Check prior audit runs / profile decisions
  - web_search      # Verify unknown audit-domain terms
subagents:
  - path: ./auditor/SKILL.md
  - path: ./curator/SKILL.md  # Round 34: renamed from learner per ADR-0003 B.2
---

## Overview

The Audit Agent implements the v4.0 Map-Reduce architecture for network health reporting:

- **Auditor** — Profile authoring + execution (map_engine + render_report) + correlation pass. Merged from v0.18.0 `designer` sub-agent in Round 17 (Sprint 3 Step B).
- **Curator** — Schema discovery, TextFSM template learning, trace pattern curation. Renamed from `learner` in Round 34 per ADR-0003 B.2.

## Two-Step Execution Model

```
1. map_engine(profile, window)   →  segmented JSON (per-Job findings)
2. render_report(json, profile)  →  Markdown report (per-section + Executive Summary)
```

The Auditor Agent's complete workflow is exactly these two tool calls. No further orchestration is required.

## Profiles

Profiles live in `profiles/*.md` — YAML frontmatter (Jobs + queries) + Markdown body (Global Correlation Pass prompt).

Each Job carries:
- A parameterized DuckDB SQL (`INTERVAL :window`) or LanceDB semantic query
- A `section_prompt` (business-logic only; format rules are in `auditor/prompts/system_envelope.md`)
