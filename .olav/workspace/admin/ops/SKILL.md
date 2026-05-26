---
name: ops
description: "OLAV platform self-operations — health checks, log export, scheduled job management, diagnostics"
agent_type: api
thinking_mode: enabled
tools:
  - execute_skill_script
scripts:
  - name: check_health
    description: "Validate workspace, DB, environment config, and network connectivity"
    file: check_health.py
  - name: export_logs
    description: "Pack app logs and audit DB rows into a .tar.gz bundle by time window"
    file: export_logs.py
  - name: manage_cron
    description: "List, add, remove, or apply OLAV cron jobs"
    file: manage_cron.py
  - name: analyze_logs
    description: "Query audit.duckdb for log stats, errors, and tool usage"
    file: analyze_logs.py
  - name: bulk_ingest
    description: "Batch ingest staging JSON files from exports/snapshots/json/ into DuckDB"
    file: bulk_ingest.py
system: $ref:./prompts/system.md
---

## ops — platform self-operations sub-agent

Platform operations tools:
observe (check_health), export (export_logs),
schedule (manage_cron), diagnostics (analyze_logs),
and ingest (bulk_ingest).

Service deploy / stop → `olav --agent devops`.

### Tools

| Tool | When to call |
|---|---|
| `check_health()` | User asks "is OLAV healthy?", "what's broken?", "validate workspace" |
| `export_logs(window="24h")` | User asks "export logs", "send me the last N hours of logs", "bundle logs for support" |
| `manage_cron(action=..., ...)` | User asks "list scheduled jobs", "add a daily audit", "remove cron X" |
| `analyze_logs(query=...)` | User asks trend/error/tool usage/model usage in audit logs |
| `bulk_ingest(...)` | User asks for batch data ingest into platform DB |

### check_health outputs

Returns a structured health report covering:
- **Workspace** — SKILL.md frontmatter validity, tool file presence, orphan detection
- **Database** — DuckDB connectivity, schema presence, row counts
- **Environment** — required env vars, API key presence (redacted)
- **Network** — reachability of configured services

### export_logs outputs

Writes `.tar.gz` to `exports/admin_logs/` containing:
- `.olav/logs/*.log` files modified within the window
- `audit_runs.csv`, `audit_tool_calls.csv`, `audit_events.csv` from audit.duckdb
- `manifest.json` with export metadata

### Hard rules

1. Never guess platform state — call `check_health` and read the result.
2. `export_logs` writes to disk; confirm the target path with the user before opening the archive.
3. `manage_cron` mutations (add/remove/apply) require explicit user intent — do not infer.
