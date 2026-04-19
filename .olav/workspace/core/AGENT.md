---
name: core
kind: Agent
description: "OLAV core agent — unified entry point for queries, CLI, KB search, and platform operations (v0.15+)"
version: "3.2.0"
system_prompt_file: prompts/system.md
subagents:
  - path: ./writer/SKILL.md
  - path: ./admin/SKILL.md
  - path: ./api_query/SKILL.md
  - path: ./db_query/SKILL.md
  - path: ./remote/SKILL.md
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
  - path: ./references/REQUIRED_INFO_CHECK.md
# ARCH-17: lazy-load — SKILL_DEVELOPMENT (~3K) + REQUIRED_INFO_CHECK (~2K) only
# get injected when router intent-matches; saves ~5K tokens on plain queries.
static_context_mode: on_intent
---

# Core Workspace (v0.15+)

Unified platform agent — the default entry point for all `olav "<question>"` queries.

Always present; cannot be uninstalled.

## Capabilities (v0.18.1, post ADR-0006)

Per [ADR-0006](../../../docs/adr/0006-core-seven-cross-domain-tools.md),
core advertises **7 cross-domain tools** (`run_python_code`, `execute_sql`,
`recall_memory`, `search_knowledge_lancedb`, `web_search`,
`format_and_export`, `manage_cron`). Domain-specific tools live in the
matching top-level agent or `core/*` sub-agent — see SKILL.md for the
full capability-scoping table.

### Direct Handling (no --agent needed)
- **Cross-domain computation & data** — `run_python_code`, `execute_sql`
- **Memory & KB** — `recall_memory`, `search_knowledge_lancedb`, `web_search`
- **Output** — `format_and_export`
- **Scheduling** — `manage_cron` (list / add / remove / apply)
- **Document writing** — polish/edit markdown → escalates to `core/writer/` sub-agent

### Escalation Hints
When a query requires domain-specific tools, core routes via sub-agents or suggests:
- Network CLI / BGP / OSPF / config diff / snapshot → `--agent ops` (or orchestrator `task("ops-analyze"/"ops-collect", ...)`)
- Compliance reports / audit profiles → `--agent audit`
- Lab / CAB simulations → `--agent ops "<CAB task>"` (ops orchestrator delegates to `ops/lab/` sub-agent)
- Service registration / API integrations → `--agent services`
- File writes / shell commands → handled internally via `core/admin/` + `core/remote/` sub-agents

## Sub-agents

- `core/writer/` — Document editing and polishing specialist
- `core/admin/` — Platform administration (`write_workspace_file`, `deploy_service`, `stop_service`, `manage_cron`)
- `core/remote/` — Shell execution (`run_shell`)
- `core/db_query/` — DB + memory + KB + export helpers (symlinks to core/tools/ canonical)
- `core/api_query/` — API integration helpers (`api_request` symlink, web search, export)
