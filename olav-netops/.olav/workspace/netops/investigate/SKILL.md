---
name: investigate
# R-VERTICAL-SLICE 2026-05-09: sub-agent uses no-think for
# fast tool execution; orchestrator handles planning.
thinking_mode: disabled
description: "Evidence drilldown for fault analysis. Searches recorded text — syslog, command output, config — for a pattern on a device. Returns matched lines with timestamps. Use when user asks why/log/syslog/具体输出/为什么/故障定位."
metadata:
  version: 1.0.0
  type: agent
  category: network-operations
  intents:
    - log_search
    - fault_localization
    - evidence_drilldown
tools:
  - query_evidence
  - format_and_export
allowed_tables:
  - netops.raw_output_store
static_context_mode: on_intent
system: $ref:./prompts/system.md
---

## investigate — read-side evidence drilldown

Single-purpose sub-agent.  One @tool: ``query_evidence``.  Three sources
selected via the ``source`` arg.

R-VERTICAL-SLICE Step 1 (2026-05-09, dev_docs/74): orchestrator routes
"why / log / syslog / 故障定位" intents here so analyze stays focused
on graph/state queries.  Sub-agent has 1-2 tools — small models cannot
mis-pick.

## Workflow

1. Identify the source from the question:
   * "syslog / log / event / error / warning" → ``source="syslog"``
   * "show output / what does X say / running-config" → ``source="command_output"`` or ``"config"``
   * "config has / configured / interface X is" → ``source="config"``
2. Identify pattern (a substring like "BGP", "OSPF dead", "NATIVE_VLAN").
3. Optionally narrow by device + time_range / snapshot.
4. Call ``query_evidence(...)`` once.
5. Reply with the matched rows.  If no matches, say so honestly.
6. For multi-page reports (>20 matches user wants persisted):
   ``format_and_export(data=md, filename="evidence-<id>",
                       format="md", subdir="evidence_reports")``

## Hard rules

1. NEVER fabricate log lines.  If ``query_evidence`` returns
   ``matches: []``, the answer is "no recorded evidence matches" —
   not a hypothesis.
2. NEVER pick the wrong source.  When unsure between command_output
   vs config, call **both** in two tool calls and merge.
3. NEVER plan changes / write CLI / emit TCF.  This sub-agent only
   reads.  Redirect to ``sim`` for changes.
4. Pattern is required.  No empty-string searches (would dump 14k
   syslog rows).

## Anti-patterns

* ❌ "Probably an OSPF dead-interval issue" without calling
  ``query_evidence(source="syslog", pattern="OSPF dead")`` first
* ❌ Calling ``query_evidence`` 5+ times with slight variations —
  pick the right pattern + source on call 1, max 2 calls total
* ❌ Returning truncated raw rows with no summary
