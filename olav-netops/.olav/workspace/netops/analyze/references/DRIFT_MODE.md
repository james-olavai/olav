# Drift Mode

Load when the user's request uses comparison verbs — `compare`,
`diff`, `drift`, `what changed`, `before/after`, `T1 vs T2`, `漂移`,
`变更检测`.

Per R102.UNIFIED_SANDBOX (2026-05-05), Drift runs through the same
`run_python_simulation` sandbox as Analysis. The four diff
primitives are pre-imported globals — call them like regular Python
functions inside an experiment_code block.

## Expertise

* **State comparison** — compare any DB table between two snapshots
* **Topology drift** — detect physical links that went up/down
* **Routing drift** — next-hop path shifts, lost prefixes, BGP
  AS_PATH changes
* **Config diff** — compare raw CLI configuration files between
  snapshots

## Pre-loaded sandbox functions

| Function | Args | Returns |
|---|---|---|
| `diff_sql_state(table_name, snapshot_id_1, snapshot_id_2, row_limit=50)` | table + two snapshot ids | `{status, missing_in_t2, new_in_t2, ...}` |
| `diff_topology_drift(snapshot_id_1, snapshot_id_2)` | two snapshot ids | link state delta |
| `diff_routing_drift(snapshot_id_1, snapshot_id_2, device_name=None)` | two snapshot ids + optional device scope | next-hop / prefix / AS_PATH delta |
| `diff_configs(device, command, snapshot_id_1, snapshot_id_2)` | per-device per-command config text | text diff |

## Common patterns

```python
# Compare a table between two snapshots
run_python_simulation(experiment_code='''
result = diff_sql_state(
    table_name="ospf_neighbors",
    snapshot_id_1="20260226_100000",
    snapshot_id_2="20260226_120000",
)
_result = result
''')

# Detect topology link state changes
run_python_simulation(experiment_code='''
_result = diff_topology_drift(
    snapshot_id_1="20260226_100000",
    snapshot_id_2="20260226_120000",
)
''')

# Detect routing changes scoped to one device
run_python_simulation(experiment_code='''
_result = diff_routing_drift(
    snapshot_id_1="20260226_100000",
    snapshot_id_2="20260226_120000",
    device_name="R1",
)
''')

# Compare raw config files
run_python_simulation(experiment_code='''
_result = diff_configs(
    device="R1",
    command="show running-config",
    snapshot_id_1="latest",
    snapshot_id_2="latest",
)
''')
```

## Composite drift + sim in one call

Because everything runs in the same sandbox, follow-up "what-if it
had been fixed?" / "blast radius?" questions chain naturally:

```python
run_python_simulation(experiment_code='''
# 1. Detect drift
drift = diff_topology_drift(
    snapshot_id_1="20260226_100000",
    snapshot_id_2="20260226_120000",
)
down_links = drift.get("missing_in_t2", [])

# 2. Sim impact: clone and apply the down-state
sim.clone(["topology_links"])
for link in down_links:
    _sql = "UPDATE sim_topology_links SET link_status='down' WHERE source_device=? AND destination_device=?"
    sim.execute(_sql, [link["source_device"], link["destination_device"]])

# 3. Compute reachability blast radius
active = sim.execute("SELECT source_device, destination_device FROM sim_topology_links WHERE link_status='active'").fetchall()
g = nx.DiGraph(); g.add_edges_from(active)
components = list(nx.weakly_connected_components(g))

_result = {"drift_summary": drift, "blast_components": [list(c) for c in components]}
''')
```

## Response format

Always include:

1. **Summary** — brief description of what changed
2. **Details** — key changes in a Markdown table
3. **Impact** — what this means for network operations

## Rules

* Always specify both `snapshot_id_1` (baseline) and `snapshot_id_2`
  (target).
* Use `"latest"` to auto-resolve to the most recent snapshot.
* Limit output to the **20 most significant changes** to prevent
  context overflow.
* For large diffs, focus on the highest-impact changes.
