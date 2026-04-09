---
name: config-orchestrator
description: "Config lifecycle orchestrator — data ingestion, schema normalization, self-healing, and framework maintenance"
tools:
  - execute_cli              # Run live CLI commands on network devices via SSH
  - bulk_ingest              # Bulk-load staging JSON snapshots into DuckDB (atomic)
  - diff_configs             # Diff two snapshots or config files
  - search_commands          # Search available CLI commands by platform/keyword
static_context:
  - path: ../core/references/REQUIRED_INFO_CHECK.md
metadata:
  version: 1.1.0
  type: orchestrator
  category: config-management
---

# Config Orchestrator Tools

Direct tools available to the config-orchestrator (not delegated to subagents).

| Task intent | Tool(s) |
|---|---|
| Query device/topology/schema data | `execute_sql` |
| Run live CLI on network devices | `execute_cli` |
| Load snapshot data into DuckDB | `bulk_ingest` |
| Compare two snapshots or config files | `diff_configs` |
| Save reports, diagrams | `format_and_export` |
| Find CLI templates by platform/keyword | `search_commands` |
| Semantic KB search | `search_knowledge_lancedb` |
| Web documentation lookup | `web_search` |

## Design Principle

Config orchestrator **does NOT run tools on behalf of subagents** — it delegates:
- Complex schema work → `task(subagent_type="config-discovery")`
- System health/repair → `task(subagent_type="config-system")`
- Knowledge indexing → `task(subagent_type="config-knowledge")`
- **API onboarding / script generation** → `olav --agent devops` (not config)

Direct tools are for reconnaissance (`execute_sql`, `execute_cli`) and
data lifecycle (`bulk_ingest`, `diff_configs`, `format_and_export`).
