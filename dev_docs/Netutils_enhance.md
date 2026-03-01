# Netutils Integration & Advanced Sandbox Simulation Architecture

This document describes the architectural enhancements for OLAV to achieve true Zero-Hallucination network analysis. It integrates `netutils` for data normalization and introduces a "Code as a Service" sandbox combining routing and simulation capabilities.

## 1. Automated Data Cleaning (Value Normalization)

While the existing `SchemaMapper` handles syntactical key alignment (e.g., `local_interface` -> `local_port`), `netutils` provides the much-needed value normalization to ensure high-success JOINs across distinct vendor outputs in DuckDB.

### ValueNormalizer Design
A new pipeline stage, `ValueNormalizer`, will be introduced in `src/olav/core/value_normalizer.py`. It operates immediately after `SchemaMapper` but before inserting data into DuckDB.

```python
from netutils.interface import canonical_interface_name
from netutils.mac import mac_to_format

class ValueNormalizer:
    def normalize(self, unified_data: dict) -> dict:
        cleaned_data = unified_data.copy()
        
        # 1. Interface Name Normalization (e.g., Gi0/1 -> GigabitEthernet0/1)
        for key in ["local_port", "neighbor_port", "interface"]:
            if key in cleaned_data and cleaned_data[key]:
                cleaned_data[key] = canonical_interface_name(cleaned_data[key])

        # 2. MAC Address Normalization (e.g., xxxx.xxxx.xxxx -> xx:xx:xx:xx:xx:xx)
        if "mac_addr" in cleaned_data and cleaned_data["mac_addr"]:
            cleaned_data["mac_addr"] = mac_to_format(cleaned_data["mac_addr"], "MAC_COLON")
            
        return cleaned_data
```

**Workflow Integration:**
`Raw Data -> LLM/TextFSM -> SchemaMapper (Keys) -> ValueNormalizer (Values) -> DuckDB`

**Benefits:**
- **Flawless DuckDB JOINs:** Eliminates empty result sets caused by vendor mismatches (`Gi0/1` vs `GigabitEthernet0/1`).
- **Semantic Clarity:** Provides standard constraints for robust `Tier 2 Analysis Agent` operations.

---

## 2. Advanced Sandbox: Merging `ops-routing` and `ops-simulation`

To eliminate LLM hallucinations during network inference, we transition from NLP-based guessing to **Math & Graph-based deterministic computation**. This is achieved by combining the Routing and Simulation subagents into a unified `ops-routing-simulator` operating in a highly-capable Python Sandbox.

### Concept: "Code as a Service" for Network Digital Twins
Instead of the LLM trying to guess Spanning Tree or OSPF convergence, the LLM writes Python code using `networkx` and `netutils` to calculate exact shortest paths, overlap, and reachability.

### Architecture Enhancements

#### A. Sandbox Physics Engine (`src/olav/core/simulation/llm_sandbox.py`)
Inject mathematical and graph logic engines into the child process execution environment.

```python
def _prepare_environment(self) -> Dict[str, Any]:
    return {
        "db": self.db,
        "json": __import__("json"),
        "netutils": __import__("netutils"),   # Strict IP math & overlaps
        "networkx": __import__("networkx"),   # Graph calculation engine
        "_result": None,
    }
```

#### B. Writable In-Memory Sandbox Database with Schema Auto-Discovery

To allow "What-If" scenarios without corrupting production data, the sandbox exposes two primitives to the LLM:

1. **`db.query(sql)`** — read-only access to production data (already implemented)
2. **`sim.clone(tables)`** — on-demand clone of selected tables into a writable in-memory DuckDB

**Critical design principle**: the platform does **not** decide which tables to clone. The LLM discovers the schema at runtime by querying the live `schema_catalog` table, then calls `sim.clone()` with exactly the tables it needs for the current simulation layer.

