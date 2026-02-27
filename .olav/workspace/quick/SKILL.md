---
name: quick-Query
description: "Unified network operations skill — SQL queries, CLI execution, KB search, data export, topology analysis, and fault investigation."
metadata:
  version: 1.1.0
  author: Network AI Team
  type: agent
  category: network-operations
  intent: query_and_operations
  tools:
    - execute_sql              # execute_sql.py    — DuckDB query + explain_only schema discovery
    - search_commands          # search_commands.py — Query commands table by device/platform + keyword
    - execute_cli              # execute_cli.py    — Nornir CLI; validates blacklist + pipe_allowed
    - take_snapshot            # take_snapshot.py  — On-demand targeted snapshot for fault investigation
    - diff_configs             # diff_configs.py   — Compare raw snapshots between dates to detect drift
    - format_and_export        # format_and_export.py — Export to CSV/JSON/Markdown
    - search_knowledge         # search_knowledge.py  — Semantic KB search (db_path, limit, threshold)
    - web_search               # web_search.py    — Web search via DuckDuckGo for external info
  database_schema:
    devices:
      description: Device inventory from Nornir hosts.yaml
      key_columns: [device_id, name, hostname, platform, device_role, site, mgmt_ip, is_active]
    commands:
      description: "Registered CLI commands per platform — source of truth for what can be executed"
      key_columns: [command_name, platform, category, has_template, allowed, blacklisted, pipe_allowed]
      note: Use search_commands tool (not raw SQL) to query this table
    parsed_outputs:
      description: TextFSM-parsed CLI outputs as JSON array
      key_columns: [id, device_name, command, parsed_data, snapshot_id, created_at]
      note: "column is parsed_data (NOT parsed_json)"
    topology_links:
      description: "Unified relationship map (L2 physical links from CDP/LLDP + L3 logical links from BGP/OSPF)"
      key_columns: [link_id, source_device, source_interface, destination_device, destination_interface, discovery_protocol, link_type, link_status]
    v_routes_enriched:
      description: "Enriched routing table with resolved next-hop device names"
    v_bgp_neighbors_enriched:
      description: "Enriched BGP neighbors with resolved peer device names"
    interfaces:
      description: "IPAM mapping table (IP to device/interface)"
    bgp_routes:
      description: "BGP RIB table with AS-PATH, Communities, Local-Pref, etc."
    routes:
      description: IP routing table entries
      key_columns: [device_name, network, mask, next_hop, interface, protocol, metric, snapshot_id]
    bgp_neighbors:
      description: BGP neighbor status
      key_columns: [device_name, neighbor_ip, neighbor_as, state, prefixes_received, snapshot_id]
    ospf_neighbors:
      description: OSPF neighbor status
      key_columns: [device_name, neighbor_id, neighbor_ip, interface, state, priority, snapshot_id]
    knowledge_chunks:
      description: KB document chunks with embeddings (use search_knowledge tool, not raw SQL)
      key_columns: [id, content, source_file]
    indexed_files:
      description: Indexed KB file registry
      key_columns: [file_path, file_name, chunk_count, indexed_at, status]
    system: $ref:./prompts/system.md
  escalation:
    to_expert:
      trigger: "User asks 'why', 'diagnose', 'root cause', 'recommend fix'"
      marker: <escalate_to_expert>reason</escalate_to_expert>
    cli_needed:
      trigger: Schema has no table for requested operational data
      marker: <cli_needed>reason</cli_needed>
  analysis_workflow:
    step_1: Scope Definition - Identify devices, protocols, or systems to analyze
    step_2: Baseline Query - Get historical baseline metrics via execute_sql
    step_3: "Current State - Compare with real-time data via execute_cli if needed"
    step_4: Anomaly Detection - Identify deviations from thresholds
    step_5: Verification - Confirm findings with CLI commands
    step_6: Recommendations - Suggest adjustments or improvements
---

## Overview

Unified network operations agent handling three modes:
1. **Query Mode** — SQL queries on DuckDB (device inventory, parsed outputs, topology)
2. **CLI Mode** — Execute show/config commands on devices via Nornir
3. **Analysis Mode** — Health diagnostics, anomaly detection, performance analysis

## Strategy

### Topology-Aware Troubleshooting
Always query `v_routes_enriched` and `v_bgp_neighbors_enriched` instead of raw tables when analyzing paths or adjacencies. These views resolve IPs to device names, preventing the need for manual translation. Use `topology_links` for the overall relationship map.

### Device Inventory Queries
Use `execute_sql` on the `devices` table:
```sql
SELECT name, hostname, platform, device_role, site FROM devices
SELECT name, hostname FROM devices WHERE device_role = 'core'
SELECT name, hostname FROM devices WHERE site = 'lab'
```

### When to Use CLI
- Operational data not in DB (BGP routes, OSPF neighbors, interface counters)
- Real-time device state verification
- Single-device ad-hoc command

### CLI Execution Workflow — Always 3 steps
Never call execute_cli directly without first discovering the right command:
1. **search_commands(device="R1", keyword="ospf")** → find commands for this device's platform; note `pipe_allowed` field
2. **Pick the command** from results (e.g. "show ip ospf neighbor" or "display ospf peer")
3. **execute_cli(device="R1", command="...")** → blocked if blacklisted or pipe used when `pipe_allowed=false`

### When to Use take_snapshot vs execute_cli
- **execute_cli** — single device, single command, output inline in response
- **take_snapshot** — multiple devices × multiple commands in parallel; writes to `parsed_outputs` DB so results can be queried with `execute_sql`; use for fault investigation requiring fresh data from several devices simultaneously

### When to Escalate to Expert
- Root cause analysis required
- Cross-device correlation or topology reasoning
- "Why" / "diagnose" / "recommend" requests
