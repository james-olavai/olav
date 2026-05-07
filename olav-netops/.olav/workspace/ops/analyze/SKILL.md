---
name: ops-analyze
description: "Routing analysis + deterministic simulation + topology viz + snapshot drift. Reads DB only; no live device access."
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
  - run_python_simulation  # pure-compute sandbox (R102.UNIFIED_SANDBOX
                           # 2026-05-05): What-If sim + drift diff
                           # share one sandbox.  diff_sql_state /
                           # diff_topology_drift / diff_routing_drift /
                           # diff_configs are pre-imported globals
                           # inside the sandbox prologue.
  - emit_tcf               # CAB TCF emission @tool (Patch D 2026-05-06).
                           # Writes exports/cab/<change_id>/spec.tcf.yaml.
                           # Sandbox-external write target per ADR-0008
                           # condition #2 — NOT in the sandbox prologue.
                           # Refuses to overwrite a spec with accumulated
                           # state (Patch O'-B guard) — use execute_skill_script
                           # tcf_patch_block.py for revisions.
  - execute_skill_script   # for tcf_patch_block.py (Patch O'-B 2026-05-07):
                           # surgical add/remove on one CliBlock when
                           # operator asks for targeted revision after
                           # lab findings.  See guides/cab_revise.guide.yaml.
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

## TCF emission (CAB workflow) — direct @tool, NOT sandbox

Change plans MUST be emitted as a TCF via the **`emit_tcf` @tool**
(see SKILL.md `tools:` list).  This is a top-level tool, not a
sandbox global — TCF writes a YAML spec to disk
(`exports/cab/<change_id>/spec.tcf.yaml`), so per ADR-0008 condition
#2 (sandbox-external write target) it lives at the @tool layer.

Call shape (Pydantic schema validates each field on the tool side):

```python
emit_tcf(
    change_id="r1-r3-ebgp",
    title="Add eBGP direct between R1 and R3",
    intent_type="ebgp_direct",
    device_names=["R1", "R3"],
    device_platforms=["juniper_junos", "cisco_ios"],
    device_loopbacks=["10.0.0.1", "10.0.0.3"],
    device_asns=[65001, 65003],
    implementation_json='[{"device":"R1","phase":1,"cli":["set protocols bgp group EBGP-R3 type external","set protocols bgp group EBGP-R3 peer-as 65003"]},{"device":"R3","phase":1,"cli":["router bgp 65003"," neighbor 10.1.13.1 remote-as 65001"]}]',
    rollback_json='[{"device":"R1","phase":1,"cli":["delete protocols bgp group EBGP-R3"]}]',
    output_dir="exports/cab",
)
```

Returns: `{"status": "success", "spec_path": "exports/cab/<change_id>/spec.tcf.yaml", ...}`
on success; `{"status": "error", "error": "<reason>"}` on validation
failure (no file written).  Lab agent consumes that path.

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
