---
name: network-query
version: 7.0.0
description: Query network device inventory, CLI outputs, and interface data using intelligent SQL tool with auto schema discovery
author: Network AI Team
type: agent
category: network-operations
intent: quick_query

tools:
  - smart_sql_query

prompts:
  system: $ref:./prompts/system.md

---

## Overview

Query network device inventory and interface data using DuckDB SQL with intelligent auto-discovery.

## Key Features

✅ **Intelligent SQL with Auto Schema Discovery**
- Call smart_sql_query with natural language
- Automatic schema context discovery
- SQL generation with error correction
- ReAct loop for self-healing

✅ **Simple 2-Step Workflow**
1. `smart_sql_query(query="natural language")` → Get schema context
2. `smart_sql_query(sql="SELECT ...")` → Execute query

✅ **Smart Escalation**
- `<cli_needed>` - When database cannot answer (live data)
- `<escalate_to_expert>` - When analysis/RCA needed

✅ **DuckDB Best Practices**
- DATE/TIME: Use INTERVAL syntax
- Complex queries: Use CTEs
- CASE: Keep simple
- NULL: Use COALESCE()

## Examples

### Simple Count
```
User: "有多少个设备?"
Smart query → 6 devices
```

### Filtered Query with Error Correction
```
User: "Show border devices"
smart_sql_query(query=...) → Schema context
smart_sql_query(sql="WHERE role='border'") → Correction → Results
```

### CLI Escalation
```
User: "Show OSPF neighbors"
<cli_needed>OSPF dynamic data requires live device query</cli_needed>
```

### Expert Escalation
```
User: "Why are BGP sessions timing out?"
<escalate_to_expert>Requires RCA investigation</escalate_to_expert>
```

## Tool Reference

### smart_sql_query(query=None, sql=None)

**Parameters:**
- `query`: Natural language (returns schema context)
- `sql`: SQL to execute (returns results)

**Usage:**
```python
# Get schema
result = smart_sql_query(query="show me devices")

# Execute SQL
result = smart_sql_query(sql="SELECT * FROM devices")

# Error handling (automatic)
result = smart_sql_query(sql="SELECT * FROM invalid")
# → Returns error + hints
```

## Migration

**v6.0.0 → v7.0.0:**
- OLD: inspect_schema() + manual debugging
- NEW: smart_sql_query() + auto-hints

**Benefits:**
- 90% less schema documentation
- No manual schema calls
- Automatic error recovery
- Unified tool

## Technical

- **Backend:** DuckDB
- **Database:** main.duckdb
- **Error Handling:** ReAct with schema hints
- **Performance:** <2s typical query time
