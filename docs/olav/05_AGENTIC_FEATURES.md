# Agentic Features & Self-Improving Loop

OLAV is not a static query tool—it is a **self-improving agentic system**. Every interaction generates structured trace data that feeds back into the agents' future behavior, closing the loop between execution, observation, and learning.

---

## 🧠 What Makes OLAV "Agentic"?

A truly agentic system must do more than answer questions. It must:

1. **Observe** — record what happened during every run
2. **Reason** — analyze patterns across multiple runs
3. **Learn** — extract reusable constraints from failures
4. **Adapt** — inject learned constraints into future reasoning

OLAV implements all four. The architecture below shows how they connect:

```
User Query
    │
    ▼
CLI Entry Point
    ├── AuditEventRecorder  ──────────────────────────────────▶ audit.duckdb
    ├── SemanticRouter.route(recorder) → routing_decision event ──▶
    │
    ▼
Agent Execution (deepagents framework)
    └── AuditCallbackPlugin (LangChain hooks)
            ├── on_llm_end        → llm_usage (tokens_in/out)
            ├── on_tool_start/end → tool_call_started/completed
            └── on_tool_error     → tool_call_failed
                                            │
                                            ▼
                                      audit.duckdb
                                            │
                          ┌─────────────────┼──────────────────┐
                          │ (trigger)        │                  │
                    take_snapshot      daily cron          /trace-review
                          │                 │                  │
                          └─────────────────┼──────────────────┘
                                            ▼
                                  trace_learner (background agent)
                                    ├── Step 1: read failed runs
                                    ├── Step 2: read error events
                                    ├── Step 3: LLM extracts constraints
                                    └── Step 4: write → LanceDB memory[audit]
                                                          │
                                                          ▼
                                                 GuardrailInjector
                                                          │
                                                          ▼
                                            injected into system prompt
                                                  on next run  ◀────────┐
                                                          │              │
                                                          └──────────────┘
                                                       closed loop
```

---

## 🔁 The Four Agentic Layers

### Layer 1 — Observation: Audit Trace Collection

Every agent run produces a structured trace in `audit.duckdb` via the `AuditCallbackPlugin` and `AuditEventRecorder`. No hardcoded write logic lives inside agents—all collection is done through LangChain lifecycle hooks.

| Event Type | Trigger | What It Captures |
|---|---|---|
| `run_start` / `run_end` | CLI entry/exit | `run_id`, `agent_id`, `status`, `start_time`, `end_time` |
| `user_input_received` | User types query | Raw query text |
| `routing_decision` | `SemanticRouter.route()` | `routing_method`, `matched_agent`, `confidence_score` |
| `llm_request_started` | LLM call begins | `model_name`, message count |
| `llm_usage` | LLM call ends | `tokens_in`, `tokens_out` |
| `semantic_cache_hit` | Cache lookup | `distance`, cached agent name |
| `tool_call_started` / `tool_call_completed` | Tool execution | tool name, inputs, outputs |
| `tool_call_failed` | Tool error | tool name, error message |
| `run_error` / `run_cancelled` | Unhandled exception / Ctrl-C | error payload |

All events are written **synchronously** (no fire-and-forget) to prevent data loss.

---

### Layer 2 — Routing: Semantic Intent Matching

Before any agent runs, OLAV classifies the user's intent using `SemanticRouter`:

```
User Query ──▶ embedding vector ──▶ LanceDB similarity search
                                          │
                      ┌───────────────────┴────────────────────┐
               score ≥ threshold                         score < threshold
                      │                                         │
            semantic routing                          LLM fallback routing
            (milliseconds)                            (cheap model, ~1s)
                      │                                         │
                      └───────────────────┬────────────────────┘
                                          │
                              routing_decision event → audit.duckdb
```

**Three routing methods** are recorded, enabling downstream analysis of routing quality:

| `routing_method` | Description |
|---|---|
| `semantic` | Matched via LanceDB embedding similarity above threshold |
| `semantic_cache` | Cache hit from `SemanticCache` — no LLM call needed |
| `llm_router` | LLM fallback — used when semantic confidence is too low |

---

### Layer 3 — Learning: `trace_learner` Background Agent

`trace_learner` is a **background agentic tool** that runs independently of user interactions. It consumes the trace data produced by Layer 1 and extracts reusable knowledge.

**Trigger mechanisms (three paths):**

| Trigger | When | How |
|---|---|---|
| `take_snapshot` hook | After each inventory sync | Stage 2 of `take_snapshot.py` calls `trace_learner` |
| Daily cron | 03:00 every day | Registered by `python olav-netops/scripts/netops_init.py` into `~/.olav/cron.tab` |
| User-initiated | On demand | `/trace-review` slash command in the interactive CLI |

**The four-step learn cycle (`_run_learn_cycle`):**

```python
# Step 1 — Query failed runs from audit.duckdb
failed_runs = SELECT * FROM audit_runs
              WHERE status IN ('error', 'cancelled')
              AND start_time >= NOW() - INTERVAL hours DAY

# Step 2 — Fetch error event details
events = SELECT * FROM audit_events
         WHERE run_id IN (...) AND event_type IN ('tool_call_failed', 'run_error')

# Step 3 — LLM analysis: extract failure patterns as constraints
constraints = LLM.invoke(
    "Given these failures, extract 1-5 reusable constraints as JSON array..."
)

# Step 4 — Write constraints to LanceDB long-term memory
for constraint in constraints:
    store_failure_memory(store, description=constraint, scope="global")
```

