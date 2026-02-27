---
name: audit-auditor
description: "Rule Executor — Runs audits and formats markdown compliance reports"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: network-audit
  intent: rule_execution_compliance_checking
tools:
  - list_audits               # Dedicated: List available audit configs
  - run_audit                 # Dedicated: Full audit pipeline (map→reduce→analyze→report)
  - get_current_datetime      # Dedicated: Accurate timestamps
  - diff_snapshot             # Dedicated: Compare snapshots during analysis
  - schema_inspector          # Dedicated: Inspect DuckDB schema for debugging
  - execute_sql              # Dedicated: Query parsed_outputs from DB
system: $ref:./prompts/system.md
---

## Overview

The Rule Executor runs audits and formats compliance reports.

## Use Cases

1. **Run Audit**: Execute full audit pipeline (map→reduce→analyze→report)
2. **List Audits**: Show available audit configurations
3. **Diff Analysis**: Compare snapshots during root cause analysis
4. **Schema Debug**: Inspect DuckDB schema for debugging

## Audit Pipeline

1. **Map**: SSH collection via `take_snapshot` → raw files + DuckDB parsed_outputs
2. **Reduce**: Config-driven rule engine → findings
3. **Analyze**: LLM per-device root-cause + global correlation
4. **Report**: Markdown with findings table, per-device analysis, cascade chain

## Output

- Findings table with severity (critical/warning/info)
- Per-device analysis with root cause
- Cascade chain showing impact propagation
- Recommendations for fixes