```python
# In llm_sandbox.py — injected into the generated subprocess script
# (alongside db_query_code). Objects cannot be serialized across the process
# boundary, so SimulationProxy is reconstructed textually inside the child process.

SIM_PROXY_CODE = '''
import duckdb as _duckdb

class SimulationProxy:
    """Writable in-memory DuckDB, populated on demand by the LLM."""
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn = None

    def _ensure_conn(self):
        if self._conn is None:
            self._conn = _duckdb.connect(":memory:")
            self._conn.execute(f"ATTACH \'{self._db_path}\' AS prod_db (READ_ONLY);")

    def clone(self, tables: list) -> None:
        """Clone prod tables into sim_<table>. Idempotent."""
        self._ensure_conn()
        for table in tables:
            sim_name = f"sim_{table}"
            exists = self._conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [sim_name]
            ).fetchone()[0]
            if not exists:
                self._conn.execute(
                    f"CREATE TABLE {sim_name} AS SELECT * FROM prod_db.{table};"
                )

    def execute(self, sql: str, params: list = None):
        """Parameterized SQL against the writable in-memory sim DB."""
        self._ensure_conn()
        return self._conn.execute(sql, params) if params else self._conn.execute(sql)

sim = SimulationProxy(r"{db_path_str}")
'''

# In _execute_subprocess(), include SIM_PROXY_CODE in the generated full_code
# (just like db_query_code is included today). The session-level `sim` instance
# lives for the entire duration of one subprocess execution — across all steps
# within a single experiment_code block.
```

> **Multi-step state persistence**: within one `execute_experiment()` call the `sim`
> instance is alive for the full block. For cross-call persistence (multi-turn ReAct),
> each subsequent call needs to pass a `session_id`; the sandbox maps
> `session_id → tmp_db_file` (a named temp file instead of `:memory:`) so state
> survives across subprocess boundaries within the same agent turn.

**LLM-side workflow (written inside the Sandbox by the LLM itself):**

```python
# Step 1 — Discover available tables and their columns from schema_catalog
# (schema_catalog is a real table in prod DB: source_type, source_name, fields JSON)
available = db.query("SELECT source_name, fields FROM schema_catalog")
# OR: use DuckDB INFORMATION_SCHEMA as fallback
all_tables = db.query(
    "SELECT table_name, column_name, data_type "
    "FROM information_schema.columns "
    "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
)

# Step 2 — LLM decides which tables are relevant for the current simulation layer
# (no hardcoding — the LLM reasons from the schema discovery output above)
# Example decision for an L1/L2 + L3 simulation:
needed_tables = [
    t["table_name"] for t in all_tables
    if t["table_name"] in ("topology_links", "interfaces", "routes", "ospf_neighbors")
]

# Step 3 — Clone only what's needed into writable in-memory sim DB
sim.clone(needed_tables)

# Step 4 — Mutate sim tables to model failure scenarios (never touches production)
sim.execute("UPDATE sim_ospf_neighbors SET state = 'DOWN' WHERE neighbor_ip = ?",
            ["10.0.0.1"])
sim.execute("DELETE FROM sim_topology_links WHERE source_device = 'R2'")

# Step 5 — Run deterministic graph analysis on the mutated state
import networkx as nx
links = sim.execute("SELECT source_device, destination_device FROM sim_topology_links "
                    "WHERE link_status = 'active'").fetchall()
G = nx.DiGraph()
G.add_edges_from([(r[0], r[1]) for r in links])

_result = {
    "path_r1_r4": nx.shortest_path(G, "R1", "R4") if nx.has_path(G, "R1", "R4") else None,
    "r2_removed": True,
    "convergence": "success"
}
```

**Schema reference the LLM always has available** (from `information_schema` query above at runtime):

| Layer | Tables the LLM will likely select | Key columns |
|-------|-----------------------------------|-------------|
| L1/L2 | `topology_links`, `interfaces` | `source_device`, `source_interface`, `destination_device`, `link_status`, `discovery_protocol` / `device_name`, `interface`, `ip_address`, `status` |
| L3    | `routes`, `ospf_neighbors`, `bgp_neighbors` | `device_name`, `network`, `mask`, `next_hop`, `protocol`, `metric` / `neighbor_ip`, `state` |
| L4    | ⚠️ No `acls` table yet — blocked until `show access-lists` pipeline is built. Track in `dev_docs/issues.md`. |

> **Why this design is better than hardcoding:**
> - When new tables are added (e.g., `acls`, `mpls_labels`), the LLM discovers them automatically — zero platform changes needed.
> - The LLM selects the minimal set of tables for a given task, avoiding unnecessary memory clones.
> - `sim.clone()` is idempotent: multi-step ReAct loops can call it repeatedly without duplication.
> - Session state is preserved across tool calls within one agent turn (the `SimulationProxy` instance lives for the duration of the sandbox session).

