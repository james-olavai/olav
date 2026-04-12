---
name: core
kind: Agent
description: "OLAV core agent — unified entry point for queries, CLI, KB search, and platform operations (v0.15+)"
version: "3.0.0"
system_prompt_file: prompts/system.md
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
  - path: ./references/REQUIRED_INFO_CHECK.md
---

# Core Workspace (v0.15+)

Unified platform agent — the default entry point for all `olav "<question>"` queries.

Always present; cannot be uninstalled.

## Capabilities

### Direct Handling (no --agent needed)
- **Network CLI queries** — "R1 show version", "R1 BGP neighbors?" → `execute_cli` / `execute_sql`
- **KB/log search** — semantic search over documents and syslog records
- **Platform ops** — skill development, service registration, config management
- **Document writing** — polish/edit markdown → escalates to `core/writer/` sub-agent

### Escalation Hints
When a query requires deep operations, core suggests the right agent:
- Complex network changes → `--agent ops`
- Compliance reports → `--agent audit`
- Lab simulations → `--agent ops-lab`

## Built-in Tools

- `execute_cli` — Nornir/Netmiko CLI execution on network devices
- `execute_sql` — DuckDB queries (read-only default; writes require HITL)
- `search_commands` — Query the commands table by device/platform/keyword
- `run_python_code` — Pure-computation Python sandbox
- `recall_memory` — Semantic memory recall (LanceDB)
- `web_search` — DuckDuckGo web search
- `execute` — Shell tool injected by LocalShellBackend

## Sub-agents

- `core/writer/` — Document editing and polishing specialist
