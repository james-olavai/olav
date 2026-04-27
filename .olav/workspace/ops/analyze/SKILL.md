---
name: ops-analyze
description: >
  Unified network analysis + drift detection sub-agent. Merges the former
  ``ops-analysis`` (routing analysis, deterministic simulation, topology
  visualization) and ``ops-diff`` (snapshot state comparison, drift detection)
  sub-agents. Reads production DB; runs Python sims via ``run_python_simulation``
  and diff via four ``diff_*`` tools. Does not access live devices.
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
  - run_python_simulation  # Analysis Mode SANDBOX (ad-hoc networkx/netutils what-if;
                           # NOT used for the 5 deterministic helpers below — those
                           # are skill scripts via execute_skill_script per ADR-0008)
# Drift Mode + CAB emit — call as skill scripts via execute_skill_script
# (inherited from core/tools/, per ADR-0008 R92.3):
#   skill_name="analyze", script_name=
#     {tcf_emit_from_sim.py, diff_sql_state.py, diff_topology_drift.py,
#      diff_routing_drift.py, diff_configs.py}
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
static_context:
  - path: ./references/ROUTING_EXPERT_GUIDE.md
# R86 — on_intent (~3.3K tokens).  ROUTING_EXPERT_GUIDE is the
# largest static reference in any agent; baking it on every
# ops-analyze invocation is wasteful when most queries (drift,
# topology) don't need routing expertise.  Loaded only when the
# query keyword-matches; agent can fetch via get_static_context
# explicitly when needed.
static_context_mode: on_intent
system: $ref:./prompts/system.md
---

## Overview

Unified sub-agent with **two modes** dispatched by the ops orchestrator based on
task keywords:

### Analysis Mode (was `ops-analysis` v1.1.0)

Proactive theoretical work — understand the current network, simulate changes,
visualize topology.

1. **Routing Analysis** — BGP/OSPF/routing table analysis from DuckDB snapshots
2. **Change Simulation** — Deterministic what-if via networkx + netutils sandbox
3. **Topology Visualization** — L2/L3 graphs, path analysis, Mermaid diagrams

Use when the task contains: `simulate`, `what-if`, `change plan`, `BGP/OSPF/路由`,
`变更方案`, `topology`, `path`, `loop`.

### Drift Mode (was `ops-diff` v1.0.0)

Retrospective comparison — what changed between two snapshots?
Per ADR-0008 R92.3, the four diff helpers are skill scripts under
``ops/analyze/scripts/``. Invoke via ``execute_skill_script``:

```python
execute_skill_script(
    skill_name="analyze",
    script_name="diff_sql_state.py",
    script_args={"table_name": "ospf_neighbors", "snapshot_id_1": "t1", "snapshot_id_2": "t2"},
)
```

1. **State Comparison** — any operational table (`diff_sql_state.py`)
2. **Topology Drift** — physical link up/down changes (`diff_topology_drift.py`)
3. **Routing Drift** — prefix loss / next-hop shift / AS-PATH changes (`diff_routing_drift.py`)
4. **Config Diff** — raw config file comparison (`diff_configs.py`)

Use when the task contains: `drift`, `compare`, `what changed`, `delta`,
`snapshot T1 vs T2`, `before/after`, `漂移`, `变更检测`.

## Mode Dispatch

The parent ops orchestrator (`ops/prompts/orchestrator.md`) routes drift-keyword
tasks and analysis-keyword tasks to this single sub-agent. Within this sub-agent:

- Start by identifying the mode from the request's verbs: "simulate / analyze /
  design" → Analysis; "compare / diff / what changed" → Drift.
- In Analysis Mode, the only tool is `run_python_simulation` (the sandbox covers
  all needs via `db`, `sim`, `nx`, `netutils`).
- In Drift Mode, use `execute_skill_script(skill_name="analyze", ...)` with
  the relevant ``diff_*.py`` script. R92.3 (ADR-0008) put the 4 helpers as
  skill scripts under ``ops/analyze/scripts/``. ``run_python_simulation``
  is reserved for Analysis-Mode ad-hoc work (graph algorithms / what-if).

A single request can invoke both modes sequentially (e.g. "compare yesterday's
snapshot, then simulate fixing the broken links").

## Analysis Mode — Tool Notes

- `run_python_simulation` — sandbox with `db` (read-only DB proxy), `sim`
  (writable in-memory clone), `nx` (networkx), `netutils`. Network isolation
  via `OLAV_SANDBOX_NETNS=1` env var.
- **sandbox_guard SQL rule**: `sim.execute()` with literal SQL starting with
  `CREATE` / `INSERT` / etc. must use a variable:
  ```python
  _sql = "CREATE TABLE sim_x (col VARCHAR)"
  sim.execute(_sql)  # NOT: sim.execute("CREATE TABLE ...")
  ```

## Design Feasibility Check — Common BLOCKER Patterns (Analysis Mode)

Always query these from DB, never assume:

| Required Info | DB Source | BLOCKER if missing |
|---|---|---|
| Peer AS number | `netops.v_bgp_neighbors_auto.neighbor_as` | Yes — cannot design session type |
| BGP link IP | JSON-extract `netops.parsed_outputs` where `command LIKE 'show%ip interface%'`; fallback `netops.v_l2_links_auto` for the physical link | Yes — Phase 0 must assign IPs |
| Direct physical link | `netops.v_l2_links_auto WHERE source_device=X AND destination_device=Y` | Warning (not blocker if via intermediate hops) |
| IGP between peers | `netops.v_ospf_neighbors_auto` | Blocker for iBGP design |
| Route to loopback | JSON-extract `parsed_outputs` where `command='show ip route'` (no materialised view) | Blocker for multihop eBGP |

If ANY BLOCKER is found: **state it explicitly** as a Phase 0 prerequisite. Do
NOT assume or invent values.

## Drift Mode — Workflow

1. **Select Snapshots**: Choose two `snapshot_id` values (T1=before, T2=after)
2. **Invoke the appropriate skill script**:
   ```python
   execute_skill_script(
       skill_name="analyze",
       script_name="diff_sql_state.py",   # or diff_topology_drift / diff_routing_drift / diff_configs
       script_args={"table_name": "ospf_neighbors", "snapshot_id_1": "t1", "snapshot_id_2": "t2"},
   )
   ```
   Pick the script by dimension:
   - `diff_sql_state.py` — any table (ospf_neighbors, interfaces, etc.)
   - `diff_topology_drift.py` — `topology_links` changes
   - `diff_routing_drift.py` — `routes` / `bgp_routes` changes
   - `diff_configs.py` — raw config files
3. **Analyze Results**: Review delta (`missing_in_t2`, `new_in_t2` — inside the
   `stdout` dict the script returned)
4. **Report**: Findings with root cause analysis

## Sandbox Network Policy

**`network_isolation=True`** — analysis sandbox is fully network-isolated.
All simulation is pure local computation.

```python
execute_in_sandbox(code, network_isolation=True)
```

## Migration Notes

- Replaces `ops-analysis` (v1.1.0) and `ops-diff` (v1.0.0) — Sprint 3 Step C
  (Round 31). ADR-0003 `docs/adr/0003-audit-ops-sub-agent-parity.md` documents
  the "distinct workflow count" rationale for the merge.
- All intents from both agents are available: `routing_analysis`,
  `change_simulation`, `topology_analysis`, `topology_visualization`,
  `state_comparison_drift_detection`.
- External callers: orchestrator `task("ops-analysis", ...)` and
  `task("ops-diff", ...)` both → `task("ops-analyze", ...)`. See
  `ops/prompts/orchestrator.md`.
