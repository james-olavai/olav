---
name: log-analytics
description: "Log Query & Intelligent Analysis — SQL metrics queries, semantic fault search, log enhancement"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: log-operations
subagents:
  - probe/SKILL.md
---

## Overview

Log Analytics Agent provides unified log query and analysis capabilities:

1. **Metrics Query** — SQL queries on DuckDB (log metrics, aggregation, time-series)
2. **Semantic Search** — Vector similarity search on LanceDB (fault diagnosis, root cause analysis)
3. **Log Enhancement** — LLM-powered log noise reduction and structured extraction (experimental)

## Architecture

- **DuckDB**: Full log storage in Parquet format (`.olav/databases/logs/`)
- **LanceDB**: Semantic fault knowledge base (`.olav/databases/lancedb/logs.lance`)
- **Query Agent**: Tier 1 agent for fast metrics queries
- **Ops Subagent**: Tier 2 agent for deep fault investigation

## Escalation

- `<escalate_to_expert>`: Root cause analysis, cross-device correlation, topology reasoning
