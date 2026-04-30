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
  - run_python_simulation  # ad-hoc networkx/netutils what-if (Analysis Mode);
                           # diff_* + tcf_emit_from_sim are skill scripts via
                           # execute_skill_script, NOT this tool (ADR-0008 R92.3)
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

## Two modes (dispatched by request verbs)

* **Analysis** — proactive (simulate / what-if / change plan / 变更方案 /
  topology / path / loop).  Tool: `run_python_simulation` (sandbox
  with `db` read-only proxy, `sim` writable clone, `nx` networkx,
  `netutils`; `network_isolation=True`).
* **Drift** — retrospective (drift / compare / what changed / delta /
  snapshot T1 vs T2 / 漂移).  Tool: `execute_skill_script(skill_name="analyze", ...)`.

A single request can invoke both sequentially.

### Drift skill scripts (skill_name="analyze")

| Script | Use for |
|---|---|
| `diff_sql_state.py` | any operational table (ospf_neighbors, interfaces, …) |
| `diff_topology_drift.py` | `topology_links` up/down changes |
| `diff_routing_drift.py` | prefix loss / next-hop / AS-PATH delta |
| `diff_configs.py` | raw config file comparison |

`tcf_emit_from_sim.py` (Analysis Mode helper) — emits TCF JSON from
a sim result for the CAB workflow.

Call shape:

```python
execute_skill_script(
    skill_name="analyze",
    script_name="diff_sql_state.py",
    script_args={"table_name": "ospf_neighbors",
                 "snapshot_id_1": "t1", "snapshot_id_2": "t2"},
)
```

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

## Drift workflow

1. Pick two `snapshot_id` values (T1 before, T2 after)
2. Invoke `execute_skill_script(skill_name="analyze", script_name=...)` —
   pick by dimension (table above)
3. Inspect `stdout.missing_in_t2` / `stdout.new_in_t2`
4. Report findings with root-cause analysis
