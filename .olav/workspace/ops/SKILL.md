---
name: ops-orchestrator
description: "Operations orchestrator — network ops, service deployment (deploy/install/set up any container service), SQL queries, device CLI, snapshots"
tools:
  - execute_cli
  - search_commands
  - take_snapshot
  - diff_configs
  - record_network_event
  - register_service
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

# Ops Orchestrator Tools

Direct tools available to the orchestrator (not delegated to subagents):

| Task intent | Tool(s) |
|---|---|
| **"Deploy / install / set up / stand up [any service]"** | `write_workspace_file` (files first) → `deploy_service` (start + health) |
| Ad-hoc docker/shell commands, check logs | `run_shell` |
| Register service API schema, generate tools | `register_service` |
| Query network DB (devices, interfaces, BGP, OSPF) | `execute_sql` |
| Run live CLI on network devices | `execute_cli` |
| `search_commands` | Find available CLI commands by platform/keyword |
| `search_knowledge_lancedb` | Semantic search of KB documents |
| `recall_memory` | Recall relevant past decisions and context |
| `record_network_event` | Persist network events to memory |
| `take_snapshot` | Capture live device state snapshot into DB |
| `format_and_export` | Write markdown reports to exports/ |
| `web_search` | Search the web for documentation or known issues |

## Output Export Rules

**When a subagent returns a Mermaid diagram, simulation result, or analysis report:**
1. ALWAYS call `format_and_export` to save the output to `exports/`
2. Use descriptive filenames: `topology_YYYYMMDD.mmd`, `sim_<scenario>_YYYYMMDD.md`
3. Tell the user the saved path

| Subagent output type | Save to | Format |
|---|---|---|
| Mermaid topology | `exports/topology_YYYYMMDD.mmd` | `.mmd` (raw Mermaid, no code fences) |
| Simulation result | `exports/simulations/sim_<name>_YYYYMMDD.md` | Markdown |
| Analysis report | `exports/reports/<name>_YYYYMMDD.md` | Markdown |
| CAB report | `exports/cab_report_<name>_YYYYMMDD.md` | Markdown |
