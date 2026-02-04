# OLAV Project Context

## Overview
OLAV (Orchestrator Language Agent Virtuoso) is a network query assistant that translates natural language to SQL queries against network device snapshots stored in DuckDB.

## Key Components
- **DataGateway**: DuckDB-based snapshot query engine (`.olav/data/snapshots.duckdb`)
- **QueryAgent**: ReAct agent using DeepAgents framework for intelligent query execution
- **Orchestrator**: SubAgent-based meta-agent for routing and coordination
- **SubAgents**: Specialized agents (database, cli, analysis)

## Architecture
- **Cache System**: SQLiteCache for LLM calls, Fuzzy/Exact matching for Guard/Intent
- **Persistence**: DuckDB for checkpointer/store (session state and aliases)
- **Skills**: Loaded from `.olav/skills/*/SKILL.md` frontmatter

## User Preferences
<!-- Agent will learn and update this section -->
- Preferred output format: Markdown tables (Rich for TTY, plain Markdown for pipe)
- Language: Chinese (Simplified) for interaction, English for code

## Device Aliases
<!-- Agent maintains device alias mappings in DuckDBStore -->
<!-- Example: R1 = router-core-01, SW1 = switch-access-01 -->

## Common Query Patterns
<!-- Agent learns frequently asked queries -->
