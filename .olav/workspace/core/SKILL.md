---
name: core
description: "Core platform tools — available globally in all agents and workspaces."
tools:
  - run_python_code          # Pure-computation Python sandbox (no IO/shell)
  - execute_sql              # DuckDB query with read-only/write approval gate
  - web_search               # Web search via DuckDuckGo
  - recall_memory            # Recall from semantic memory (LanceDB)
  - search_knowledge_lancedb # Semantic KB search (LanceDB vector store)
  - format_and_export        # Write reports/CSV/JSON to exports/
  - deploy_service           # Docker Compose lifecycle — up, health-check, logs
  - write_workspace_file     # Write files to .olav/workspace or .olav/services
  - run_shell                # Shell command execution (docker, git, curl, etc.)
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
metadata:
  version: 2.0.0
  type: core
  category: platform
---

# Core Workspace

These tools are globally available to **all agents** regardless of active workspace.

| Tool | Purpose |
|------|---------|
| `run_python_code` | Pure-computation sandbox — data parsing, format conversion, graph algorithms |
| `execute_sql` | DuckDB queries; SELECT is read-only, mutating SQL requires approval |
| `web_search` | DuckDuckGo search for external documentation or known issues |
| `recall_memory` | Recall relevant past decisions from semantic memory (LanceDB) |
| `search_knowledge_lancedb` | Semantic search over indexed KB documents |
| `format_and_export` | Write markdown reports, CSV, JSON to `exports/` |
| `deploy_service` | Start any Docker Compose service, wait for health, return logs on failure |
| `write_workspace_file` | Write any file to `.olav/workspace/` or `.olav/services/` |
| `run_shell` | Execute shell commands — docker, git, curl, file ops |

## Design Principle

Core tools are **platform infrastructure** — any agent or subagent may need them
regardless of domain. Agent-specific tools (execute_cli, diff_configs, etc.)
stay in their respective workspace SKILL.md.
