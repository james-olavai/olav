---
name: analyzer
thinking_mode: enabled
subagents:
  - path: ../simulator/SKILL.md
description: "Change-plan drafter — gather device facts via SQL, write a vendor-specific change plan markdown (CLI per device + rollback + post-checks + risks) to exports/change_plans/. Use when the user asks 'plan / add / change / modify / 变更 / new eBGP between X and Y'. For investigation/audit reports or blast-radius what-if, use reporter instead."
tools:
  - execute_sql          # SQL on main.duckdb (read-only) — device facts, topology, interface state
  - execute_skill_script # call analyzer scripts (describe_table, inspect_devices, inspect_interfaces)
  - diff_configs         # raw CLI config diff between two snapshots (difflib — not SQL)
  - format_and_export    # Markdown emission to exports/change_plans/
scripts:
  - name: describe_table
    description: "Phase 0a schema discovery — columns + types + 2 sample rows per table call"
    file: describe_table.py
  - name: inspect_devices
    description: "Device facts: platform/loopback/AS/mgmt_ip/role; pass devices=[] for discovery mode"
    file: inspect_devices.py
  - name: inspect_interfaces
    description: "Per-interface IP/status/proto from latest snapshot; Cisco IOS + Junos terse views"
    file: inspect_interfaces.py
# Structured change-record (TCF) emission is enterprise-only (olav-ent lab).
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
static_context_mode: on_intent
dynamic_context:
  - path: ./references/topology_query.guide.yaml
  - path: ./references/change_plan_cli_authoring.guide.yaml
  - path: ./references/plan_act_reflect_workflow.guide.yaml
  - path: ./references/schema_introspection_via_describe_table.guide.yaml
system: $ref:./prompts/system.md
metadata:
  version: 6.0.0
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - change_request
    - change_planning
---

## Analyzer — change plan drafter

Mode A only: gather device facts, write a vendor-specific change plan markdown.

### Tools (7 total — 4 @tool + 3 scripts)

| Tool | Purpose |
|---|---|
| `execute_sql(sql=..., explain_only=False)` | Read-only SQL — device inventory, topology, interface/routing state. Returns `list[dict]`. |
| `describe_table(table_name=..., include_samples=True)` | Phase 0a schema introspection: columns + types + 2 sample rows. |
| `inspect_devices(devices=[...])` | Device facts: platform, loopback, AS, mgmt_ip, role. Pass `devices=[]` for full inventory. |
| `inspect_interfaces(device=..., snapshot_id=None)` | Per-interface IP/status from latest snapshot. |
| `diff_configs(device=..., snap_a=..., snap_b=...)` | Raw CLI config diff (difflib unified diff) between two snapshots. |
| `format_and_export(data=<MD>, filename=..., format="md", subdir="change_plans")` | Emit the change plan Markdown. |

### Output mode

* **Workflow A — Change plan markdown** (`subdir="change_plans"`)
  Trigger: "plan / add / change / modify / 变更 / new ... between X and Y".
  Output: complete change plan including CLI per device, rollback, post-checks, risks.

### What this agent does NOT do

- No investigation or audit reports (use `reporter`).
- No blast-radius what-if (use `reporter`).
- No CLI execution on devices (read-only).
- No structured-spec output (TCF / Pydantic schemas) — enterprise-only (olav-ent).
