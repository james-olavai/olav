---
name: explorer
agent_type: api      # tool-execution flow, not orchestrator
# PLAN / CORRELATE / REPORT phases benefit from thinking; the system
# prompt steers the LLM to use deep thought selectively (it'll naturally
# skip thinking on routine record_finding / execute_sql tool dispatches).
thinking_mode: enabled
description: "Autonomous network audit — acts as a senior architect, explores the netops DB freely with no checklist, records findings with SQL evidence, writes a prioritised report.  Use when the user asks 'find issues' / 'audit this network' / '看看这个网络有什么问题' without a specific question."
metadata:
  version: 0.1.0
  type: agent
  agent_type: api
  category: network-autonomous-audit
  intent: open_ended_network_health_exploration
tools:
  - execute_sql               # primary query tool
  - record_finding            # external scratchpad write
  - update_exploration_run    # budget / status bookkeeping
  - start_exploration         # opens a new run_id at session start
  - promote_finding_to_audit  # graduate a finding → audit profile
                              # (dry_run=True default; operator commits)
  - task                      # delegate to sim / investigate / analyzer
  - recall_memory             # optional taxonomy / past findings
  - format_and_export         # final markdown report
dynamic_context: []           # Level 2 default — NO playbook auto-loaded.
                              # Playbooks live in ./references/ as schema-v2
                              # KB guides; the LLM pulls them on-demand via
                              # recall_memory() after classifying the
                              # network type during SURVEY.  This keeps the
                              # default prompt small and preserves the
                              # architect-persona Level-2 design (the
                              # agent CHOOSES to fetch domain knowledge).
system: $ref:./prompts/system.md
---

## Overview — Level 2 architect persona

This sub-agent embodies a senior network architect.  Unlike `audit`
(which runs predefined check profiles) or `analyzer` (which answers
specific user questions), `explorer` is **open-ended**:

* Looks at whatever data the DB happens to have.
* Decides on its own what to investigate.
* Records findings with mandatory SQL evidence.
* Stops when budget is exhausted or the network looks healthy.

See [`dev_docs/83`](../../../../dev_docs/83.%20AUTONOMOUS_EXPLORER_SUBAGENT.md)
for the full design rationale (why Level 2 over taxonomy-driven, how
the 7-second memory problem is solved, etc.).

## When to use

| User says | Right sub-agent |
|---|---|
| "What's the BGP status on R1?" | `analyzer` (single-question) |
| "Why is interface Gi0/1 down?" | `investigate` (hypothesis drilldown) |
| "Run the standard health audit" | `audit` (profile-driven) |
| **"Find any issues in this network"** | **`explorer` (this)** |
| **"Audit this fleet"** | **`explorer`** |
| **"What should I be worried about?"** | **`explorer`** |

## Anti-fabrication contract

Every finding `explorer` writes must include the SQL that proved it.
This is enforced at the DB layer (`evidence_sql NOT NULL` in
`netops.exploration_findings`).  The agent's system prompt also
forbids referencing tables or views before verifying their existence
via `information_schema.tables`.

If the LLM tries to write a finding with empty `evidence_sql`, the
`record_finding` tool raises `ValueError` — the langchain framework
turns this into a structured error response the LLM can recover from.

## Budget — bounded autonomy

Each `/explore` invocation has fixed budgets (defaults):

* **30 turns max** — counted by the orchestrator agent step counter
* **20 findings max** — `record_finding` rejects past this
* **25 minutes wall time** — checked every turn via `update_exploration_run`

These prevent the agent from going off into the weeds.  When any
budget is approaching exhaustion, the system prompt instructs the
LLM to enter the REPORT phase immediately and finalise whatever it has.