#### C. Merging `ops-routing` + `ops-simulation` → `ops-routing-simulator`

##### C.1 Why Merge

| What | Current home | Problem |
|---|---|---|
| `execute_sql` | `routing/tools/` **and** `simulation/tools/` | **100% identical code, duplicated across both agents** |
| `simulate_change` | `simulation/tools/` | Wraps `NetworkSimulator` from `olav.core.simulation.engine` — the **old** imperative simulation engine. Superseded by `LLMExperimentSandbox` + `SimulationProxy` (Section B) |
| `analyze_network_topology` | `simulation/tools/` | Wraps `olav.core.memory.topology` (DuckPGQ-based path query). Superseded by in-sandbox `networkx` living graph (Section E) |
| `execute_cli` | `routing/tools/` only | Keep — feeds `cli_execute` injection (Section F.5) |
| `format_and_export` | `routing/tools/` only | Keep — still needed for exporting reports |
| `ROUTING_EXPERT_GUIDE.md` | `routing/references/` | Keep as `references/` in the merged agent — static context for BGP/OSPF rules |

**Result**: `ops-routing` is deleted entirely. `ops-simulation` is deleted. A single `ops-routing-simulator` is created with no duplicate code.

##### C.2 Deletion Manifest

Files to **delete**:
```
.olav/workspace/ops/routing/               ← entire directory removed
.olav/workspace/ops/simulation/tools/execute_sql.py        ← duplicate of routing's
.olav/workspace/ops/simulation/tools/simulate_change.py    ← replaced by sandbox
.olav/workspace/ops/simulation/tools/analyze_network_topology.py  ← replaced by networkx
.olav/workspace/ops/simulation/prompts/system.md           ← replaced by new prompt
.olav/workspace/ops/simulation/SKILL.md                    ← entire dir replaced
```

Files to **keep / migrate**:
```
routing/tools/execute_sql.py       → routing-simulator/tools/execute_sql.py
routing/tools/execute_cli.py       → routing-simulator/tools/execute_cli.py
routing/tools/format_and_export.py → routing-simulator/tools/format_and_export.py
routing/references/ROUTING_EXPERT_GUIDE.md → routing-simulator/references/ROUTING_EXPERT_GUIDE.md
```

New file to **create**:
```
routing-simulator/tools/run_python_simulation.py   ← wraps LLMExperimentSandbox
routing-simulator/prompts/system.md                ← merged prompt (see Section D)
routing-simulator/SKILL.md                         ← below
```

##### C.3 New `SKILL.md`

```yaml
---
name: ops-routing-simulator
description: >
  Unified routing analysis and network simulation agent.
  Queries BGP/OSPF/routing tables for live state; runs deterministic Python
  simulations via LLMExperimentSandbox (networkx + netutils) for What-If analysis.
  Does NOT guess outcomes — writes code to compute them.
metadata:
  version: 2.0.0
  replaces: [ops-routing v1.0.0, ops-simulation v0.1.0]
  type: agent
  category: network-operations
  intents: [routing_analysis, change_simulation, topology_analysis]
tools:
  - execute_sql              # Query: bgp_routes, routes, ospf_neighbors, bgp_neighbors, topology_links, interfaces
  - execute_cli              # Live: show ip bgp / show ip ospf neighbor / show ip route
  - run_python_simulation    # Sandbox: LLMExperimentSandbox with sim + networkx + netutils
  - format_and_export        # Output: CSV/JSON/Markdown report export
allowed_tables:
  - bgp_routes
  - routes
  - bgp_neighbors
  - ospf_neighbors
  - topology_links
  - interfaces
  - devices
  - parsed_outputs
  - schema_catalog
static_context:
  - path: ./references/ROUTING_EXPERT_GUIDE.md
system: $ref:./prompts/system.md
---

## Overview

Unified agent combining BGP/OSPF routing analysis with deterministic graph-based
simulation. For any "what happens if..." question, writes Python code to compute
the exact outcome using networkx and netutils in a secure sandbox.

## Use Cases

1. **Routing Analysis**: BGP AS-PATH, OSPF cost, route lookup, blackhole detection
2. **Change Impact**: Simulate link/device/neighbor failure via sandbox graph mutation
3. **Path Analysis**: OSPF/BGP shortest path with cost weights via networkx
4. **BGP Best-Path**: Deterministic best-path from local_pref, as_path, weight
5. **Multi-Layer Topology**: L2 (LLDP/CDP) + L3 (OSPF/BGP) enriched living graph

## Replaced Agents

- `ops-routing` (v1.0.0): all capabilities migrated here
- `ops-simulation` (v0.1.0): `simulate_change` (NetworkSimulator) and
  `analyze_network_topology` (DuckPGQ) replaced by `run_python_simulation`
  backed by `LLMExperimentSandbox`
```

