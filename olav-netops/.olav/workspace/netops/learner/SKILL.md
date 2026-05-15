---
name: learner
agent_type: api  # skip TodoListMiddleware (NETOPS sub-agents are tool-execution, not plan-and-iterate)
# R-VERTICAL-SLICE 2026-05-09: sub-agent uses no-think for
# fast tool execution; orchestrator handles planning.
thinking_mode: disabled
# 2026-05-15: TextFSM template generation is mechanical pattern
# extraction — temp 0.0 keeps identical raw output → identical parser
# (regression detection becomes trivial; non-deterministic temp would
# mask which input change actually drove a template diff).
llm:
  temperature: 0.0
description: >
  Parser-layer learning for CLI output. Takes raw device output the
  stock ntc-templates can't parse and produces a persistent parser
  (TextFSM or Python). Single entry point `learn_commands()` is called
  by both batch (`netops_init` Stage 3.5) and interactive (`/learn_cmd`)
  paths — no more two-learner cascade.
tools:
  - learn_commands
  - cmd_learn
references:
  - path: ./references/DSL_CHOICE_RULES.md
  - path: ./references/FROZEN_LAYOUT.md
metadata:
  version: 1.0.0
  category: network-operations
  required_params:
    batch:
      - samples_list
    interactive:
      - command_text
      - device_name
---

# Command Learner

Unified parser-learning skill.  Invoked by **user-initiated**
`/learn_cmd` only — `netops_init` does **not** call this skill.
Round 72 (ISSUE-LEARNER-BATCH-CUT) removed batch auto-learning from
the pipeline; v0.21.0 deleted `olav_netops.core.auto_learn` entirely.

## Why this skill exists

Parse coverage out of the box (ntc-templates + custom TextFSM + PaC
parsers) is never 100% — vendors add commands, output formats drift
between OS versions, and some output structures ntc doesn't ship a
template for.  When `/netops_init`'s Stage 3.5 parse-coverage
classifier reports a `(platform, command)` pair as *raw-only*, it
writes it to `.olav/config/unsupported.json` and prints an
actionable invocation:

```
⚡ To enable structured queries for these, run:
    olav --agent netops_ops '/learn_cmd cisco_ios "show spanning-tree"'
```

The user runs `/learn_cmd <platform> "<command>"` when they want that
concept in SQL — the skill learns once, freezes the parser to
`.olav/templates/`, and every subsequent pipeline run picks it up
via the standard three-tier parse chain.

Router between DSLs (TextFSM vs Python) lives in
`references/DSL_CHOICE_RULES.md`.

## Entry points

### `learn_commands(samples, budget_seconds, max_workers, max_retries, allow_llm, force_relearn) -> LearnResult`

Direct function call. No agent, no NL parsing.

- **samples**: `list[{device, platform, command, raw_output}]`
- **budget_seconds**: wall-clock hard limit (default 300)
- **max_workers**: ThreadPool size (default 5)
- **max_retries**: per-command LLM attempts (default 2)
- **allow_llm**: False = frozen-only (CI / smoke install)
- **force_relearn**: ignore failure cache

Called by `/learn_cmd` (agent-facing).  Not called by `netops_init`
(pipeline); see ISSUE-LEARNER-BATCH-CUT for rationale.

### `cmd_learn` (LangChain `@tool`)

Thin wrapper for agent-side invocation. Captures raw via `_run_one`
then calls `learn_commands([single_sample])`.

## Output contract

Frozen artifacts:

| DSL | Location |
|---|---|
| TextFSM | `.olav/templates/<platform>/<cmd_safe>.textfsm` |
| Python (main) | `.olav/templates/parsers/<platform>/<cmd_safe>.py` |
| Python (quarantine) | `.olav/templates/parsers/_quarantine/<platform>/<cmd_safe>.py` |
| Failure cache | `.olav/templates/_failed_learn.json` (TTL 7 days) |

Runtime parse chain unchanged (`textfsm_parse.parse_output`):
PaC Python → custom TextFSM → ntc-templates.
