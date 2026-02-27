---
name: config-discovery
description: "Schema Alignment — Fuzzy mapping for multi-vendor normalization and topology generation"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: system-administration
  intent: schema_alignment_topology_generation
tools:
  - fuzzy_map_schema         # Dedicated: LLM-based schema translation for multi-vendor
  - generate_topology         # Dedicated: Generate topology_links from normalized tables
  - execute_sql              # Dedicated: Query parsed_outputs and normalized tables
system: $ref:./prompts/system.md
static_context:
  - path: ./references/BASELINE_SCHEMA.md
---

## Overview

The Discovery Subagent handles schema alignment and topology generation.

## Use Cases

1. **Fuzzy Schema Mapping**: Translate vendor-specific output to Cisco baseline
2. **Topology Generation**: Build topology_links from normalized CDP/LLDP data

## Tools

### fuzzy_map_schema
Multi-vendor schema normalization:
- Input: Raw parsed output from any vendor (Huawei, Juniper, Arista)
- Output: Standardized schema based on device category (Routing, Firewall, Wireless)
- Configuration: Managed via `config/baselines.yaml`
- Discovery: Automatically falls back to database schema if baseline is missing
- Caching: Saves mappings to `schema_mappings` table for reuse

### generate_topology
Build topology from normalized data:
- Physical links: From CDP/LLDP neighbors
- Logical links: From BGP/OSPF adjacencies
- Deduplication: Bidirectional edge normalization

## Workflow

1. Execute `take_snapshot` to collect raw data
2. Use `fuzzy_map_schema` to normalize vendor-specific output
3. Use `generate_topology` to build topology_links
4. Query results with `execute_sql`
