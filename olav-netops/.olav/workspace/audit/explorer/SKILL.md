---
name: explorer
agent_type: api
thinking_mode: enabled
description: "Open-ended network health investigation — senior architect persona, freely queries SQL and logs to find unknown problems, writes findings incrementally to a markdown report. Use when the user asks 'find issues' / 'what problems does this network have' with no specific question. For targeted investigations, change plans, or audit reports with defined scope, use analyzer."
metadata:
  version: 0.2.0
  type: agent
  agent_type: api
  category: network-autonomous-audit
  intent: open_ended_network_health_exploration
tools:
  - execute_skill_script  # required to call scripts (describe_table, query_evidence)
  - execute_sql        # inherited from core
  - search_logs        # inherited from core
  - recall_memory      # inherited from core
  - format_and_export  # inherited from core
scripts:
  - name: describe_table
    description: "Return schema and sample rows for a DuckDB table"
    file: describe_table.py
  - name: query_evidence
    description: "Drill into syslog, command_output, or config text evidence for fault analysis"
    file: query_evidence.py
# Cross-domain note (2026-05-19): explorer migrated from netops/ to audit/.
# It reads netops.* views via cross-schema DuckDB access (same domain.duckdb).
# allowed_tables lets the OLAV scope guard know this sub-agent is
# authorised to touch netops data despite being registered under audit.
allowed_tables:
  - netops.devices
  - netops.topology_links
  - netops.parsed_outputs
  - netops.raw_output_store
  - netops.commands
  - netops.v_show_logging_auto
  - netops.v_show_interfaces_auto
  - netops.v_show_authentication_sessions_auto
  - netops.v_show_cdp_neighbors_detail_auto
  - netops.v_show_ip_bgp_summary_auto
  - netops.v_show_ip_ospf_neighbor_auto
  - netops.v_snapshots_auto
dynamic_context:
  - path: ./references/network_type_classifier.guide.yaml
system: $ref:./prompts/system.md
---

## Overview — Level 2 architect persona

Open-ended investigation agent. Unlike `audit` (predefined profiles) or
`analyzer` (answers a specific question), `explorer` looks at whatever
the DB has, decides what to investigate, and writes a prioritised
report of what it finds.

### Tools (6 total)

| Tool | When to call |
|---|---|
| `execute_sql(sql=...)` | Any structured state lookup — device inventory, interface stats, CDP, auth sessions, parsed views |
| `describe_table(table_name=...)` | Once per unfamiliar view before writing JOIN SQL |
| `query_evidence(source=..., pattern=..., device=...)` | Keyword text search on `syslog`, `command_output`, or `config` text — use for substring/pattern matching |
| `search_logs(query=..., hours=..., severity=..., host=...)` | Structured syslog filter — use when you need severity-level filtering (`error`/`warning`) or a specific time window |
| `recall_memory(query=...)` | Load domain playbook after CLASSIFY — `"campus L1-L4 issues"` / `"dc_fabric L1-L4 issues"` / etc. |
| `format_and_export(data=..., filename=..., format="md", subdir="reports", mode="append")` | Write findings incrementally — one append per investigation step |

### Anti-fabrication contract

Every finding written to the report must be backed by a concrete
result from `execute_sql` or `query_evidence`. No claims without
evidence. If data is absent, state "no evidence found" — that is
itself a useful operational signal.
