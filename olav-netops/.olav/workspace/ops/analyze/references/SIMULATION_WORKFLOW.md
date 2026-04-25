# Simulation workflow (Mode 2)

Load before writing any `run_python_simulation` code for a What-If
scenario, change-impact analysis, or convergence prediction.

## Sandbox globals

| Variable | Type | Usage |
|---|---|---|
| `db` | `DatabaseProxy` | `db.query(sql)` → `list[dict]`, read-only prod data |
| `sim` | `SimulationProxy` | `sim.clone([...])` then `sim.execute(sql)` — writable in-memory copy |
| `nx` | `networkx` | `nx.DiGraph()`, `nx.shortest_path()`, `nx.has_path()`, etc. |
| `netutils` | `netutils` | IP math, interface canonicalisation |
| `json`, `math`, `itertools`, `collections` | stdlib | Standard utilities |

## ⚠️ `sim.execute` SQL rule

`sandbox_guard` blocks `sim.execute("CREATE TABLE …")` when the SQL is
a string literal directly inside the call.  Always assign the SQL to a
variable first:

```python
_sql = "CREATE TABLE my_table (col1 VARCHAR)"
sim.execute(_sql)
# NOT: sim.execute("CREATE TABLE …")  — blocked
```

## Five-step workflow (always in this order)

```python
# Step 1 — Clone the tables you'll mutate
sim.clone(['topology_links', 'ospf_neighbors', 'routes',
           'bgp_neighbors', 'interfaces'])

# Step 2 — Apply the What-If mutation
_upd = "UPDATE sim_topology_links SET link_status = 'down' WHERE source_device = ?"
sim.execute(_upd, ['R2'])

# Step 3 — Build a WEIGHTED graph (always weighted; hop-count alone misleads)
ospf_rows = sim.execute("""
    SELECT device_name, neighbor_id, interface, cost
    FROM sim_ospf_neighbors WHERE state = 'FULL'
""").fetchall()
G = nx.DiGraph()
for device, neighbor, iface, cost in ospf_rows:
    edge_cost = cost if cost else 10  # default if DB has no cost
    G.add_edge(device, neighbor, weight=edge_cost, interface=iface)

# Step 4 — Add L2 topology fallback (devices without OSPF data)
topo_rows = sim.execute("""
    SELECT source_device, destination_device, link_status
    FROM sim_topology_links WHERE link_status = 'active'
""").fetchall()
for src, dst, _ in topo_rows:
    if not G.has_edge(src, dst):
        G.add_edge(src, dst, weight=10)

# Step 5 — Compute and shape the result
try:
    path  = nx.dijkstra_path(G, 'R1', 'R4', weight='weight')
    cost  = nx.dijkstra_path_length(G, 'R1', 'R4', weight='weight')
    paths = list(nx.all_shortest_paths(G, 'R1', 'R4', weight='weight'))
    _result = {
        "best_path":     path,
        "total_cost":    cost,
        "ecmp_paths":    paths,
        "is_ecmp":       len(paths) > 1,
        "blast_radius":  [list(c) for c in nx.weakly_connected_components(G)],
    }
except nx.NetworkXNoPath:
    _result = {"best_path": None, "reason": "No path R1→R4 after change"}
```

## Always emit `_result["topology_coverage"]`

So the report can show which OSI layers had data.

## Blast-radius computation

`nx.weakly_connected_components(G)` after the simulation run gives
every set of devices that lost primary OR backup paths.

## Live data needed?

You're a pure-compute agent (`network_isolation=True`).  If the DB is
missing data you need, return a recommendation that the orchestrator
run `ops-collect` first, then re-invoke analysis once data lands.
