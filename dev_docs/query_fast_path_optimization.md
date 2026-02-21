# Query Fast Path Optimization

**Status**: Design / Approved  
**Author**: Design session 2026-02-22  
**Motivation**: Simple lookups ("list devices", "show BGP on R1") currently make 4 LLM calls
totalling 30–60s, plus 3–5s startup overhead on every `uv run olav` invocation.
Target: simple lookups < 1s (cache hit), < 5s (SQL cache hit), startup < 200ms.

---

## Problem: Current Latency Breakdown

### Startup overhead (every cold start)
```
uv run olav
  ↓ import langchain + langgraph + deepagents       ~1.5s
  ↓ create_deep_agent → build LangGraph StateGraph  ~0.5s
  ↓ discover_tools → importlib scan skills/*/tools  ~0.5s
  ↓ DuckDBStore.setup()                             ~0.3s
  ↓ SQLiteCache init                                ~0.2s
Total startup: ~3–5s (wasted on every invocation)
```

### Per-query LLM overhead
```
User query
  ↓  LLM 1 (~5s)   Orchestrator: "call task(olav-ops, query)"
  ↓  LLM 2 (~10s)  SubAgent:     "call execute_sql(SELECT ...)"
  ↓  Tool  (~0.1s) DuckDB:       execute SQL → JSON rows
  ↓  LLM 3 (~10s)  SubAgent:     "format rows as Markdown table"
  ↓  LLM 4 (~10s)  Orchestrator: "synthesize final response"
Total: ~35–60s for a query that could be answered in <1s
```

---

## P0 — Startup Overhead: Daemon Mode

**Priority**: P0. Eliminates 3–5s wasted initialization on every `uv run olav` invocation.

### How it works

```
olav-daemon start           # (one-time) forks background process, preloads all agents
                            # startup cost paid once, not per query

echo "list devices" | olav  # connects to daemon via Unix socket (<5ms)
olav                        # interactive mode connects to daemon instantly
```

**Protocol**: Unix domain socket at `.olav/run/daemon.sock`. CLI sends query as JSON line,
daemon responds with JSON result, display layer renders as Markdown.

### Daemon lifecycle

```bash
olav daemon start    # start daemon, prints PID
olav daemon stop     # graceful shutdown
olav daemon status   # running/stopped, uptime, query count
olav daemon restart  # stop + start
```

Auto-start: if `.olav/config/daemon.yaml` has `auto_start: true`, CLI spawns daemon on
first invocation and reuses it on subsequent calls.

### Fallback

If daemon is not running and `auto_start: false`, CLI falls back to current in-process
mode (no regression, just slower startup).

### Files

| File | Role |
|------|------|
| `src/olav/cli/daemon.py` | Daemon process: socket server + agent lifecycle |
| `src/olav/cli/cli_app.py` | CLI: try socket → fallback to in-process |
| `.olav/run/daemon.sock` | Unix socket (auto-created) |
| `.olav/config/daemon.yaml` | `auto_start`, `socket_path`, `idle_timeout` |

---

## P1 — Hybrid Cache: Exact Code Bypass + Semantic RAG Tool

### Architecture: why hybrid?

Two types of cache retrievals need different mechanisms:

| Type | Example | Safe to skip LLM? | Method |
|------|---------|:-----------------:|--------|
| Exact repeat | "list devices" asked again | ✅ Yes — hash collision impossible | Code bypass (0 LLM) |
| Similar query | "show all routers" ≈ "list devices" | ⚠️ LLM must verify | RAG tool (1 LLM) |
| Different entities | "BGP R1" vs "BGP R2" | ❌ No — same intent, different data | Never collide |

**Design principle**: Exact match needs no LLM reasoning. Semantic match requires Orchestrator
to verify the cached result actually answers the new question, and to handle entity mismatches
(R1 ≠ R2, same semantic intent but completely different data).

### Full flow

