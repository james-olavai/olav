---
name: log-analytics
description: "Log Query & Intelligent Analysis — DuckDB metrics queries, LanceDB semantic search, log enhancement"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: log-operations
  intent: log_query_and_analysis
tools:
  - log_metrics_query     # log_metrics.py — DuckDB Parquet query for log metrics
  - semantic_log_search   # log_semantic.py — LanceDB vector search for fault diagnosis
database_schema:
  logs_parquet:
    description: "Full log storage in Parquet format — query via DuckDB in-memory mode"
    storage_path: ".olav/databases/logs/YYYY-MM-DD/"
    key_columns: [timestamp, host, severity, message, facility, raw]
  logs_lancedb:
    description: "Semantic fault knowledge base — LLM-enhanced diagnostic cards"
    storage_path: ".olav/databases/lancedb/logs.lance"
    key_columns: [id, device_name, timestamp, severity, original_message, enhanced_summary, root_cause, affected_module, vector_embedding]
escalation:
  to_expert:
    trigger: "User asks 'why', 'diagnose', 'root cause', 'recommend fix'"
    marker: <escalate_to_expert>reason</escalate_to_expert>
  cli_needed:
    trigger: "Real-time log streaming required, historical data insufficient"
    marker: <cli_needed>reason</cli_needed>
analysis_workflow:
  step_1: Scope Definition - Identify time range, devices, severity levels
  step_2: Metrics Query - Get log counts, error rates via log_metrics_query
  step_3: Semantic Search - Find similar faults via semantic_log_search
  step_4: Root Cause Analysis - LLM-powered diagnostic card generation
  step_5: Recommendations - Suggest fixes based on historical patterns
---

## Overview

Log Analytics skill provides intelligent log query and fault diagnosis:

1. **Metrics Query** — Fast SQL queries on DuckDB (log counts, error rates, time-series)
2. **Semantic Search** — Vector similarity search for fault diagnosis
3. **Log Enhancement** — LLM-powered noise reduction (experimental)

## Strategy

### When to Use Metrics Query
- Log count aggregation by severity, host, time window
- Time-series trends (errors per minute/hour)
- Finding specific error patterns in historical logs

### When to Use Semantic Search
- "Show me similar past faults"
- "What caused this error before?"
- Root cause analysis from natural language

### Data Storage
- **Parquet** (`.olav/databases/logs/`): Full logs for audit and aggregation
- **LanceDB** (`.olav/databases/lancedb/logs.lance`): Enhanced diagnostic cards

## Query Examples

### Metrics Query
```sql
SELECT severity, count(*) as cnt 
FROM read_parquet('.olav/databases/logs/*.parquet')
WHERE timestamp >= now() - interval '1 hour'
GROUP BY severity
```

### Semantic Search
Search: "interface flapping causing packet loss"
Returns: Similar past incidents with root cause and fix recommendations
