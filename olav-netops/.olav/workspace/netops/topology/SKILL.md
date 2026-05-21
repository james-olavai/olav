---
name: topology
agent_type: api  # skip TodoListMiddleware (NETOPS sub-agents are tool-execution, not plan-and-iterate)
# R-VERTICAL-SLICE 2026-05-09: sub-agent uses no-think for
# fast tool execution; orchestrator handles planning.
thinking_mode: disabled
description: >
  Network topology queries + LLM-assisted recipe discovery. Built-in: BGP /
  OSPF / CDP-LLDP / L2. Extension path: declare new protocols in
  ~/.olav/config/topology.yaml — agent drafts a YAML recipe on first query
  and freezes it for reuse. No Python-code generation, no sandbox.
tools:
  - execute_skill_script
scripts:
  - name: query_topology
    description: "Query BGP / OSPF / L2 topology views and return a typed TopologySnapshot"
    file: query_topology.py
  - name: discover_recipe
    description: "LLM-assisted recipe discovery for a new protocol from raw_output_store samples"
    file: discover_recipe.py
  - name: save_recipe
    description: "Validate recipe YAML, dry-run against current snapshot, UPSERT to view_recipes"
    file: save_recipe.py
  - name: rebuild_views
    description: "Pure SQL rebuild of topology views for one or all protocols (no LLM)"
    file: rebuild_views.py
  - name: list_recipes
    description: "List available topology recipes (built-in vs user, with active status)"
    file: list_recipes.py
references:
  - path: ./references/INTENT_FORMAT.md
  - path: ./references/RECIPE_FORMAT.md
  - path: ./references/SUPPORTED_BUILTIN.md
metadata:
  version: 1.0.0
  category: network-operations
  intents:
    - topology_query
    - relationship_discovery
    - recipe_management
---

## Overview

`topology` is a data-access skill: it answers "what relationships exist?"
queries (BGP sessions, OSPF adjacencies, CDP/LLDP L2 links) without ever
running LLM code. Each query returns a typed `TopologySnapshot` Pydantic
model (canonical state, vendor-preserved interface names).

## When to load references

- User edits `~/.olav/config/topology.yaml` or asks about the format → load
  `references/INTENT_FORMAT.md`
- Agent needs to draft a new recipe for an unknown protocol → load
  `references/RECIPE_FORMAT.md`
- User asks "what's supported out of the box?" → `references/SUPPORTED_BUILTIN.md`

## Discovery flow (only when user adds a new protocol)

```
user adds `- bfd` to topology.yaml
      │
      ▼
query_topology("bfd") — no recipe in view_recipes yet
      │
      ▼
discover_recipe("bfd", "cisco_ios")
      │  scans raw_output_store for commands matching %bfd%
      │  samples parsed_data keys
      │  prompts LLM: "draft a recipe YAML per RECIPE_FORMAT.md"
      ▼
save_recipe(yaml_text) — validates + dry-run + UPSERT view_recipes +
                        writes recipes/user/bfd_cisco_ios.yaml
      │
      ▼
rebuild_views("bfd") — pure SQL generates v_bfd_sessions_auto
      │
      ▼
query_topology("bfd") — returns data, zero LLM forever after
```

## Key invariants

1. Recipes are **YAML data**, not Python code — no sandbox, no AST allowlist
2. Canonical form is **declared by recipes** (SQL `CASE` in view_builder), not inferred at runtime
3. Built-in recipes ship with the wheel; user recipes live in
   `~/.olav/config/recipes/user/` (never committed to olav-netops repo)
4. Every frozen recipe has a file and a DB row — agents may grep either
5. Pipeline (netops_init / take_snapshot) calls `build_all_views` directly
   and never needs an agent; skill tools are for interactive use
