---
name: audit-orchestrator
description: "Audit — runs health check Profiles, authors / extends Profiles, open-ended data investigation"
route_keywords:
  - audit health check compliance report profile SLA
  - 审计 健康检查 合规 报告
  - create design build profile threshold baseline
  - run execute audit report summary executive
  - explore investigation data-driven explore anomaly evidence query
# Rev 259 (2026-05-11): Run vs Author split.
# Rev N (2026-05-27): Removed curator sub-agent — all scripts were dead code:
#   discover_view_schemas superseded by view_builder R83.2; fuzzy_map_schema
#   depended on removed view_recipes; sync_schema_reference had wrong path;
#   scaffold_domain_agent duplicated by admin/editor; trace_learner now runs
#   automatically via AuditMiddleware._bg_trace_learn() after every agent run.
# task_return_direct: every sub-agent returns a complete user-facing artifact.
# `_patched_build_task_tool` marks the deepagents `task` tool as terminal so
# the orchestrator exits after a sub-agent reply (kills duplicate summaries
# on small models like gemma4).
task_return_direct: true
tools:
  - olav_recall_memory   # Check prior audit runs / profile decisions
  - web_search      # Verify unknown audit-domain terms
subagents:
  - path: ./audit-runner/SKILL.md    # Run mode (run_map_engine + render_report)
  - path: ./audit-author/SKILL.md    # Profile Authoring (save_profile + append_jobs + supporting scripts)
  - path: ./explorer/SKILL.md  # Data-driven investigation: query evidence, explore anomalies
---

## Overview

The Audit Agent implements the v4.0 Map-Reduce architecture for network
health reporting, split into three focused sub-agents:

- **Runner** — Executes an existing Profile against the DB and produces
  a Markdown health report. Two tool calls (`run_map_engine` →
  `render_report`), strictly deterministic.

- **Author** — Creates, extends, or retunes Profile files. Uses
  Pydantic-typed `save_profile` / `append_jobs` (LangChain
  StructuredTools — grammar-constrained at LLM decode time).

- **Explorer** — Open-ended data investigation. Freely queries the DB,
  decides what to investigate, and writes a prioritised findings report.
  Use when the user has no specific profile in mind.

## Routing

| User intent | Route to |
|---|---|
| Run a profile / generate health report | runner |
| Create / extend / retune a Profile | author |
| List profiles | author (owns `list_profiles` skill script) |
| Find issues / explore the network / autonomous discovery | explorer |

## Profiles

Profiles live in `profiles/*.md` — YAML frontmatter (Jobs + queries) +
Markdown body. Each Job carries:
- A parameterized DuckDB SQL (`INTERVAL :window`) or LanceDB semantic query
- A `section_prompt` (business-logic only; format rules are in
  `runner/prompts/system_envelope.md`)
- `type: sql | lancedb`, `severity: Critical | Warning | Info`, `name`
