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

## Database Schema

**Database:** `main.duckdb` (accessed via `execute_sql`). Key tables:

| Table | Key columns |
|---|---|
| `netops.devices` | `hostname`, `ip_address`, `platform`, `vendor`, `model`, `role`, `site`, `os_version`, `last_seen` |
| `netops.parsed_outputs` | `device_name`, `command`, `parsed_data` (JSON), `raw_output`, `snapshot_id`, `ingested_at` |
| `netops.topology_links` | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `link_type`, `link_status`, `discovery_protocol` |

**Common queries — use DIRECTLY without schema exploration:**
```sql
-- List all devices
SELECT hostname, ip_address, platform, vendor FROM netops.devices ORDER BY hostname;

-- Devices by platform
SELECT hostname, ip_address FROM netops.devices WHERE platform LIKE '%ios%';

-- BGP neighbor data (parsed_data is JSON)
SELECT device_name, parsed_data FROM netops.parsed_outputs
WHERE command LIKE '%bgp%' ORDER BY ingested_at DESC;

-- Network topology links
SELECT source_device, source_interface, destination_device, destination_interface
FROM netops.topology_links WHERE link_status = 'up';
```

> **Never** call `execute_sql` just to discover table names or column names.
> Use the schema above and write the query directly.

### Raw Fallback (重要)

`raw_output_store` contains raw CLI text for **every** collected command (覆盖更新，只保留最新):

| Column | Type | 说明 |
|---|---|---|
| device_name | VARCHAR | 设备名 |
| command | VARCHAR | CLI 命令 |
| raw_output | TEXT | 原始 CLI 文本 |
| updated_at | TIMESTAMP | 最后更新 |

**主键:** (device_name, command) — 覆盖更新。

**When parsed_outputs is empty for a device/command, fall back to raw:**
```sql
SELECT device_name, command, raw_output FROM netops.raw_output_store
WHERE command LIKE '%bgp%'
  AND device_name NOT IN (
    SELECT DISTINCT device_name FROM netops.parsed_outputs WHERE command LIKE '%bgp%'
  );
```

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