```
User query
  │
  ├─[Code] sha256(query) → result_cache   ← exact match (0 LLM, ~0ms)
  │         hit? → render & return
  │
  └──── agent.invoke()
           │
           └─[Orchestrator LLM] calls search_cache(query) FIRST  ← semantic match (1 LLM)
                    hit? → Orchestrator verifies & returns
                    miss? → task(SubAgent) → full 4-LLM path
                              │
                              └── result auto-stored in DuckDB cache
                                  (next identical query → exact code bypass)
```

### Unified cache table (DuckDB, all SubAgents)

```sql
CREATE TABLE response_cache (
    query_hash       VARCHAR PRIMARY KEY,   -- sha256(normalized_query)
    query_embedding  FLOAT[1536],           -- for VSS semantic retrieval
    query_text       VARCHAR,
    response_text    TEXT,                  -- pre-formatted Markdown output
    source_agent     VARCHAR,               -- "olav-ops" | "netbox" | "olav-audit"
    invalidation_ts  TIMESTAMP,             -- data timestamp at cache time
    cached_at        TIMESTAMP,
    hit_count        INTEGER DEFAULT 0
);
```

**Why source_agent matters**: each SubAgent has its own data freshness cycle:

```python
INVALIDATION_RULES: dict[str, Callable[[], datetime | None]] = {
    "olav-ops":   lambda: get_last_snapshot_ts(),   # 24h snapshot → 24h effective TTL
    "netbox":     lambda: get_netbox_sync_ts(),      # Netbox sync timestamp
    "olav-audit": lambda: None,                     # never cache (audit results change anytime)
}

def is_cache_valid(entry: CacheEntry) -> bool:
    rule = INVALIDATION_RULES.get(entry.source_agent)
    if rule is None:
        return False
    source_ts = rule()
    return source_ts is not None and entry.invalidation_ts >= source_ts
```

Adding `netbox` SubAgent in the future: add one line to `INVALIDATION_RULES`. No other changes.

### `search_cache` tool (registered to Orchestrator)

```python
@tool
def search_cache(query: str) -> str:
    """Search cached results from previous queries. Call this FIRST before any task delegation.
    Returns pre-formatted Markdown result if a fresh, relevant match is found, else empty string.
    """
    # 1. Exact match (belt-and-suspenders with the code-level check)
    exact = cache.get_exact(sha256(query))
    if exact and is_cache_valid(exact):
        return exact.response_text

    # 2. Semantic retrieval via DuckDB VSS
    embedding = embed(query)
    candidates = cache.get_similar(embedding, threshold=0.92)

    for entry in sorted(candidates, key=lambda e: e.similarity, reverse=True):
        if not is_cache_valid(entry):
            continue
        # Entity alignment: "BGP R1" must not answer "BGP R2"
        if entities_match(query, entry.query_text):
            cache.increment_hit(entry.query_hash)
            return entry.response_text

    return ""  # miss — Orchestrator will delegate to SubAgent
```

Orchestrator system prompt addition (`.olav/skills/olav-ops/prompts/system.md`):
```markdown
## Cache-First Protocol (MANDATORY)
Call `search_cache` as your VERY FIRST action on every user query.
Only proceed to `task` delegation if `search_cache` returns an empty string.
If `search_cache` returns a result, output it directly without modification.
```

### Auto-population: SubAgent results stored automatically

Every SubAgent result is intercepted and stored in the cache after a successful query.
No SubAgent needs to be modified — the storage happens in the Orchestrator layer.

### Cache invalidation vs. wall-clock TTL

Using snapshot timestamp instead of wall-clock TTL:

```
Wall-clock TTL of 24h:
  snapshot at 14:00 → old cache from 13:59 valid until tomorrow 13:59 ❌ (23h stale data)

Snapshot-timestamp invalidation:
  snapshot at 14:00 → all cache entries with invalidation_ts < 14:00 instantly invalid ✅
```

Rule: `is_valid = (entry.invalidation_ts >= get_last_snapshot_ts())`

---

## P2 — Direct Table Output (No LLM Formatting)

`execute_sql` returns a pre-formatted Markdown table. Orchestrator is instructed to
pass `formatted_table` through verbatim. Eliminates LLM 3 + partial LLM 4 for tabular results.

