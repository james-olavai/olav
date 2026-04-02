---
name: quick-query
description: "Unified network operations skill — SQL queries, CLI execution, KB search, data export, topology analysis, and fault investigation."
tools:
  - execute_sql              # execute_sql.py    — DuckDB query + explain_only schema discovery
  - search_commands          # search_commands.py — Query commands table by device/platform + keyword
  - execute_cli              # execute_cli.py    — Nornir CLI; validates blacklist + pipe_allowed
  - diff_configs             # diff_configs.py   — Compare raw snapshots between dates to detect drift
  - format_and_export        # format_and_export.py — Export to CSV/JSON/Markdown
  - take_snapshot            # take_snapshot.py  — Trigger snapshot collection on devices
  - search_knowledge_lancedb # search_knowledge_lancedb.py — Semantic KB search (LanceDB)
  - web_search               # web_search.py    — Web search via DuckDuckGo for external info
  - path: ../ops/tools/_generated/netbox_dcim.py          # NetBox DCIM — sites, racks, devices, interfaces
  - path: ../ops/tools/_generated/netbox_ipam.py          # NetBox IPAM — prefixes, IPs, VLANs, VRFs
  - path: ../ops/tools/_generated/netbox_virtualization.py # NetBox VM — clusters, VMs, VM interfaces
  - path: ../ops/tools/_generated/netbox_tenancy.py        # NetBox tenancy — tenants, contacts
static_context:
  - path: ./references/SCHEMA_REFERENCE.md
metadata:
  version: 1.3.0
  author: Network AI Team
  type: agent
  category: network-operations
  intent: query_and_operations
  database_schema:
    devices:
      description: Device inventory from Nornir hosts.yaml
      key_columns: [device_id, name, hostname, platform, device_role, site, mgmt_ip, is_active]
    commands:
      description: "Registered CLI commands per platform — source of truth for what can be executed"
      key_columns: [command_name, platform, category, has_template, allowed, blacklisted, pipe_allowed]
      note: Use search_commands tool (not raw SQL) to query this table
    parsed_outputs:
      description: "Raw parsed CLI/NETCONF output (stored as-is per S1 SSOT rule). Field names are vendor-specific — use schema_catalog.fields[].openconfig_path to find OC mapping."
      key_columns: [id, device_name, command, parsed_data, snapshot_id, created_at]
      note: "Column is parsed_data (NOT parsed_json). DO NOT assume OpenConfig paths — check schema_catalog for mapping."
    schema_catalog:
      description: "S3 SSOT: OpenConfig mapping authority. Each row = one CLI command, fields[].openconfig_path = validated OC path. Pipeline Stage 5 writes here."
      key_columns: [platform, source_name, source_type, fields]
      note: "fields is a JSON array of {name, openconfig_path, mapping_confidence, mapping_source}. Read openconfig_path to find OC mapping for a field."
    mapping_cache:
      description: "Stage 2 lookup cache: fast (platform, src_field) → oc_path mapping. Seeded from mapping_rules, updated by pipeline Stage 5."
      key_columns: [platform, src_field, oc_path, confidence, stage, hit_count, validated]
      note: "Use for Stage 2 deterministic lookup. Cross-platform normalization available via semantic_type matching."
    mapping_candidates:
      description: "Medium-confidence (0.55-0.70) LLM mapping decisions. Staging table for Audit Agent review before promotion to schema_catalog."
      key_columns: [platform, src_field, oc_path, confidence, stage, needs_review]
      note: "Audit Agent reviews and promotes valid candidates to schema_catalog."
    mapping_rules:
      description: "Legacy vendor CLI field → OpenConfig path mappings. Now serves as seed data source for mapping_cache."
      key_columns: [vendor, command, src_field, oc_path, confidence]
      note: "Compatibility shim — prefer schema_catalog or mapping_cache for queries."
    yang_leaves:
      description: "OpenConfig YANG leaf registry (806 rows, 31 modules). Ground truth for OC paths, types, and descriptions. Used by pipeline Stage 3 embedding and Stage 4 LLM."
      key_columns: [yang_path, leaf_name, leaf_type, description, module]
      note: "Modules: openconfig-interfaces, bgp, ospfv2, system, platform, lldp, network-instance, vlan, acl, qos, spanning-tree, isis, mpls, lacp, probes, segment-routing, macsec, optical-amplifier, terminal-device, etc."
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
4. **Log Mode** — Fast metrics/semantic search on network logs (v0.10.x+)

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

### When to Use execute_cli
- **execute_cli** — single device, single command, output inline in response
- For fresh multi-device data collection, delegate to `config` agent (take_snapshot)

### When to Use Log Tools in Quick Mode
- **log_metrics_query** — "How many ERRORs on R1 since 3AM?" (DuckDB SQL)
- **semantic_log_search** — "Find similar authentication failures from last week" (LanceDB Vector)

### When to Escalate to Expert
- Root cause analysis required
- Cross-device correlation or topology reasoning
- "Why" / "diagnose" / "recommend" requests
- Deep log investigation over multiple incidents