#### D. Merged System Prompt (`routing-simulator/prompts/system.md`)

The prompt replaces both `ops-routing/prompts/system.md` (BGP/OSPF expertise) and `ops-simulation/prompts/system.md` (impact prediction). It unifies two previously separate reasoning modes into one agent:

> "You are OLAV's Routing & Simulation Expert — a unified agent for BGP, OSPF, static route analysis, and deterministic network simulation.
>
> ## Routing Analysis Mode
> For questions about current routing state (neighbors, BGP sessions, route tables):
> - Use `execute_sql` to query `bgp_routes`, `routes`, `ospf_neighbors`, `bgp_neighbors`.
> - Use `execute_cli` for live verification: `show ip bgp`, `show ip ospf neighbor`, `show ip route`.
> - Use `format_and_export` to export route tables as CSV or Markdown reports.
> - Consult `ROUTING_EXPERT_GUIDE.md` (static context) for BGP best-path selection rules and OSPF area design.
>
> ## Simulation Mode (What-If / Change Impact)
> For any question of the form "what happens if...", "simulate...", "predict impact of...":
> - **DO NOT GUESS**. Write Python code via `run_python_simulation` to compute the answer.
> - In your Sandbox, you have access to:
>   - `db`: Read-only production database. First query schema:
>     ```python
>     schema = db.query("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'main' ORDER BY table_name, ordinal_position")
>     ```
>   - `sim`: Writable in-memory sandbox DB. Call `sim.clone(['topology_links', 'ospf_neighbors', ...])`, then `sim.execute(sql)` to mutate state.
>   - `networkx` (as `nx`): Build the living graph (Section E pattern). One graph, all layers.
>   - `netutils.ip`: Subnet overlap checks (`is_ip_within_cidr`), prefix math.
>   - Always emit `_result["topology_coverage"]` so the caller knows which OSI layers have data.
>
> ## Missing Data
> Before any simulation, check data coverage (Section F pattern). If a required table is empty:
> - **No template** (parsed_data is null): `cli_execute()` + inline parse, set `_result["data_gap"] = "no_template:<cmd>"`
> - **No data collected** (table has 0 rows): `cli_execute()` to collect live, emit staging record.
>
> ## Rules
> - For physical topology questions, query `topology_links` (LLDP/CDP data) — this agent has full access, unlike the old routing agent which was restricted.
> - `simulate_change` (old tool) and `analyze_network_topology` (old DuckPGQ tool) no longer exist. Use `run_python_simulation` instead.
> - Blast radius = all devices that lose primary or backup paths after the modeled change (compute via `nx.connected_components` or `nx.has_path` on the post-failure active subgraph)."
#### E. Topology as a Living Graph: Progressive Layer Enrichment

Since OLAV already maintains LLDP/CDP (`topology_links`), OSPF (`ospf_neighbors`), BGP (`bgp_neighbors`, `bgp_routes`), and interface IP data (`interfaces`), the correct pattern is **not** to build a separate model per layer. Instead, build **one `networkx` graph** from the physical topology and progressively annotate nodes and edges with higher-layer attributes. The graph's analytical richness scales automatically with what data is available.

