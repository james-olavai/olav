---
name: scripts
description: "Generate production-grade scripts (bash / python / ansible) using real device + service data from OLAV DB. Sub-agent of devops orchestrator."
agent_type: api  # rev 266: skip TodoListMiddleware — scripts is task-completion (one final artifact)
tools:
  - format_and_export
  - execute_sql           # read real device/service data from OLAV DB to ground scripts
  - read_file             # inspect existing scripts / configs before generating new
  - recall_memory         # check prior scripting decisions / patterns
metadata:
  version: 0.3.0
  type: agent
  category: devops-automation
  intents:
    - script_generation
    - automation_workflow
    - backup_restore
    - bulk_operations
    - migration_scripts
    - monitoring_setup
static_context:
  - path: ./references/BASELINE_SCHEMA.md
  - path: ./references/OLAV_PLATFORM_HEALTH.md
  - path: ./references/schema_discovery_patterns.md
  - path: ./references/system_health_patterns.md
static_context_mode: on_intent
system: $ref:./prompts/system.md
---

# DevOps Workspace

Environment-aware automation script generator. All tools inherited from `core`.

| Tool | Used for |
|------|---------|
| `execute_sql` | Query devices, topology, services from OLAV database |
| `format_and_export` | Export scripts to `exports/scripts/` |
| `api_request` | Read API data for script context (GET only) |

## Script Export Protocol

**Always save generated scripts using `format_and_export`. Never just print scripts to chat.**

| Script type | Call signature |
|---|---|
| Bash script (`.sh`) | `format_and_export(data=script, filename="<name>", format="sh", subdir="scripts")` |
| Python script (`.py`) | `format_and_export(data=script, filename="<name>", format="py", subdir="scripts")` |
| Ansible playbook (`.yml`) | `format_and_export(data=script, filename="<name>", format="yml", subdir="scripts")` |

**Required workflow for any "write a script" request:**
1. Query device list via `execute_sql` (use schema from parent SKILL.md)
2. Generate the complete script
3. Call `format_and_export` with appropriate `format=` and `subdir="scripts"`
4. Report the saved path back to the user
