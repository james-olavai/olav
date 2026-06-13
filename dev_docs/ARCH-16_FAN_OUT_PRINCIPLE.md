# ARCH-16 — Anti-Fan-Out Principle

**Status:** Active guidance (Sprint 0a).
**Applies to:** every `@tool` function registered across
`.olav/workspace/{core,ops,audit,ops-lab}/tools/`.
**Enforced by:** `tests/governance/test_fan_out_principle.py`.

## The Rule

Under a small-context model tier (`< 32K` usable window), a single tool
invocation MUST NOT fan out to multiple data sources and return the
fused payload in one shot. Instead:

- **Return one source, one purpose.** `execute_sql` queries SQL. `execute_cli`
  hits a device. `recall_memory` reads LanceDB. No "mega-tool" that does
  three at once.
- **Push cross-source fusion up to the orchestrator.** The agent picks
  tools in sequence; the loop is cheap, the context is expensive.
- **Delegate, don't expand.** When a multi-source task is unavoidable,
  call `olav_delegate("ops", ...)` and let the sub-agent own that
  context window. The parent only sees the summary.

## Why

Small-model (4-8B class) deployments run with an 8K context budget
(`TIER_DEFAULTS["small"]["context_budget"] = 8000`). A single fan-out
tool returning 5 × 2 KB of parsed data consumes over 60% of the window
before the model even starts reasoning. The `TokenUsageCallback` +
`ContextBudgetMonitor` pair (Sprint 0a) tracks this; ARCH-16 is the
design convention that keeps the bill manageable in the first place.

Large-tier runs (200K+ usable window) are unaffected by the budget —
the principle still applies as discipline, because the same tool code
has to run on every tier.

## Anti-Patterns (don't do this)

```python
# ❌ mega-tool that joins parsed_outputs + topology_links + raw_output_store
@tool
def retrieve_diagnostic_context(device: str) -> dict:
    return {
        "config": execute_sql(f"SELECT ... FROM netops.parsed_outputs"),
        "neighbors": execute_sql(f"SELECT ... FROM netops.topology_links"),
        "raw": execute_sql(f"SELECT ... FROM netops.raw_output_store"),
    }

# ❌ unbounded pagination
@tool
def list_all_devices() -> list[dict]:
    return api_request("netbox", path="/api/dcim/devices/", page_size=-1)

# ❌ hardcoded top_k that ignores tier
@tool
def recall(q: str) -> list:
    return store.hybrid_search(query=q, limit=20)
```

## Correct Patterns (do this)

```python
# ✅ single-source tools; orchestrator composes
@tool
def execute_sql(...) -> dict: ...

@tool
def recall_memory(query: str, top_k: int | None = None) -> list:
    # top_k=None → resolves tier default via TIER_DEFAULTS
    ...

# ✅ compact-by-default returns, `full=True` escape hatch
@tool
def diff_configs(..., full: bool = False) -> dict: ...

# ✅ multi-source work → spawn a sub-agent that owns its own context
@tool
def analyze_outage(device: str) -> dict:
    return olav_delegate(
        "ops",
        f"investigate outage on {device}: pull topology, recent changes, "
        f"and syslog. summarise root cause.",
    )
```

## Compliance Checklist

Feature teams adding a new `@tool` should confirm:

1. **Single-source**: the tool body queries at most one external system
   (one DuckDB table family, one HTTP service, one LanceDB index).
2. **Tier-aware defaults**: caps (`limit`, `top_k`, `page_size`) default
   to `tier_default(tier, "...", fallback)` instead of hardcoded ints.
3. **Compact return**: any payload > 1 KB has a `full: bool = False`
   escape hatch and a default truncation with a `"truncated": True`
   marker (see `execute_cli`, `diff_configs`, `api_request`).
4. **Docstring budget**: ≤ 20 lines; full usage lives behind
   `tool_help('<name>')`.

The `tests/governance/test_fan_out_principle.py` suite enforces
(2)–(4) automatically; (1) is reviewer judgment.

## Related

- ARCH-18 #1 — docstring trim
- ARCH-18 #2 — return-value compaction (compact default + `full=True`)
- ARCH-18 #3 — `recall_memory` tier-driven `top_k`
- ARCH-19 #C — `tool_help` lookup (detail retrieval on demand)
- Sprint 0a — `TokenUsageCallback` + `ContextBudgetMonitor` (runtime
  instrumentation that makes violations visible)