```
topology_links  ──→  nx.DiGraph (L2 skeleton: nodes=devices, edges=physical links)
                             │
interfaces      ──→  node attrs: ip_addresses = [{interface, ip_address}, ...]
                             │
ospf_neighbors  ──→  edge attrs: ospf_cost, ospf_state, ospf_area
routes          ──→  edge attrs: igp_protocol, route_metric
                             │
bgp_neighbors   ──→  BGP overlay: separate logical edges (may not follow physical path)
bgp_routes      ──→  node attrs: advertised_prefixes, best_path flags
                             │
acls (future)   ──→  edge attrs: acl_in, acl_out  [Blocked — no collection yet]
```

**One clone, one graph, all layers:**

```python
import networkx as nx
import netutils.ip as net_ip

# Clone all available tables at once (idempotent — safe to call every experiment)
sim.clone(["topology_links", "interfaces", "ospf_neighbors", "routes",
           "bgp_neighbors", "bgp_routes"])

# ── Layer 1/2: Physical skeleton from LLDP/CDP ───────────────────────────────
G = nx.DiGraph()
links = sim.execute(
    "SELECT source_device, destination_device, source_interface, "
    "destination_interface, link_status, discovery_protocol "
    "FROM sim_topology_links"
).fetchall()
for src, dst, s_iface, d_iface, status, proto in links:
    G.add_edge(src, dst,
               src_interface=s_iface, dst_interface=d_iface,
               link_status=status, discovery=proto,
               ospf_cost=1)        # default cost; overwritten in L3 step

# ── Layer 3a: Enrich nodes with IP addresses ─────────────────────────────────
ifaces = sim.execute(
    "SELECT device_name, interface, ip_address "
    "FROM sim_interfaces WHERE ip_address IS NOT NULL"
).fetchall()
ip_index = {}   # ip_address → device_name (for OSPF neighbor resolution)
for device, iface, ip in ifaces:
    G.nodes[device].setdefault("ip_addresses", []).append(
        {"interface": iface, "ip": ip}
    )
    ip_index[ip.split("/")[0]] = device   # strip prefix len if present

# ── Layer 3b: Enrich edges with OSPF state and cost ──────────────────────────
ospf_rows = sim.execute(
    "SELECT device_name, neighbor_ip, interface, state "
    "FROM sim_ospf_neighbors"
).fetchall()
for device, neighbor_ip, iface, state in ospf_rows:
    neighbor_device = ip_index.get(neighbor_ip)
    if neighbor_device and G.has_edge(device, neighbor_device):
        G[device][neighbor_device]["ospf_state"] = state
        G[device][neighbor_device]["layer"] = "L3-OSPF"
        # Pull metric from routes table for this next-hop
        metric_row = sim.execute(
            "SELECT metric FROM sim_routes WHERE device_name = ? AND next_hop = ? LIMIT 1",
            [device, neighbor_ip]
        ).fetchone()
        if metric_row:
            G[device][neighbor_device]["ospf_cost"] = metric_row[0] or 1

# ── Layer 3c: BGP overlay (logical — does NOT follow physical topology) ───────
# BGP sessions are added as separate edge type, not overwriting OSPF edges
bgp_rows = sim.execute(
    "SELECT device_name, neighbor_ip, neighbor_as, state "
    "FROM sim_bgp_neighbors"
).fetchall()
for device, neighbor_ip, neighbor_as, state in bgp_rows:
    neighbor_device = ip_index.get(neighbor_ip)
    if neighbor_device:
        # Add BGP as a distinct edge attribute (may already exist as physical edge)
        if G.has_edge(device, neighbor_device):
            G[device][neighbor_device]["bgp_session"] = state
            G[device][neighbor_device]["bgp_as"] = neighbor_as
        else:
            # iBGP over loopback — no physical edge, add logical BGP-only edge
            G.add_edge(device, neighbor_device,
                       bgp_session=state, bgp_as=neighbor_as,
                       layer="L3-BGP-logical", link_status="logical")

# Enrich nodes with BGP advertised prefixes
bgp_prefix_rows = sim.execute(
    "SELECT device_name, network, mask, local_pref, best_path "
    "FROM sim_bgp_routes WHERE best_path = TRUE"
).fetchall()
for device, network, mask, local_pref, _ in bgp_prefix_rows:
    G.nodes[device].setdefault("bgp_prefixes", []).append(
        {"prefix": f"{network}/{mask}", "local_pref": local_pref}
    )
```

**Failure simulation — mutate sim table, rebuild graph in-place:**

