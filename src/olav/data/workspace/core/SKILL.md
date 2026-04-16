---
name: core
description: "Core platform agent — data queries directly, delegates to writer/api_query/remote/admin subagents"
tools:
  - execute_sql
  - recall_memory
  - web_search
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
  - path: ./references/REQUIRED_INFO_CHECK.md
metadata:
  version: 4.0.0
  type: core
  category: platform
---

# Core Workspace

Core orchestrator directly handles data queries (3 tools + olav_delegate).
Other capabilities are delegated to subagents:
- `writer` — format tables, charts, reports, scripts (unified output engine)
- `db_query` — complex multi-step database queries
- `api_query` — API requests, health checks
- `remote` — SSH, shell commands
- `admin` — platform management, deployment, cron