**Truncation rule**: ≤ 10 rows → full table. > 10 rows → first 10 + note.

**execute_sql return change**:
```python
# Before:
return {"rows": [...], "columns": [...], "row_count": 6}

# After:
return {
    "formatted_table": "| Name | Hostname | ...\n|------|----------|...",
    "row_count": 6,
    "truncated": False,                    # True if > 10 rows shown as 10
    "full_row_count": 6,
    "sql": "SELECT * FROM devices ...",    # debug
}
```

When to use direct vs LLM synthesis:

| Query type | Direct table | LLM synthesis |
|------------|:---:|:---:|
| Single table lookup, ≤ 10 rows | ✅ | |
| Empty result | ✅ ("No results found") | |
| Multi-SQL correlation | | ✅ |
| Root cause / analysis | | ✅ |
| > 10 rows requiring explanation | | ✅ |

---

## Implementation Plan

| Priority | Step | What | Files | Effort |
|:---:|------|------|-------|--------|
| **Cleanup** | 0 | Remove dead code: `cli_main.py` (entire file) + 3 old cache fns in `cli_app.py` | `cli_main.py`, `cli_app.py` | Small |
| **P0** | 1 | Daemon mode: Unix socket server + auto-start | `daemon.py`, `cli_app.py` | Large |
| **P1** | 2 | Unified DuckDB `response_cache` table + per-agent invalidation | new `core/response_cache.py` | Medium |
| **P1** | 3 | Code-level exact hash bypass in `_stream_response` | `cli_app.py` | Small |
| **P1** | 4 | `search_cache` RAG tool + Orchestrator Cache-First prompt | new `search_cache.py`, `system.md` | Medium |
| **P1** | 5 | Auto-store SubAgent results post-invoke hook | `agent.py` | Medium |
| **P2** | 6 | `execute_sql` direct table output (≤ 10 rows auto-truncate) | `execute_sql.py` | Small |
| **P2** | 7 | SQL generation semantic cache (DuckDB VSS) | `response_cache.py` | Medium |

**Recommended implementation order**: Cleanup → P0 (daemon) → P1.2 → P1.3 → P1.4 → P1.5 → P2.

---

## Cleanup: Redundant Code to Remove

### `cli_app.py` — 3 dead cache functions

`_init_response_cache`, `_get_cached_response`, `_set_cached_response` (lines 78–151):
- Use **wall-clock TTL** (wrong — should be snapshot-timestamp based)
- Hit **wrong DB path** (`.olav/databases/main.duckdb` not the agent DB)  
- Superseded by `ResponseCache` in Phase 2

Also remove their call sites in `main_callback` (the `_init_response_cache()` + cache get/set block around `_stream_response`).

### `cli_main.py` — entire file is dead code

`pyproject.toml` entry point: `olav.cli.cli_app:app`. `cli_main.py` was the v0.9.x entry
point, now completely superseded by `cli_app.py`. It redefines its own Typer app,
`stream_agent_response`, interactive loop — none of it is reachable at runtime.

**Verify before deleting**: `grep -r "cli_main" src/ tests/` (expect 0 imports).

---

## Expected Latency After Optimization

| Scenario | Before | After |
|----------|--------|-------|
| Cold start `uv run olav` | 3–5s startup | <200ms (daemon already running) |
| Exact repeat query | 35–60s | ~0ms (code cache bypass) |
| Similar query | 35–60s | ~5s (1 LLM via search_cache) |
| New query (first time) | 35–60s | 35–60s (unchanged, result stored for next time) |

---

## What We Are NOT Doing

- ❌ Moving `execute_sql` directly into Orchestrator (breaks SubAgent separation)
- ❌ Semantic result cache without entity alignment (R1 ≠ R2, same intent, different data)
- ❌ Removing SubAgent architecture (keeps extensibility for olav-config, olav-audit, netbox, etc.)
- ❌ Skipping LLM for semantic matches (LLM must verify entity alignment and result relevance)