The full cycle is **fully injectable** (db_path, llm, store all accept test doubles), making it TDD-friendly and environment-portable.

---

### Layer 4 — Adaptation: GuardrailInjector

The constraints written to `LanceDB memory[category=audit]` by `trace_learner` are automatically retrieved by `GuardrailInjector` on every subsequent agent invocation.

```python
# GuardrailInjector runs before every agent call
guardrails = store.similarity_search(query, category="audit", k=5)

# Constraints are prepended to the agent's system prompt:
system_prompt = base_prompt + "\n\n## Learned Constraints\n" + guardrails
```

This means **the agent becomes measurably smarter after each failure** — without any model fine-tuning, without manual prompt engineering, and without a deployment cycle.

---

## 🛠️ Interactive Agentic Commands

### `/trace-review` — On-Demand Learning

Run the full `trace_learner` cycle immediately from the interactive CLI:

```
olav> /trace-review
olav> /trace-review hours=24
olav> /trace-review hours=168 limit=100
```

Output includes:
- Summary table: completed runs / failed runs / constraints learned
- List of extracted constraint texts

### `/trace-review` Parameters

| Parameter | Default | Description |
|---|---|---|
| `hours` | `168` (7 days) | Look-back window for failed runs |
| `limit` | `50` | Maximum number of failed runs to analyze |

---

## ⚙️ Automated Setup: NetOps Bootstrap

Running the netops bootstrap script performs the cron registration step that automatically schedules `trace_learner` to run daily:

```bash
python olav-netops/scripts/netops_init.py
```

```
# OLAV trace_learner — daily at 03:00
0 3 * * *  cd /path/to/project && uv run olav --agent config "run trace_learner()"
```

Properties of the cron registration:
- **Idempotent**: checks for existing entry before writing; safe to re-run the bootstrap
- **No root required**: writes to `~/.olav/cron.tab` (user-owned)
- **Non-blocking**: cron registration failure prints a warning but does not abort the bootstrap

---

## 📊 Observability: Querying Trace Data

All trace data is queryable via `olav log` or the `execute_sql` tool — no separate dashboard required.

```sql
-- Agent success rate (last 7 days)
SELECT agent_id,
       COUNT(*) AS total,
       ROUND(100.0 * SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS success_pct
FROM audit_runs
WHERE start_time >= NOW() - INTERVAL 7 DAY
GROUP BY agent_id;

-- Average latency per agent
SELECT agent_id,
       ROUND(AVG(DATEDIFF('ms', start_time, end_time)), 0) AS avg_latency_ms
FROM audit_runs WHERE status = 'completed'
GROUP BY agent_id;

-- Token usage by day
SELECT date_trunc('day', timestamp) AS day,
       SUM(CAST(json_extract_string(payload, '$.tokens_in')  AS INTEGER)) AS tokens_in,
       SUM(CAST(json_extract_string(payload, '$.tokens_out') AS INTEGER)) AS tokens_out
FROM audit_events WHERE event_type = 'llm_usage'
GROUP BY 1 ORDER BY 1;

-- Recent tool failures
SELECT timestamp, agent_id,
       json_extract_string(payload, '$.tool') AS tool,
       json_extract_string(payload, '$.error') AS error
FROM audit_events
WHERE event_type = 'tool_call_failed'
ORDER BY timestamp DESC LIMIT 20;
```

---

## 🗺️ Feature Status

| Feature | Location | Status |
|---|---|---|
| `AuditCallbackPlugin` LangChain hooks | `plugins/callbacks/audit.py` | ✅ Complete |
| `on_llm_end` token capture | `plugins/callbacks/audit.py` | ✅ Complete |
| `SemanticRouter` routing audit | `core/router.py` | ✅ Complete |
| `SemanticCache` cache hit audit | `core/memory/__init__.py` | ✅ Complete |
| CLI call site wired to `route_query()` | `cli/main.py` | ✅ Complete |
| `trace_learner` Steps 1-4 full cycle | `config/sync/tools/trace_learner.py` | ✅ Complete |
| NetOps bootstrap cron registration | `olav-netops/scripts/netops_init.py` | ✅ Complete |
| `/trace-review` slash command | `cli/main.py` + `cli/commands/trace_review.py` | ✅ Complete |
| `analyze_logs` querying `audit.duckdb` | `config/system/tools/analyze_logs.py` | ✅ Complete |
| User feedback rating `feedback` (1-5) | CLI / API endpoint | ⬜ Planned |

---

## 📁 Key Source Files

| File | Role |
|---|---|
| `src/olav/plugins/callbacks/audit.py` | LangChain hook collector |
| `src/olav/core/audit_recorder.py` | `AuditEventRecorder` write interface |
| `src/olav/core/router.py` | `SemanticRouter` + `route_query()` |
| `src/olav/core/memory/guardrails.py` | `GuardrailInjector` + `store_failure_memory()` |
| `.olav/workspace/config/sync/tools/trace_learner.py` | Background learn cycle |
| `src/olav/cli/commands/trace_review.py` | `/trace-review` command logic |
| `olav-netops/scripts/netops_init.py` | Cron registration for `trace_learner` |
| `.olav/databases/audit.duckdb` | Append-only trace store (SSOT) |
