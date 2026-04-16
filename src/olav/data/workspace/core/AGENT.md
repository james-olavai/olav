---
name: core
kind: Agent
description: "Core platform agent — data queries, API services, remote execution, platform management"
version: "0.4.0"
system_prompt_file: prompts/system.md
subagents:
  - path: ./db_query/SKILL.md
  - path: ./api_query/SKILL.md
  - path: ./remote/SKILL.md
  - path: ./admin/SKILL.md
  - path: ./writer/SKILL.md
route_keywords:
  - help version status workspace platform health check
  - database SQL query select table column list count how many
  - 列出 查询 多少 数据库 设备列表 统计
  - API service health status grafana jira gitlab monitoring
  - server host disk memory cpu process remote command
  - memory knowledge recall search document import export
  - cron schedule job docker compose deploy
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
---

# Core Workspace

Platform-level agent providing built-in capabilities.
Always present; cannot be uninstalled.

This agent helps users build and operate the OLAV platform itself — developing new skills,
registering external service APIs, and running arbitrary code to explore integrations.

## Orchestrator Tools (direct)

- `execute_sql` — DuckDB database queries
- `recall_memory` — Semantic memory recall (LanceDB)
- `web_search` — DuckDuckGo web search
- `format_and_export` — Output formatting and file export

## Subagents (via olav_delegate)

- `db_query` — Database queries, knowledge base, web search, export
- `api_query` — API service requests, health checks, web search, export
- `remote` — SSH to servers, local shell commands
- `admin` — Platform management, deployment, cron, data ingestion
