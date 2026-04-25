# Drift Mode

Load when the user's request uses comparison verbs — `compare`,
`diff`, `drift`, `what changed`, `before/after`, `T1 vs T2`, `漂移`,
`变更检测`.  Drift Mode uses the four `diff_*` tools instead of
`run_python_simulation`.

## Expertise

* **State comparison** — compare any DB table between two snapshots
* **Topology drift** — detect physical links that went up/down
* **Routing drift** — next-hop path shifts, lost prefixes, BGP
  AS_PATH changes
* **Config diff** — compare raw CLI configuration files between
  snapshots

## Tools

| Tool | Description |
|---|---|
| `diff_sql_state` | Compare any table between two snapshots |
| `diff_topology_drift` | Physical link state changes (up/down/status) |
| `diff_routing_drift` | Next-hop shifts, lost prefixes, BGP changes |
| `diff_configs` | Raw CLI configuration files |
| `execute_sql` | Query snapshot data for context around a diff |

## Common patterns

```python
# Compare a table between two snapshots
diff_sql_state(
    table_name="ospf_neighbors",
    snapshot_id_1="20260226_100000",
    snapshot_id_2="20260226_120000",
)

# Detect topology link state changes
diff_topology_drift(
    snapshot_id_1="20260226_100000",
    snapshot_id_2="20260226_120000",
)

# Detect routing changes scoped to one device
diff_routing_drift(
    snapshot_id_1="20260226_100000",
    snapshot_id_2="20260226_120000",
    device_name="R1",
)

# Compare raw config files
diff_configs(
    device="R1",
    command="show running-config",
    snapshot_id_1="latest",
    snapshot_id_2="latest",
)
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
* If the user follows up with a "what-if it had been fixed?" or
  "what's the impact?" question, hand off to Mode 2 simulation
  (`run_python_simulation`).
