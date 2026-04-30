---
name: ops-orchestrator
description: "Operations orchestrator — network ops, service deployment, SQL queries, device CLI, snapshots"
tools:
  - execute_cli
  - search_commands
  - take_snapshot
  - diff_configs
  - record_network_event
  - register_service
  # R100/S5: syslog Parquet search — shared platform tool
  - search_logs
static_context:
  - path: ../core/references/REQUIRED_INFO_CHECK.md
metadata:
  version: 2.1.0
  required_params:
    service_deployment:
      - admin_password_or_secret
      - port_mapping
      - base_dn_or_org_name
      - data_persistence_path
    device_cli:
      - hostname_or_ip
      - platform
    snapshot:
      - device_list_confirmed
---

# Ops orchestrator — direct tools

| Task intent | Tool |
|---|---|
| Deploy / install service | `write_workspace_file` → `deploy_service` |
| Ad-hoc docker / shell / logs | `run_shell` |
| Register service API + generate tools | `register_service` |
| Query network DB | `execute_sql` |
| Live CLI on devices | `execute_cli` |
| Find CLI commands by platform/keyword | `search_commands` |
| KB document search | `search_knowledge_lancedb` |
| Recall past decisions | `recall_memory` |
| Persist network events | `record_network_event` |
| Capture device state | `take_snapshot` |
| Write markdown to exports/ | `format_and_export` |
| Web search | `web_search` |

## References (load on demand — do NOT preload)

* `references/DB_SCHEMA.md` — `netops.*` tables + `v_*_auto` views + raw fallback
* `references/OUTPUT_EXPORT_RULES.md` — when/where to call `format_and_export`
* `references/TOOL_PARTITIONING.md` — orchestrator vs sub-agent intent map
* `references/SERVICE_DEPLOYMENT.md` — service deploy pattern

NEVER call `execute_sql` just to discover table names — read
`references/DB_SCHEMA.md` and write the query directly.  When the
column shape is unclear, use `describe_table('netops.<view>')`
instead of guessing.