```python
# Simulate R2 failure: take all its links down
sim.execute("UPDATE sim_topology_links SET link_status = 'down' "
            "WHERE source_device = 'R2' OR destination_device = 'R2'")
sim.execute("UPDATE sim_ospf_neighbors SET state = 'DOWN' "
            "WHERE device_name = 'R2' OR neighbor_ip IN "
            "(SELECT ip FROM (SELECT json_extract(ip_address, '$') AS ip "
            " FROM sim_interfaces WHERE device_name = 'R2'))")

# Rebuild graph with only active links (re-run the build above, or filter in-place)
active_links = [(u, v) for u, v, d in G.edges(data=True) if d.get("link_status") == "active"]
G_active = G.edge_subgraph(active_links).copy()

# Deterministic path query with OSPF cost as weight
src, dst = "R1", "R4"
if nx.has_path(G_active, src, dst):
    path = nx.shortest_path(G_active, src, dst, weight="ospf_cost")
    cost = nx.shortest_path_length(G_active, src, dst, weight="ospf_cost")
    _result = {"path": path, "cost": cost, "r2_reachable": False}
else:
    _result = {"path": None, "cost": None, "r2_reachable": False,
               "error": f"No path from {src} to {dst} after R2 failure"}
```

**Why progressive enrichment beats per-layer isolation:**

| Concern | Per-layer isolation (old) | Progressive enrichment (new) |
|---|---|---|
| Number of graph builds per scenario | One per layer | One total |
| Failure simulation | Re-query + rebuild per layer | Mutate one sim table, rebuild once |
| BGP over iBGP (no physical edge) | Missed — only physical adjacency used | Explicit logical edge with `layer="L3-BGP-logical"` |
| New protocol (MPLS, SRv6) | New section/class required | Add edge attribute in LLM code, zero platform change |
| `nx.shortest_path(weight=)` | Must pick one weight per query | Any edge attribute is a valid weight — LLM chooses |
| Missing layer data | Silently skipped | Layer attribute absent on edge → LLM stops at that layer |

**Layer detection at query time:**

```python
# The LLM can inspect what layers are present before deciding analysis depth
ospf_edges  = [(u,v) for u,v,d in G.edges(data=True) if d.get("ospf_state") == "FULL"]
bgp_sessions = [(u,v) for u,v,d in G.edges(data=True) if "bgp_session" in d]
l2_only     = [(u,v) for u,v,d in G.edges(data=True) if "ospf_state" not in d and "bgp_session" not in d]

_result["topology_coverage"] = {
    "l2_edges": len(G.edges()),
    "ospf_enriched": len(ospf_edges),
    "bgp_sessions": len(bgp_sessions),
    "l2_only_links": len(l2_only),   # physical links with no L3 data → data gap signal
}
```

> If `l2_only_links > 0`, the LLM knows those edges have no L3 data and should trigger
> Section F (data gap recovery) before performing L3 path analysis on them.

**Benefits:**
- **Zero Hardcoding:** Any new protocol adds an edge attribute — the platform never changes.
- **Single Source of Truth:** One graph instance holds the complete network digital twin for the current simulation.
- **Layer-Isolated Diagnostics:** Missing attributes signal the exact OSI layer where data ends, preventing hallucination about higher layers.
- **Composable What-If:** `sim.execute()` mutations propagate to the graph on next rebuild — no state inconsistency between DB and graph.

---

#### F. Handling Missing Data: Template Gap vs Data Gap

Before running any simulation, the LLM **must** verify that the required data actually exists in the DB. Two distinct failure modes require different recovery paths.

##### F.1 Diagnostic Query (always run first)

```python
# Step 0 — Before any sim.clone(), check data completeness
# Check which tables have data for the devices in scope
coverage = db.query("""
    SELECT
        'ospf_neighbors'  AS tbl, count(*) AS rows FROM ospf_neighbors
    UNION ALL SELECT 'routes',        count(*) FROM routes
    UNION ALL SELECT 'bgp_neighbors', count(*) FROM bgp_neighbors
    UNION ALL SELECT 'interfaces',    count(*) FROM interfaces
    UNION ALL SELECT 'topology_links',count(*) FROM topology_links
""")
missing = [r['tbl'] for r in coverage if r['rows'] == 0]
```

