---
name: audit-orchestrator
description: "OLAV Audit & SLE Agent — Network health inspection, compliance and root-cause report generation (v4.0)"
system_prompt_file: prompts/orchestrator.md
subagents:
  - path: ./designer/SKILL.md
  - path: ./auditor/SKILL.md
---

## Overview

The Audit Agent implements the v4.0 Map-Reduce architecture for network health reporting:

- **Designer** — Explores the DuckDB/LanceDB schema, drafts and validates Profile queries.
- **Auditor** — Executes Profiles (Phase 1 Map) and renders segmented Markdown reports (Phase 2+3 Reduce).

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
