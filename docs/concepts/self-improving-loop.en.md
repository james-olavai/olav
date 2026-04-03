# Self-Improving Loop

One of OLAV's most distinctive designs: it learns from its own mistakes. Every operation -- whether successful or failed -- is recorded and becomes the basis for improvement.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-24 | `/trace-review` analyzes failure patterns and writes to LanceDB memory | ✅ v0.10.0 |
    | C-L2-22 | `olav log export trajectory` exports training data | ✅ v0.10.0 |

---

## Core Idea

Traditional AI assistants make a mistake and may make the same mistake again next time. OLAV is different -- it transforms errors into "lessons learned," stores them in a vector memory store, and automatically references them the next time a similar situation arises, avoiding the same pitfalls.

```
Daily use of OLAV
    |
Audit log automatically records: every tool call, error, token consumption, user question
    |
Run /trace-review or let Config Agent analyze
    |
LLM identifies failure patterns -> extracts "constraints" (what to avoid next time) -> writes to LanceDB memory
    |
Future queries search memory before execution -> Agent automatically avoids known pitfalls
```

---

## /trace-review: One-Click Improvement Trigger

Run in interactive mode (TUI):

```bash
olav        # Start interactive mode
/trace-review
```

What it does:

1. Queries `audit.duckdb` to find failed runs within the last **7 days**
2. Analyzes the tool call trajectory and error messages for each failure
3. Sends failure records in batches to the LLM to extract **constraints** (what to do next time)
4. Writes the learned constraints to the **LanceDB** vector memory store
5. On every subsequent run, the Agent searches the memory store before acting, automatically avoiding known issues

Example output:

```
Analyzed 12 failed runs

Extracted constraints (written to LanceDB memory):
  1. execute_sql must use schema.table format, not just the table name
  2. list_services tool does not accept arguments, passing arguments causes TypeError
  3. When user says "recent errors", look at the past 48h instead of 24h
```

These constraints are **persistent** -- even after restarting OLAV, the Agent will automatically query these memories on the next run.

---

## Triggering Analysis via Config Agent

In addition to `/trace-review`, you can also use natural language to have the Config Agent analyze:

```bash
olav --agent config "analyze recent failures and suggest improvements"
olav --agent config "which tools are called the most?"
olav --agent config "which queries can't be handled by current tools?"
```

---

## What Gets Improved

| Aspect | Improvement Method |
|--------|-------------------|
| **Tool usage errors** | Constraints written to LanceDB, Agent automatically queries and avoids them before each run |
| **Routing blind spots** | Config Agent identifies query types that no Agent can handle well |
| **System prompts** | Based on failure patterns, Config Agent suggests modifications to AGENT.md |
| **Tool descriptions** | If routing is inaccurate, the `@tool` function's docstring may not be clear enough |

---

## Audit Data -> Training Data

Beyond self-improvement, audit logs can also be exported as LLM training data. Successful operation trajectories can be used to fine-tune your own models:

```bash
olav log export trajectory --output ./exports/train/
```

Converts successful runs into tool call trajectory JSONL format, suitable for fine-tuning tool calling capabilities.

See [Audit and Logs ->](../guides/audit-and-logs.md) for details.

---

## Design Philosophy

OLAV treats prompt engineering as an **operations problem** -- driven by real usage data rather than adjusted by intuition.

- Every failure is evidence
- Every constraint is a lesson
- The workspace grows more aligned with your actual usage patterns over time

You don't need to be a prompt engineering expert. Just use OLAV normally, and it will improve on its own.
