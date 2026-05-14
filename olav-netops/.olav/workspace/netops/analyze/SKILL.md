---
name: ops-analyze
agent_type: api  # skip TodoListMiddleware (NETOPS sub-agents are tool-execution, not plan-and-iterate)
# R-VERTICAL-SLICE 2026-05-09: sub-agent uses no-think for
# fast tool execution; orchestrator handles planning.
thinking_mode: disabled
description: "READ-SIDE network analysis: BGP / OSPF investigation, snapshot drift detection, topology Q&A, blast-radius reachability, Mermaid diagram. Inspector @tools wrap NetworkX queries; LLM never writes graph code. Reads DB only; no live device access. Does NOT own change planning — for 'plan a change' / 'add eBGP X-Y' / '变更方案' the orchestrator delegates to `task('analyzer', ...)` instead."
metadata:
  version: 2.0.0
  replaces: [ops-analysis v1.1.0, ops-diff v1.0.0]
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - routing_analysis
    - topology_analysis
    - topology_visualization
    - state_comparison_drift_detection
    - blast_radius_analysis
tools:
  # Topology / state inspectors (shared with sim via netops/tools/)
  - inspect_devices         # facts: platform / AS / loopback / role
  - inspect_topology        # L2 adjacencies (LLDP/CDP), depth-N BFS
  - inspect_routing         # BGP / OSPF session state per device
  - inspect_blast_radius    # what-if: remove devices/links → components
  - inspect_path            # P2 2026-05-10: src→dst path + ECMP
  - inspect_critical_nodes  # P3 2026-05-10: articulation + betweenness
  - inspect_interfaces      # 2026-05-11: per-interface IP/status
  # Drift inspectors (NEW 2026-05-09 — wrap diff_* helpers as @tools)
  - inspect_drift_sql       # any table, t1 vs t2
  - inspect_drift_topology  # L2 link up/down/added/removed
  - inspect_drift_routing   # prefix / next-hop / AS-PATH delta
  - inspect_drift_configs   # raw config text diff per device
  # Output
  - format_and_export       # Markdown reports + Mermaid diagrams
allowed_tables:
  - netops.devices
  - netops.topology_links
  - netops.parsed_outputs
  - netops.v_show_ip_bgp_summary_auto
  - netops.v_show_ip_ospf_neighbor_auto
  - netops.v_show_ospf_neighbor_auto
  - netops.v_show_ip_route_auto
  - netops.v_l2_links_auto
  - netops.commands
  - schema_catalog
static_context_mode: on_intent
# Portability manifest — YAML knowledge files under ./references/
dynamic_context:
  - path: ./references/inspect_path.guide.yaml
  - path: ./references/topology_viz.guide.yaml
system: $ref:./prompts/system.md
---

## Analyze — read-side network analysis (inspector pattern)

R-AGENT-HIERARCHY 2026-05-09: dropped sandbox + `run_python_simulation`
in favour of typed inspector @tools.  Same rationale as sim: small
models can't reliably compose multi-line NetworkX Python; typed tool
calls with grammar-constrained args fit gemma4:31b nothink.

OLAV is committed to local small models (R100 milestone, dev_docs/200).
The sandbox path was a cloud-LLM-era affordance; analyze now mirrors
sim's inspector-driven approach.

## Available inspectors

| Tool | Returns |
|---|---|
| `inspect_devices(devices=[...])` | platform / AS / loopback / mgmt_ip / role per device |
| `inspect_topology(devices=[...], depth=1)` | L2 neighbors with interface + status, up to N hops |
| `inspect_routing(devices=[...], protocol="bgp"|"ospf"|"both")` | BGP/OSPF session state |
| `inspect_blast_radius(remove_devices=[...] OR remove_links=[[A,B]])` | Components + isolated nodes after the proposed failure |
| `inspect_drift_sql(table_name, snap1, snap2)` | Rows missing / new between snapshots |
| `inspect_drift_topology(snap1, snap2)` | Links removed / added / status changed |
| `inspect_drift_routing(snap1, snap2)` | Prefixes + next-hop + AS-PATH delta |
| `inspect_drift_configs(device, command, snap1, snap2)` | Raw command-output line diff |

## Workflow shapes

### Drift / change detection ("what changed between snapshots?")

1. Identify two snapshot_ids (user gives them, or via prompt context).
2. Call `inspect_drift_*` for the relevant dimension:
   - Devices/inventory drift → `inspect_drift_sql("devices", t1, t2)`
   - L2 topology drift → `inspect_drift_topology(t1, t2)`
   - Routing drift → `inspect_drift_routing(t1, t2)`
   - Per-device config drift → `inspect_drift_configs(device, cmd, t1, t2)`
3. Read the typed result.  Surface anomalies (rows missing, new
   prefixes, status flips).
4. Optionally call `inspect_blast_radius` if a topology change has
   downstream impact you want to quantify.
5. Write a Markdown drift report via `format_and_export`.

### Topology Q&A ("how is R1 connected? what's R3's BGP state?")

1. `inspect_devices([dev])` for facts.
2. `inspect_topology([dev])` for L2 neighbors.
3. `inspect_routing([dev])` for session state.
4. Reply directly to user — no `format_and_export` needed for
   simple Q&A (only for diagrams / drift reports).

### Blast-radius / what-if ("what if R3 fails?")

1. `inspect_blast_radius(remove_devices=["R3"])`
2. Reply with components + isolated nodes from the result.

### Mermaid topology diagram

1. `inspect_topology(<all devices>)` to get full L2 adjacency.
2. Compose Mermaid syntax from the result.
3. `format_and_export(data=mermaid_text, filename="topology",
                      format="mmd", subdir="diagrams")`.

## Hard rules

1. **No sandbox**.  You don't have `run_python_simulation`.  Don't
   try to import networkx — the inspectors already use it under
   the hood with typed args.
2. **Inspector first**.  Every graph or drift question goes through
   one of the 8 inspectors.  Don't query DuckDB directly for these
   patterns — the inspectors are faster and structured.
3. **Don't compose change plans**.  If the user asks for a change
   plan or "add eBGP" → redirect: that's ``analyzer``'s Workflow A.
4. **Drift reports go via `format_and_export`** to
   `exports/drift_reports/<id>.md` (or `exports/diagrams/` for
   Mermaid).

## Anti-patterns (do NOT do these)

* Writing 30 lines of `nx.DiGraph(); for src, dst, ...: G.add_edge(...)`
  — the inspectors already built the enriched graph.
* Querying ASN / loopback via SQL — call `inspect_devices`.
* Re-implementing diff_sql_state by hand — call `inspect_drift_sql`.
