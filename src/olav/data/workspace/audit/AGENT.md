---
name: audit-orchestrator
description: "Audit & Learning — runs health check Profiles, authors / extends Profiles, plus schema discovery, TextFSM learning, trace analysis"
system_prompt_file: prompts/orchestrator.md
route_keywords:
  - audit health check compliance report profile SLA
  - 审计 健康检查 合规 报告
  - create design build profile threshold baseline
  - run execute audit report summary executive
  - learn command TextFSM template generate teach
  - schema discover map field column view
  - trace analyze failure pattern improve self-healing
# Rev 259 (2026-05-11): Run vs Author split experiment.
# The orchestrator routes:
#   - Run prompts ("run X", "generate report") → runner sub-agent
#   - Author prompts ("create/extend/retune profile") → author sub-agent
#   - Curator prompts ("discover schema", "learn template") → curator sub-agent
# Each sub-agent has a focused tool set + shorter SKILL.md so that
# small models (gemma4 31b nothink) have fewer simultaneous decision
# points to track.
# Orchestrator stays pure delegation; whitelist 2 low-risk reads only.
# task_return_direct: every sub-agent (runner/author/curator) returns a
# complete user-facing artifact (markdown report / profile path / schema
# discovery output). With this flag set, `_patched_build_task_tool` (in
# src/olav/agents/agent.py) marks the deepagents `task` tool as terminal
# at compile time, so the orchestrator exits after a sub-agent reply
# rather than doing a second LLM round-trip to "format" it. This kills
# the orchestrator-layer paraphrase that duplicated render_report's
# executive summary on small models (gemma4) — see 2026-05-12 fix.
task_return_direct: true
tools:
  - recall_memory   # Check prior audit runs / profile decisions
  - web_search      # Verify unknown audit-domain terms
subagents:
  - path: ./audit-runner/SKILL.md   # Run mode (run_map_engine + render_report)
  - path: ./audit-author/SKILL.md   # Profile Authoring (save_profile + append_jobs + 5 supporting skill scripts)
  - path: ./curator/SKILL.md  # Schema discovery + TextFSM learning + trace analysis
---

## Overview

The Audit Agent implements the v4.0 Map-Reduce architecture for network
health reporting, split into three focused sub-agents (rev 259):

- **Runner** — Executes an existing Profile against the DB and produces
  a Markdown health report. Two tool calls (`run_map_engine` →
  `render_report`), strictly deterministic.

- **Author** — Creates, extends, or retunes Profile files. Uses
  Pydantic-typed `save_profile` / `append_jobs` (LangChain
  StructuredTools — grammar-constrained at LLM decode time). Merged
  from the v0.18.0 `designer` sub-agent in Round 17.

- **Curator** — Schema discovery, TextFSM template learning, trace
  pattern curation. Renamed from `learner` in Round 34 per ADR-0003 B.2.

## Routing

| User intent | Route to |
|---|---|
| Run a profile / generate health report | runner |
| Create / extend / retune a Profile | author |
| List profiles | author (owns `list_profiles` skill script) |
| Discover schema / map fields / learn TextFSM / analyze traces | curator |

## Profiles

Profiles live in `profiles/*.md` — YAML frontmatter (Jobs + queries) +
Markdown body. Each Job carries:
- A parameterized DuckDB SQL (`INTERVAL :window`) or LanceDB semantic query
- A `section_prompt` (business-logic only; format rules are in
  `runner/prompts/system_envelope.md`)
- `type: sql | lancedb`, `severity: Critical | Warning | Info`, `name`
