---
name: admin
description: "OLAV platform self-management — health/log diagnostics, cron, ingest, skill pack installation, workspace scaffolding"
system_prompt_file: prompts/admin.md
route_keywords:
  - health check platform status broken validate workspace
  - export logs bundle support archive log file
  - cron schedule job recurring task
  - workspace health analyze logs bulk ingest
  - install skill pack plugin extension olav-netops olav-ent
  - list skills installed status
  - scaffold new skill agent tool workspace file
  - audit workspace consistency syntax error broken ref
  - platform admin self-management self-development
tools:
  - olav_recall_memory
  - olav_store_memory
task_return_direct: true
subagents:
  - path: ./ops/SKILL.md        # health + logs + cron
  - path: ./installer/SKILL.md  # skill pack query + install
  - path: ./editor/SKILL.md     # workspace audit + scaffold + file editing
---

## Admin — OLAV platform self-management

The admin agent answers one question: **"How is OLAV itself doing, and how do I extend it?"**

Three sub-agents cover distinct concerns:

- **ops** — *observe and operate the platform* (check_health / export_logs / manage_cron)
  + analyze_logs / bulk_ingest
- **installer** — *manage skill packs* (skill_query / skill_install); 3 tools, fast
- **editor** — *extend and repair the workspace* (audit_workspace, scaffold_skill,
  write_workspace_file, tool_help, load_reference, get_static_context); 7 tools, thinking enabled

## Routing

| User intent | Route to |
|---|---|
| "Is OLAV healthy?" / "What's broken?" / "Validate workspace" | `ops` |
| "Export logs" / "Bundle logs for support" / "Last 24h logs" | `ops` |
| "List / add / remove scheduled jobs" / "Set up a daily audit" | `ops` |
| "What skills are installed?" / "Install olav-netops" / "Check skill X" | `installer` |
| "Create a new sub-agent" / "Scaffold a tool skeleton" | `editor` |
| "Edit SKILL.md" / "Write a guide.yaml" | `editor` |
| "Is the workspace consistent?" / "Any broken @tool refs?" | `editor` |

## CLI usage

```bash
olav --agent admin "check platform health"
olav --agent admin "export the last 7 days of logs"
olav --agent admin "install olav-netops from /path/to/pack"
olav --agent admin "scaffold a new sub-agent for database replication checks"
```

## Scope boundary

- Network operations (BGP/OSPF/topology) → `olav --agent netops`
- Service deploy / stop / register / API calls → `olav --agent services`
- Script generation / infra integrations → `olav --agent devops`
- Audit profiles / health reports → `olav --agent audit`
