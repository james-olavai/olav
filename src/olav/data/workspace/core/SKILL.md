---
name: core
description: "Core platform agent — data queries directly, delegates to api_query/remote/admin subagents"
tools:
  - execute_sql
  - recall_memory
  - web_search
  - format_and_export
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
  - path: ./references/REQUIRED_INFO_CHECK.md
metadata:
  version: 4.0.0
  type: core
  category: platform
---

# Core Workspace

Core orchestrator directly handles data queries (4 tools).
Other capabilities are delegated to subagents:
- `db_query` — database queries, knowledge base, web search, export
- `api_query` — API requests, health checks, web search, export
- `remote` — SSH, shell commands
- `admin` — platform management, deployment, cron
