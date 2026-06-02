---
name: core
kind: Agent
description: "OLAV core agent — unified entry point for queries, CLI, KB search, and platform operations (v0.15+)"
version: "4.0.0"
system_prompt_file: prompts/core.md
subagents:
  - path: ./writer/SKILL.md
  - path: ./api_query/SKILL.md
  - path: ./db_query/SKILL.md
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

Core keeps a minimal cross-domain surface and delegates domain operations
to dedicated agents/sub-agents.

### Direct Handling (no --agent needed)
- **Cross-domain computation & data** — `run_python_code`, `execute_sql`
- **Memory & KB** — `recall_memory`, `search_knowledge_lancedb`, `web_search`
- **Output** — `format_and_export`
- **Document writing** — polish/edit markdown → escalates to `core/writer/` sub-agent

### Escalation Hints
When a query requires domain-specific tools, core routes via sub-agents or suggests:
- Network CLI / BGP / OSPF / config diff / snapshot → `--agent netops`
- Compliance reports / audit profiles → `--agent audit`
- Service registration / container deploy / authenticated API calls → `--agent services`
- Platform administration (health/logs/cron/deploy/stop/workspace edits) → `--agent admin`
- Lab / CAB simulations → `--agent netops "<CAB task>"`

## Sub-agents

- `core/writer/` — Document editing and polishing specialist
- `core/db_query/` — DB + memory + KB + export helpers (symlinks to core/tools/ canonical)
- `core/api_query/` — API integration helpers (`api_request` symlink, web search, export)
