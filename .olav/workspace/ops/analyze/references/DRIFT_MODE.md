# Drift Mode

Load when the user's request uses comparison verbs — `compare`,
`diff`, `drift`, `what changed`, `before/after`, `T1 vs T2`, `漂移`,
`变更检测`. Per ADR-0008 R92.3, Drift Mode uses **skill scripts** under
``ops/analyze/scripts/`` invoked via ``execute_skill_script`` —
**not** ``run_python_simulation`` (sandbox is reserved for Analysis
Mode ad-hoc graph algorithms).

## Expertise

* **State comparison** — compare any DB table between two snapshots
* **Topology drift** — detect physical links that went up/down
* **Routing drift** — next-hop path shifts, lost prefixes, BGP
  AS_PATH changes
* **Config diff** — compare raw CLI configuration files between
  snapshots

## Skill scripts

| Script | Description |
|---|---|
| `diff_sql_state.py` | Compare any table between two snapshots |
| `diff_topology_drift.py` | Physical link state changes (up/down/status) |
| `diff_routing_drift.py` | Next-hop shifts, lost prefixes, BGP changes |
| `diff_configs.py` | Raw CLI configuration files |
| `execute_sql` (MCP) | Query snapshot data for context around a diff |

## Common patterns

```python
# Compare a table between two snapshots
execute_skill_script(
    skill_name="analyze",
    script_name="diff_sql_state.py",
    script_args={
        "table_name": "ospf_neighbors",
        "snapshot_id_1": "20260226_100000",
        "snapshot_id_2": "20260226_120000",
    },
)

# Detect topology link state changes
execute_skill_script(
    skill_name="analyze",
    script_name="diff_topology_drift.py",
    script_args={
        "snapshot_id_1": "20260226_100000",
        "snapshot_id_2": "20260226_120000",
    },
)

# Detect routing changes scoped to one device
execute_skill_script(
    skill_name="analyze",
    script_name="diff_routing_drift.py",
    script_args={
        "snapshot_id_1": "20260226_100000",
        "snapshot_id_2": "20260226_120000",
        "device_name": "R1",
    },
)

# Compare raw config files
execute_skill_script(
    skill_name="analyze",
    script_name="diff_configs.py",
    script_args={
        "device": "R1",
        "command": "show running-config",
        "snapshot_id_1": "latest",
        "snapshot_id_2": "latest",
    },
)
```

The ``execute_skill_script`` tool returns a dict with the script's
parsed JSON ``stdout`` — that's where the ``status`` /
``missing_in_t2`` / ``new_in_t2`` / etc. live.

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
* If the user follows up with a "what-if it had been fixed?" or
  "what's the impact?" question, hand off to Mode 2 simulation
  (`run_python_simulation`).
