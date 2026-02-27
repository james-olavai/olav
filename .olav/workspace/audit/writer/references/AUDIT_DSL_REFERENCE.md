# 🛠️ Audit DSL Reference (YAML)

Use this specification to write valid `audit.yaml` rules.

## 🏠 Root Structure
```yaml
name: "Short descriptive name"
description: "Why are we checking this?"
severity: "high" | "medium" | "low"
category: "compliance" | "security" | "health"
scope:
  device_group: "all" | ["R1", "R2"]
  tables: ["interfaces", "bgp_routes"]
rules:
  - id: "BPDU_GUARD_CHECK"
    type: "sql_match" | "cli_regex"
    query: "SELECT ... FROM ..." # If sql_match
    expectation: "equals" | "contains" | "range"
    target_value: "up"
```

## 📋 Common Check Types
1. **`sql_match`**: Runs a DuckDB query. Truthy if result is not empty or matches `target_value`.
2. **`cli_regex`**: Runs a command and matches output against a regex patterns.

## 💡 Best Practices
- Use `snapshot_id = (SELECT MAX(snapshot_id) FROM sync_metadata)` in all SQL-based rules.
- Prefer **SQL-based checks** for inventory and state; use **CLI-based checks** only for very deep, non-normalized config fragments.
