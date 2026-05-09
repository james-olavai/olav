---
name: ops-analyze
description: "READ-SIDE network analysis ONLY: BGP / OSPF investigation, snapshot drift detection, topology Q&A, Mermaid diagram rendering, blast-radius reachability. Reads DB only; no live device access. Does NOT own change planning — for 'plan a change' / 'add eBGP X-Y' / 'emit TCF' / 'CAB' / '变更方案' the orchestrator MUST delegate to `task('sim', ...)` instead (R-AGENT-HIERARCHY Phase B+C+D 2026-05-09)."
metadata:
  version: 1.0.0
  replaces: [ops-analysis v1.1.0, ops-diff v1.0.0]
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - routing_analysis
    - change_simulation
    - topology_analysis
    - topology_visualization
    - state_comparison_drift_detection
tools:
  - run_python_simulation  # pure-compute sandbox (R102.UNIFIED_SANDBOX):
                           # What-If sim + drift diff share one sandbox.
                           # diff_sql_state / diff_topology_drift /
                           # diff_routing_drift / diff_configs are
                           # pre-imported globals inside the prologue.
  - format_and_export      # diagram saves (Mermaid topology) + drift
                           # report inline writes per Patch D' Step 5.
                           # Change-plan path lives in `sim` sub-agent
                           # (R-AGENT-HIERARCHY 2026-05-09) — analyze
                           # is read-side only.
allowed_tables:
  - netops.v_bgp_neighbors_auto
  - netops.v_ospf_neighbors_auto
  - netops.v_l2_links_auto
  - netops.topology_links
  - netops.devices
  - netops.parsed_outputs
  - netops.oc_outputs
  - netops.raw_output_store
  - netops.commands
  - schema_catalog
  - view_recipes
# ROUTING_EXPERT_GUIDE used to be on_intent here (~3.2K chars).
# Removed from auto-load — agent calls `get_static_context` /
# `read_file('references/ROUTING_EXPERT_GUIDE.md')` when actually
# investigating BGP attributes.  See dev_docs/00 § ISSUE-CTX-PROMPT-INFLATION.
# static_context: []
static_context_mode: on_intent
system: $ref:./prompts/system.md
---

## Single dispatch — everything runs in `run_python_simulation`

Analysis (what-if / sim / topology) and Drift (T1 vs T2 / 漂移) and
CAB TCF emission all share the same sandbox.  Write Python that
imports/uses the pre-loaded primitives — no mode selection, no
skill-script dispatch, no two-level naming:

```python
run_python_simulation(experiment_code='''
# Drift: compare snapshots
drift = diff_sql_state("ospf_neighbors", "t1", "t2")

# Analysis: simulate impact of newly-down devices
affected = [r["device_name"] for r in drift["missing_in_t2"]]
sim.clone(["topology_links"])
for d in affected:
    sim.execute("UPDATE sim_topology_links SET link_status='down' WHERE source_device=?", [d])

# Graph reachability
links = sim.execute("SELECT source_device, destination_device FROM sim_topology_links WHERE link_status='active'").fetchall()
g = nx.DiGraph(); g.add_edges_from(links)
blast = list(nx.weakly_connected_components(g))

_result = {"affected": affected, "blast_components": blast}
''')
```

Pre-loaded sandbox globals (no `import` needed):

| Global | Use |
|---|---|
| `db` | read-only prod DB proxy — `db.query(sql)` |
| `sim` | writable in-memory DuckDB clone — `sim.clone([...])` / `sim.execute(...)` |
| `nx` | networkx — graphs, paths, components |
| `netutils` | IP / interface / ASN normalization |
| `diff_sql_state(table, t1, t2)` | drift any operational table |
| `diff_topology_drift(t1, t2)` | topology_links up/down changes |
| `diff_routing_drift(t1, t2)` | prefix / next-hop / AS-PATH delta |
| `diff_configs(device, t1, t2)` | raw config text diff |
Composite analyses run in **one** sandbox call instead of N tool turns.

## Sandbox SQL rule

`sim.execute()` with literal SQL starting with `CREATE` / `INSERT` etc.
MUST use a variable (sandbox_guard pattern):

```python
_sql = "CREATE TABLE sim_x (col VARCHAR)"
sim.execute(_sql)  # NOT: sim.execute("CREATE TABLE ...")
```

## Design feasibility — query, don't assume

| Required info | DB source | BLOCKER? |
|---|---|---|
| Peer AS | `netops.v_bgp_neighbors_auto.neighbor_as` | Yes — can't design session type |
| BGP link IP | JSON from `parsed_outputs WHERE command LIKE 'show%ip interface%'`; fallback `v_l2_links_auto` | Yes — Phase 0 IP assign |
| Direct physical link | `v_l2_links_auto WHERE src=X AND dst=Y` | Warning |
| IGP between peers | `v_ospf_neighbors_auto` | Blocker for iBGP |
| Route to loopback | JSON from `parsed_outputs WHERE command='show ip route'` | Blocker for multihop eBGP |

If ANY blocker is found → state explicitly as Phase 0 prerequisite.
NEVER assume / invent values.

## Drift workflow (now one call)

1. Pick two `snapshot_id` values (T1 before, T2 after)
2. Inside `run_python_simulation`, call the right diff primitive
   (`diff_sql_state` / `diff_topology_drift` / `diff_routing_drift`
   / `diff_configs`) — pick by dimension
3. Read `result["missing_in_t2"]` / `result["new_in_t2"]` directly
   from the dict you assigned to `_result`
4. Report findings with root-cause analysis