If `missing` is non-empty the LLM must determine **why** before proceeding.

##### F.2 Case A — No Template (parser gap)

**Signal**: `parsed_outputs` has rows for the device+command but all `parsed_data` fields are `null` or `{}`, **OR** the command does not appear in `parsed_outputs` at all while raw output files exist.

```python
# Detect parser gap
parse_check = db.query("""
    SELECT command, count(*) AS total,
           sum(CASE WHEN parsed_data IS NULL OR parsed_data = '{}' THEN 1 ELSE 0 END) AS unparsed
    FROM parsed_outputs
    WHERE device_name = 'R1'
    GROUP BY command
""")
unparsed_commands = [r['command'] for r in parse_check if r['unparsed'] == r['total']]
```

**Recovery**: The LLM calls `execute_cli` to get fresh raw output and parses it inline with Python string processing / regex — **no template needed**. The result is used directly for this simulation without being persisted to DB.

```python
# Inline raw parse — used for current simulation only
raw = cli_execute(device="R1", command="show ip ospf neighbor")
# LLM writes ad-hoc parser for the raw text
neighbors = []
for line in raw['output'].splitlines():
    parts = line.split()
    if len(parts) >= 6 and '.' in parts[0]:  # heuristic: starts with IP
        neighbors.append({'neighbor_id': parts[0], 'state': parts[2], 'interface': parts[-1]})

# Use parsed result directly in networkx graph — bypass DB entirely
G = nx.DiGraph()
for n in neighbors:
    if 'FULL' in n['state']:
        G.add_edge('R1', n['neighbor_id'])
```

> The LLM should also set `_result["data_gap"] = "no_template:show_ip_ospf_neighbor"` so the
> calling agent knows to flag this command for template development.

##### F.3 Case B — No Data (collection gap)

**Signal**: `parsed_outputs` has **zero** rows for the device (or the table is entirely empty, e.g. `ospf_neighbors` has 0 rows). Template exists; data was simply never collected.

**Recovery**: The LLM triggers live collection via `cli_execute`, parses using the inline `db_query` pattern (which calls `show` commands), and **also emits a staging record** so the data is persisted for future simulations.

```python
# Collect live if DB has no data
if db.query("SELECT count(*) AS n FROM ospf_neighbors")[0]['n'] == 0:
    # Live collection
    raw = cli_execute(device="R1", command="show ip ospf neighbor detail")

    # Agent tries the structured table first (template may now exist)
    parsed_check = db.query(
        "SELECT parsed_data FROM parsed_outputs "
        "WHERE device_name='R1' AND command='show ip ospf neighbor detail' "
        "ORDER BY created_at DESC LIMIT 1"
    )

    if parsed_check and parsed_check[0]['parsed_data']:
        # Template existed — newly parsed data is available
        neighbors = parsed_check[0]['parsed_data']
    else:
        # Fall back to inline parse (Case A path)
        neighbors = _inline_parse_ospf(raw['output'])

    _result["data_gap"] = "collection_gap:ospf_neighbors"
    _result["live_data_used"] = True
    _result["neighbors"] = neighbors
```

##### F.4 Recovery Decision Tree

```
Required table empty / missing?
        │
        ├─→ Check parsed_outputs for device + command
        │         │
        │         ├─→ rows exist but parsed_data = null/{}  ──→ [Case A] No Template
        │         │         └─→ cli_execute() + inline ad-hoc parse
        │         │               + set _result["data_gap"] = "no_template:<cmd>"
        │         │
        │         └─→ zero rows for device                  ──→ [Case B] No Data
        │                   └─→ cli_execute() to collect live
        │                         ├─→ parsed_outputs now has data? → use it
        │                         └─→ still empty? → inline parse (fallback to Case A)
        │
        └─→ Table has data → proceed with sim.clone() normally
```

##### F.5 `cli_execute` in Subprocess

`CLIExecutor.execute()` is currently a stub in `llm_sandbox.py`. The LLM-side `cli_execute()` helper is injected into the subprocess alongside `db_query()`, delegating to the `execute_cli` workspace tool via a serialized call:

