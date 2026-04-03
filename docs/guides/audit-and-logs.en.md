# Audit and Logs

OLAV automatically records every Agent operation — every query, every tool call, every error — all written to the audit log. No extra configuration needed; it works out of the box.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-08 | `olav log list/errors` queries the audit log | ✅ v0.10.0 |
    | C-L2-12 | Multi-user concurrent audit with no write conflicts | ✅ v0.10.0 |
    | C-L2-22 | `olav log export trajectory/sft/atif` exports training data | ✅ v0.10.0 |
    | C-L2-40 | `olav log show <run-id>` displays the complete event sequence | ✅ v0.10.0 |
    | C-L2-45 | Audit database can be queried directly via DuckDB | ✅ v0.10.0 |

---

## Why It Matters

- **Traceability**: When something goes wrong, you can trace back to the exact operation and timestamp
- **Compliance**: Meets audit requirements for SOC2, ISO 27001, and more (audit logs include SHA256 tamper-proof checksums)
- **Improvement**: Analyze failure patterns to make the Agent better over time
- **Training**: Export operation trajectories for fine-tuning your own LLM

---

## View Recent Operations

```bash
olav log list
```

```
Recent Audit Runs (last 24h):

  [2026-04-03 15:35:52] 7f2693b8  completed     agent=core
  [2026-04-03 15:35:25] 2e31144b  completed     agent=config
  [2026-04-03 15:34:20] 4e314755  completed     agent=quick
  [2026-04-03 02:33:26] 37d3dc7f  running       agent=config
```

Each record includes: timestamp, run ID (8 characters), status (`completed` / `running` / `error`), and the Agent that executed it.

## View Details for a Specific Operation

```bash
olav log show 7f2693b8
```

Using the 8-character run ID from `olav log list`, you can view the complete details of that operation: which tools were called, the LLM's reasoning process, inputs and outputs, error messages, and more.

## View Errors Only

```bash
olav log errors              # errors from the last 24 hours
olav log errors --hours 168  # errors from the last 7 days
```

---

## Export Training Data

OLAV's audit logs are not only for retrospective review — they can also be exported as LLM training data, turning your operational experience into AI knowledge.

```bash
olav log export trajectory --output ./exports/train/ --no-encrypt
```

```
✓ Trajectory export complete
  Runs scanned: 19
  Samples exported: 17
  Runs rejected: 0
  Runs deduped: 0
```

Export output:
```
exports/train/
├── trajectory.jsonl      ← Tool call trajectories (one JSON line per run)
├── manifest.json         ← Export metadata
├── stats.json            ← Statistical summary
└── rejected_runs.json    ← Excluded runs and reasons
```

### Three Export Formats

| Format | Command | Use Case |
|--------|---------|----------|
| Tool-use trajectory | `olav log export trajectory` | Fine-tuning tool-calling models (recommended) |
| SFT chat | `olav log export sft` | Supervised fine-tuning (conversation format) |
| ATIF trace | `olav log export atif` | Structured instruction format |

Common parameters: `--hours N` (export the last N hours; default is all), `--output DIR` (output directory), `--min-score N` (quality filter, 0.0–1.0).

---

## Audit Database Schema

All audit data is stored in `.olav/databases/audit.duckdb` (DuckDB format, supports concurrent writes) and contains four tables:

| Table | Records | Purpose |
|-------|---------|---------|
| `audit_runs` | Summary for each run: run ID, start/end time, status, Agent, user | View operations overview |
| `audit_tool_calls` | Details for each tool call: tool name, input parameters, output results, duration (ms) | Analyze which tools are most used and slowest |
| `audit_events` | Raw event stream: LLM messages, tool returns, error details | Deep troubleshooting |
| `audit_messages` | Conversation messages: user inputs, Agent replies | Review interaction history |

!!! tip "Sensitive information is automatically redacted"
    Audit logs automatically detect and redact passwords, API keys, PSKs, and other sensitive credentials — you don't need to worry about secrets being stored in plaintext.

---

## Query Audit Data Directly with SQL

If you need more flexible analysis, you can query the audit database directly with DuckDB:

```python
import duckdb
con = duckdb.connect(".olav/databases/audit.duckdb")

# Which tools are called most frequently?
con.execute("""
  SELECT tool_name, COUNT(*) as calls
  FROM audit_tool_calls
  GROUP BY tool_name
  ORDER BY calls DESC
""").fetchall()
# [('execute_sql', 617), ('run_python_code', 187), ('search_knowledge', 165), ...]

# Recent failed runs
con.execute("""
  SELECT run_id, agent_id, start_time
  FROM audit_runs
  WHERE status = 'error'
  ORDER BY start_time DESC
  LIMIT 10
""").fetchall()
```

---

## Multi-User Scenarios

When a team shares the same project directory, everyone's operations are written to the same audit database. Each record is tagged with a `user_id`, making it easy to distinguish who performed which operation.

```
.olav/databases/audit.duckdb   ← Project-level shared; DuckDB ensures concurrency safety
```
