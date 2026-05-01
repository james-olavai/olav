---
name: netops_ops
description: "Operations orchestrator — network ops, service deployment, SQL queries, device CLI, snapshots"
tools:
  # Orchestrator-direct tools — keep minimal (B-round slim 2026-04-30):
  # delegate to sub-agents for everything else.
  - execute_cli         # live CLI (orchestrator-direct for quick liveness)
  - take_snapshot       # fresh capture (when DB stale)
  - search_logs         # syslog Parquet (R100/S5 shared platform tool)
  # Folded — invoke via olav_delegate or core/services agents:
  #   register_service / record_network_event → services agent
  #   search_commands → ops/collect when needed
  #   diff_configs → ops-analyze owns it as skill script (R92.3)
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
| Query network DB | `execute_sql` |
| Live CLI on devices | `execute_cli` |
| Capture device state | `take_snapshot` |
| Syslog search | `search_logs` |
| KB document search | `search_knowledge_lancedb` |
| Recall past decisions | `recall_memory` |
| Schema introspection | `describe_table('netops.<view>')` |
| Web search | `web_search` |
| Save markdown to exports/ | `format_and_export` |
| Read existing file | `read_file` |
| Service deploy / install | delegate via `olav_delegate` to services |
| Register service API | delegate to services agent |
| Find CLI cmd by platform/keyword | delegate to ops-collect |

## References (load on demand — do NOT preload)

* `references/DB_SCHEMA.md` — `netops.*` tables + `v_*_auto` views + raw fallback
* `references/OUTPUT_EXPORT_RULES.md` — when/where to call `format_and_export`
* `references/TOOL_PARTITIONING.md` — orchestrator vs sub-agent intent map
* `references/SERVICE_DEPLOYMENT.md` — service deploy pattern

NEVER call `execute_sql` just to discover table names — read
`references/DB_SCHEMA.md` and write the query directly.  When the
column shape is unclear, use `describe_table('netops.<view>')`
instead of guessing.
