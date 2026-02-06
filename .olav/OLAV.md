# OLAV Project Context

## Overview
OLAV (Orchestrator Language Agent Virtuoso) is a network query assistant that translates natural language to SQL queries against network device snapshots stored in DuckDB.

## Architecture
- **Framework**: DeepAgents (LangGraph-based multi-agent orchestration)
- **Cache System**: SQLiteCache for LLM calls (transparent prompt-level caching)
- **Persistence**: DuckDB for checkpointer/store (session state management)
- **Skills**: Loaded from `.olav/skills/*/SKILL.md` frontmatter
- **SubAgents**: Declarative specialist configurations (defined below)

---

## SubAgent Registry
<!-- Orchestrator dynamically loads SubAgent references from this section -->
<!-- Actual tools and prompts are defined in each agent's .olav/skills/*/SKILL.md -->

### query
```yaml
---
name: query
agent_skill: network-query
description: Database query specialist - SQL queries, schema inspection, data discovery
capabilities:
  - Device inventory queries (devices table)
  - SQL execution on network database
  - Schema inspection and data discovery
  - Automatic LLM caching for repeated queries
enabled: true
---
```

### expert
```yaml
---
name: expert
agent_skill: network-expert
description: CCIE-level Network Expert for complex troubleshooting and root cause analysis
capabilities:
  - Multi-domain expertise (R&S, DC, SP, Security)
  - Topology-aware analysis with dynamic scope expansion
  - Cross-layer correlation (L1-L7)
  - Knowledge base and case study integration
  - Professional-grade diagnosis reports
enabled: true
---
```

### cli
```yaml
---
name: cli
agent_skill: network-cli
description: CLI command execution specialist for network operations
capabilities:
  - Network command execution
  - Configuration changes
  - Device interaction
enabled: true
---
```

### analysis
```yaml
---
name: analysis
agent_skill: network-analysis
description: Network analysis specialist with health diagnostics and anomaly detection
capabilities:
  - Network health diagnostics and anomaly detection
  - Performance analysis and optimization recommendations
  - Root cause analysis for network issues
  - Real-time CLI verification when needed
enabled: true
---
```

### inspection
```yaml
---
name: inspection
agent_skill: network-inspection
description: Network inspection specialist for batch device health checks and audits
capabilities:
  - Multi-layer health checks (L1-L4)
  - BGP peer status audits
  - Interface error analysis
  - Security baseline validation
  - Automated inspection reports
enabled: true
---
```

---

## User Preferences
<!-- Agent will learn and update this section -->
- Preferred output format: Markdown tables (Rich for TTY, plain Markdown for pipe)
- Language: Chinese (Simplified) for interaction, English for code

## Device Aliases
<!-- Agent maintains device alias mappings in DuckDBStore -->
<!-- Example: R1 = router-core-01, SW1 = switch-access-01 -->

## Common Query Patterns
<!-- Agent learns frequently asked queries -->
