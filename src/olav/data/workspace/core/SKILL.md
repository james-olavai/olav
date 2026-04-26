---
name: core
description: "Core platform agent — data queries directly, delegates to writer/api_query/remote/admin subagents"
tools:
  - execute_sql
  - recall_memory
  - web_search
  # R85 (dev_docs/62 § "R85 inline-save"): format_and_export promoted
  # from writer-only to shared core capability so any agent that
  # produces report data can save it directly.  Writer keeps it via
  # the same inheritance path and remains the polish/edit subagent.
  - format_and_export
  # R86 follow-up: read_file promoted same way.  Any agent (orch,
  # ops-lab consuming a CAB spec, audit consuming a profile) needs
  # to load text files from disk.  Lives at core/tools/read_file.py.
  - read_file
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
  - path: ./references/REQUIRED_INFO_CHECK.md
  - path: ./references/SCHEMA_REFERENCE.md
# R86 (dev_docs/62 § "R86"): on_intent — references load only when the
# model's first turn keyword-matches.  SCHEMA_REFERENCE.md (~2.3K
# tokens) was always-baked even when the query didn't need DB schema
# detail; the agent already gets schema_knowledge memory entries
# auto-injected by the recall middleware so the static reference is
# now a backstop, not a primary source.
static_context_mode: on_intent
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
