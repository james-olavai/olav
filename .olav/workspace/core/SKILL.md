---
name: core
description: "Core platform tools — available globally in all agents and workspaces."
tools:
  - api_request              # Authenticated API request to any registered service
  - run_python_code          # Pure-computation Python sandbox (no IO/shell)
  - execute_sql              # DuckDB query with read-only/write approval gate
  - web_search               # Web search via DuckDuckGo
  - recall_memory            # Recall from semantic memory (LanceDB)
  - search_knowledge_lancedb # Semantic KB search (LanceDB vector store)
  - format_and_export        # Write reports/CSV/JSON to exports/
  - deploy_service           # Docker Compose lifecycle — up, health-check, logs
  - stop_service             # Docker Compose stop/down + list running services
  - write_workspace_file     # Write files to .olav/workspace or .olav/services
  - run_shell                # Shell command execution (docker, git, curl, etc.)
  - list_cron                # List all olav-managed cron jobs
  - add_cron                 # Add or update a scheduled olav task (natural language → crontab)
  - remove_cron              # Remove a scheduled olav task by agent + instruction
  - apply_cron_schedules     # Apply cron_schedules.yaml declaratively
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
  - path: ./references/REQUIRED_INFO_CHECK.md
metadata:
  version: 2.0.0
  type: core
  category: platform
---

# Core Workspace

These tools are globally available to **all agents** regardless of active workspace.

| Tool | Purpose |
|------|---------|
| `api_request` | Authenticated API request to any registered service (auth automatic, writes require HITL) |
| `run_python_code` | Pure-computation sandbox — data parsing, format conversion, graph algorithms |
| `execute_sql` | DuckDB queries; SELECT is read-only, mutating SQL requires approval |
| `web_search` | DuckDuckGo search for external documentation or known issues |
| `recall_memory` | Recall relevant past decisions from semantic memory (LanceDB) |
| `search_knowledge_lancedb` | Semantic search over indexed KB documents |
| `format_and_export` | Write markdown reports, CSV, JSON to `exports/` |
| `deploy_service` | Start any Docker Compose service, wait for health, return logs on failure |
| `stop_service` | Stop or remove a running Docker Compose service; `list_services()` shows all |
| `write_workspace_file` | Write any file to `.olav/workspace/` or `.olav/services/` |
| `run_shell` | Execute shell commands — docker, git, curl, file ops |
| `list_cron` | List all olav-managed scheduled tasks |
| `add_cron` | Add or update a cron job: natural language → system crontab |
| `remove_cron` | Remove a scheduled task by agent + instruction |
| `apply_cron_schedules` | Declaratively apply `.olav/workspace/ops/netops_init/config/cron_schedules.yaml` |

## Design Principle

Core tools are **platform infrastructure** — any agent or subagent may need them
regardless of domain. Agent-specific tools (execute_cli, diff_configs, etc.)
stay in their respective workspace SKILL.md.
