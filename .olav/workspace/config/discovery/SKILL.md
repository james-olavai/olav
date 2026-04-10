---
name: config-discovery
description: "Schema Alignment & Unified View Engine — semantic field classification, OpenAPI integration, and schema evolution"
metadata:
  version: 3.0.0
  author: OLAV Platform Team
  type: agent
  category: system-administration
  intent: schema_alignment_unified_view_evolution
tools:
  - classify_field          # Semantic field classification (vector → LLM tiered)
  - create_unified_view     # Auto-generate DuckDB normalised VIEW from schema mappings
  - register_api_schema     # Parse OpenAPI 3.x spec → classify all fields
  - trigger_schema_evolve   # OPTICS clustering on unclassified fields → propose standards
  - fuzzy_map_schema        # Legacy LLM-based schema normalisation (fallback)
  - run_topology_sandbox    # ⚠️ REMOVED — use devops agent + run_python_code + NetworkX instead
  - discover_view_schemas   # Auto-discover and register DuckDB view schemas
  - sync_schema_reference   # Sync SCHEMA_REFERENCE.md with live DB column names
  - scaffold_domain_agent   # Scaffold a new domain agent workspace from template
static_context:
  - path: ./references/BASELINE_SCHEMA.md
---

## Overview

The Discovery Subagent handles semantic schema alignment, unified view generation,
and schema evolution for any domain integrated with OLAV — not just network vendors.

It implements a four-phase schema intelligence pipeline:

```
1. classify_field          → vector-first tiered classification (Tier 0/1/2)
2. create_unified_view     → auto-generate DuckDB VIEW from approved mappings
3. register_api_schema     → ingest OpenAPI 3.x specs and classify all fields
4. trigger_schema_evolve   → OPTICS clustering → propose new standard field names
```

## Tools

### classify_field (Phase 1)
Semantic field classification using vector similarity + optional LLM confirmation:
- Input: `field_metadata` dict (name, description, type, example, command, domain)
- Tier 0 (confidence > 0.85): auto-matched via LanceDB vector search
- Tier 1 (0.60–0.85): LLM-confirmed with one zero-shot call
- Tier 2 (< 0.60): unclassified → staged in evolution pool
- Output: `{status, openconfig_path, confidence}` (field is `openconfig_path`, NOT `standard_name`)

### create_unified_view (Phase 3)
Auto-generate normalised DuckDB VIEWs from approved schema mappings:
- Input: `command` (str), `mappings` (list of raw_key → openconfig_path dicts)
- Generates `v_unified_{command}` VIEW with TRY_CAST for type safety
- Stages as `replace_view` mutation → IngestManager applies atomically
- Output: `{view_name, column_count, sql_preview}`

### register_api_schema (Phase 4)
Parse an OpenAPI 3.x specification and classify every field:
- Input: `url_or_path` (HTTP URL or local JSON file), `domain`, `dry_run`
- Extracts fields from `components/schemas` and `paths` requestBody/responses
- Calls `classify_field` for each → stages mutation requests
- Zero new pip dependencies (stdlib `urllib.request` + `json` only)
- Output: `{fields_found, matched, llm_confirmed, unclassified, errors, staged}`

### trigger_schema_evolve (Phase 5)
Cluster unclassified fields and propose new standard names for human approval:
- Input: `domain`, `min_samples` (OPTICS density threshold, default 3)
- Uses `sklearn.cluster.OPTICS` (scikit-learn already in project deps)
- LLM zero-shot names each cluster → stages `propose_standard` mutation
- Output: `{clusters_found, proposals, skipped}`
- Approval: `olav config evolve --list / --approve <id>`

### fuzzy_map_schema
Legacy LLM-based normalisation for ad-hoc vendor data alignment:
- Input: vendor, command, raw_data (dict or list)
- Output: normalised data aligned to the baseline schema
- Config: `config/normalization_strategy.yaml`

### run_topology_sandbox
Graph-based topology analysis using NetworkX on live DuckDB views:
- Data source: `v_topo_links_clean` view
- Graph: `nx.MultiGraph` with CDP/LLDP/OSPF/BGP edges
- Algorithms: shortest_path, articulation_points, degree_centrality
- Output: nodes, edge_count, is_connected, cut_points, degree_centrality, mermaid
- Saves Mermaid diagram to `exports/network_topology.mmd`

### execute_sql
Direct DuckDB query execution with auto schema discovery:
- Auto schema discovery (no manual inspect_schema calls)
- DuckDB-specific optimisations
- SchemaContext singleton caching (5 min TTL)

### discover_view_schemas
Auto-discover and register DuckDB view schemas for the SchemaContext cache.