```python
# Injected into subprocess (CLI_EXECUTOR_CODE string in _execute_subprocess)
def cli_execute(device: str, command: str, timeout: int = 30) -> dict:
    """Execute a CLI command on a device. Calls the ops workspace execute_cli tool."""
    import subprocess as _sp, json as _json, sys as _sys
    # Invoke execute_cli script from .olav/workspace/ops/tools/execute_cli.py
    result = _sp.run(
        [_sys.executable, "-m", "olav.tools.execute_cli",
         "--device", device, "--command", command, "--timeout", str(timeout)],
        capture_output=True, text=True, timeout=timeout + 5
    )
    try:
        return _json.loads(result.stdout)
    except Exception:
        return {"device": device, "command": command,
                "output": result.stdout or result.stderr, "status": "error"}
```

> **Security note**: `cli_execute` is write-capable (mutates real devices). The sandbox
> `_validate_code()` should confirm calls only use **read-only** `show` / `display` commands
> before execution. A command allowlist from `commands` table (`WHERE allowed=TRUE AND blacklisted=FALSE`)
> should be checked at call time.

---

#### G. Known Gaps & Simulation Boundaries (Current v0.11.0)

| Capability | Status | Blocker |
|---|---|---|
| L1/L2 topology reachability (networkx) | ✅ Ready | Base graph from `topology_links` (LLDP/CDP) |
| L3 OSPF path + cost (enriched edges) | ✅ Ready | Requires `ospf_neighbors.state` populated; edges get `ospf_cost` attribute |
| L3 BGP overlay + best-path | ✅ Ready | Requires `bgp_routes.local_pref/as_path` populated; iBGP adds logical edges |
| L3 ECMP multi-path selection | ⚠️ Partial | Needs multiple same-prefix rows in `routes`; `nx.all_shortest_paths()` ready |
| Multi-layer enrichment coverage check | ✅ Ready | `topology_coverage` dict in `_result` signals which edges lack L3 data |
| Sim DB cross-call persistence | ⚠️ Single-call only | Needs `session_id → tmp_db_file` mapping |
| STP topology change simulation | ❌ Blocked | No `spanning_tree` collection pipeline |
| VLAN isolation simulation | ❌ Blocked | No `vlans`/`mac_table` collection |
| L4 ACL packet filtering | ❌ Blocked | No `acls` collection (`show access-lists`) |
| Interface utilization / QoS | ❌ Blocked | No SNMP/NetFlow collection |

**All ❌ Blocked items must be tracked in `dev_docs/issues.md` as prerequisites before the corresponding simulation tier is documented as available.**

## Summary

OLAV achieves zero-hallucination network simulation through four composable layers:

1. **Data Trust** (`ValueNormalizer`): vendor-normalized values ensure DuckDB JOINs never silently fail.
2. **Code as a Service** (`SimulationProxy` + `networkx` + `netutils`): LLM writes deterministic math, not prose guesses. Schema is discovered at runtime — the platform never hardcodes table names.
3. **Living Graph Topology** (Section E): since LLDP/CDP, OSPF, and BGP tables already exist, one `networkx` graph is built from the physical skeleton and progressively enriched with L3 attributes (OSPF cost on edges, IP addresses on nodes, BGP logical overlays). New protocols add edge/node attributes without any platform change. A `topology_coverage` signal tells the LLM exactly where enrichment ends — preventing analysis beyond available data.
4. **Graceful Degradation** (Section F): when data is absent, the LLM distinguishes *template gap* from *collection gap* and autonomously recovers via live CLI collection, keeping the simulation unblocked while flagging the gap for remediation.

**Agent consolidation** (Section C): `ops-routing` (v1) and `ops-simulation` (v0.1) are deleted. The merged `ops-routing-simulator` (v2) eliminates the duplicate `execute_sql` implementation, replaces the old `NetworkSimulator`-backed `simulate_change` tool with `run_python_simulation` + `LLMExperimentSandbox`, and replaces the DuckPGQ-based `analyze_network_topology` with the in-sandbox networkx living graph. Tool count: 4 → 4 (no duplication, no dead code).

The **current simulation boundary** is L1–L3 (topology + OSPF/BGP routing). STP, VLAN, L4 ACL, and QoS simulations are forward-looking and blocked on their respective collection pipelines (tracked in `dev_docs/issues.md`).
