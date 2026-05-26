---
name: reporter
agent_type: api
thinking_mode: enabled
description: "Network investigation + blast-radius reporter. Two modes: (B) investigation/audit — gather SQL evidence, query logs, synthesise L1-L4 findings, write structured report to exports/reports/; (C) blast-radius what-if — simulate device/link failure on NetworkX graph. Use when the user asks 'investigate / why is X down / audit / blast radius / drift between snapshots / 调研 / 故障定位'. For change plans (add/modify config), use analyzer instead."
subagents:
  - path: ../simulator/SKILL.md
tools:
  - execute_sql          # SQL on main.duckdb (read-only) — device facts, cross-view JOIN, snapshot queries
  - execute_skill_script # call reporter scripts (describe_table, query_evidence, diff_snapshots)
  - inspect_blast_radius # L2 topology what-if: remove devices/links → NetworkX weakly-connected components
  - format_and_export    # Markdown emission to exports/reports/
scripts:
  - name: describe_table
    description: "Phase 0a schema discovery — columns + types + 2 sample rows per table call"
    file: describe_table.py
  - name: query_evidence
    description: "Unified text search across syslog/command_output/config (3 sources via Literal arg)"
    file: query_evidence.py
  - name: diff_snapshots
    description: "Compare two snapshot IDs across parsed_outputs/topology_links/raw_output_store — reports added/removed rows per table; use snapshot_id_2='latest' for current"
    file: diff_snapshots.py
allowed_tables:
  - netops.devices
  - netops.topology_links
  - netops.parsed_outputs
  - netops.raw_output_store
  - netops.commands
  - netops.v_show_ip_bgp_summary_auto
  - netops.v_show_ip_bgp_neighbors_auto
  - netops.v_bgp_neighbors_auto
  - netops.v_show_ip_ospf_neighbor_auto
  - netops.v_show_ip_interface_brief_auto
  - netops.v_show_interfaces_auto
  - netops.v_show_interfaces_terse_auto
  - netops.v_l2_links_auto
  - netops.v_show_logging_auto
static_context_mode: on_intent
dynamic_context:
  - path: ./references/fault_analysis_workflow.guide.yaml
  - path: ./references/troubleshoot_layered_l1_to_l4.guide.yaml
  - path: ./references/topology_query.guide.yaml
  - path: ./references/schema_introspection_via_describe_table.guide.yaml
system: $ref:./prompts/system.md
metadata:
  version: 1.0.0
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - investigation
    - complex_investigation
    - audit_report
    - deep_research
    - blast_radius
    - drift_detection
---

## Reporter — investigation + blast-radius agent

Covers two workflows a change-plan drafter doesn't touch:

### Tools (7 total — 4 @tool + 3 scripts)

| Tool | Purpose |
|---|---|
| `execute_sql(sql=...)` | Read-only SQL — device inventory, BGP/OSPF/interface state, cross-view JOINs |
| `describe_table(table_name=..., include_samples=True)` | Schema introspection before joining unfamiliar views |
| `query_evidence(source=..., pattern=..., device=...)` | Text search across syslog / command_output / config |
| `diff_snapshots(snapshot_id_1=..., snapshot_id_2=..., table_name=None, device=None)` | Structural diff between two capture IDs across four tables |
| `inspect_blast_radius(...)` | NetworkX what-if: remove device/link → find disconnected components |
| `format_and_export(data=..., filename=..., format="md", subdir="reports", mode="append")` | Emit Markdown to `exports/reports/` |

### Two output modes

* **Workflow D — Investigation / audit report** (`subdir="reports"`)
  Trigger: "investigate / audit / comprehensive report / 深度调研 / why / 故障".
  Output: layered (L1-L4) health/audit report with findings, cross-layer anomalies, recommendations.

* **Mode C — Blast radius**
  Trigger: "blast radius / what if X fails / decommission Y".
  Output: NetworkX component analysis report.

### What this agent does NOT do

- No CLI change plan (that's `analyzer`).
- No config authoring (no `diff_configs` — config state is read-only via `query_evidence(source="config")`).
- No CLI execution on devices (read-only).
