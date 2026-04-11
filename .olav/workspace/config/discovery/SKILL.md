---
name: config-discovery
description: "Schema Alignment & Discovery — view schema sync, domain agent scaffolding, fuzzy schema normalisation"
metadata:
  version: 3.1.0
  author: OLAV Platform Team
  type: agent
  category: system-administration
  intent: schema_alignment_discovery
tools:
  - fuzzy_map_schema        # Legacy LLM-based schema normalisation (fallback)
  - run_topology_sandbox    # ⚠️ REMOVED — use devops agent + run_python_code + NetworkX instead
  - discover_view_schemas   # Auto-discover and register DuckDB view schemas
  - sync_schema_reference   # Sync SCHEMA_REFERENCE.md with live DB column names
  - scaffold_domain_agent   # Scaffold a new domain agent workspace from template
static_context:
  - path: ./references/BASELINE_SCHEMA.md
---

## Overview

The Discovery Subagent handles schema synchronisation and domain agent scaffolding.
The OC schema alignment pipeline (classify_field, create_unified_view, register_api_schema,
trigger_schema_evolve) has been removed — those tools depended on schema_engine which is
not implemented in the current SSH → TextFSM → JSON pipeline.

## Tools

### fuzzy_map_schema
Legacy LLM-based normalisation for ad-hoc vendor data alignment:
- Input: vendor, command, raw_data (dict or list)
- Output: normalised data aligned to the baseline schema
- Config: `config/normalization_strategy.yaml`

### execute_sql
Direct DuckDB query execution with auto schema discovery:
- Auto schema discovery (no manual inspect_schema calls)
- DuckDB-specific optimisations
- SchemaContext singleton caching (5 min TTL)

### discover_view_schemas
Auto-discover and register DuckDB view schemas for the SchemaContext cache.
