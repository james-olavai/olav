# ADR-0009: Data Quality Over Prompt Engineering for Local Small Models

**Status**: Accepted
**Date**: 2026-05-10
**Round**: R-VERTICAL-SLICE closeout (dev_docs/74)

## Context

OLAV is committed to running on local small models (gemma4:31b, qwen3.6:27b
class).  Cloud-LLM-era patterns — long prompt rules, multi-step
chain-of-thought instructions, soft adherence to "you should" guidance —
do not survive long-context ReAct loops on these models.  By turn 20,
the LLM has forgotten the orchestrator prompt's compound-chain rule;
by turn 30, it hallucinates non-existent sub-agent names; by turn 40,
it loops on the same tool with pattern variations indefinitely.

The R-VERTICAL-SLICE work (Phase 0 hybrid-thinking canary → 19 commits
of unscoped chain reactions, dev_docs/74) demonstrated empirically that
the highest-ROI improvements live in the **data and tool layer**, not
in prompt engineering.  Same model, same prompt: starting state
produced "no BGP sessions" (wrong); ending state produced
"Established but Empty session, 4 ranked root-cause hypotheses with
Junos/Cisco-specific commands" (production grade).  The delta was 16
small fixes to tools, views, parsers, and memory guides.

This ADR codifies the 16 principles that emerged so future work
defaults to the right level of intervention.

## Decision

We adopt the following 16 architectural principles for OLAV local-model
work.  They are listed roughly in the order future contributors should
audit when a behavior fails.

### Tier 1 — Highest ROI: data layer

**1. Tool data quality > tool count > prompt engineering.**
   Before adding tools or rewriting prompts, audit whether the existing
   tools return honest, structured, complete data.  A small model that
   sees a clean `{state: "Established", prefixes_received: 0,
   resolved: true}` row reasons correctly; the same model facing
   `state: "0"` will misread it as "Idle" no matter how much prompt
   guidance it has.

**2. Surface every silent drop.**
   When a tool can't produce a meaningful answer for some input, it
   must say so explicitly via a structured field — never an empty
   list, never a no-op, never a `None`.  Examples:
   `unknown_devices`, `unknown_facts`, `unresolved_bgp` (later merged
   with `resolved: bool`), `validation_warnings`, `missing_snapshots`.

**3. Decode every overloaded field.**
   Don't make the LLM reason about "this column means prefixes-received
   when numeric and state-name when text".  Decode in SQL or Python and
   return separate fields: `state="Established"` + `prefixes_received=0`.

**4. Uniform error envelope.**
   `{status: "error" | "success", error_kind, message, args, ...}` —
   every tool, same shape.  LLMs trained on diverse APIs adapt better
   to one consistent error contract than three vendor-specific ones.

**5. Empty input = discovery mode, not "no result".**
   If the LLM calls `inspect_devices(devices=[])` or `inspect_routing(devices=[])`,
   return ALL devices.  Empty intent means "show me everything".  The
   alternative — returning `{}` — sends the LLM into a discovery
   retry loop.

**11. Write-time denormalisation of known dimensions.**
   Dimension data that's certain at write time (device platform, vendor,
   AS, snapshot timestamp) should be copied into fact tables, not joined
   at query time.  Cuts JOIN cost, simplifies cross-vendor views,
   preserves historical correctness.

**15. Empty results carry steering hints.**
   When a tool returns `total: 0`, include a `hint` field explaining
   what to try next: "DO NOT try synonyms, pivot to another source"
   beats 5 retried calls with pattern variations.

### Tier 2 — Tool architecture

**6. Capability-level routing for orchestrators.**
   Orchestrator decides intent → sub-agent.  Sub-agent decides which
   tool inside.  Two layers, clean separation.  Orchestrator never
   names tools; sub-agent never makes routing decisions.

**8. Cross-vendor compatibility lives in the view layer.**
   Don't write per-vendor branches in Python helpers.  UNION across
   vendor-specific raw views in a single `v_<concept>_auto` view.
   Adding a vendor is a SQL UNION arm, not a code path.

**9. Reparse without recollect.**
   When a parser is fixed, retroactively reprocess `raw_output_store`
   into `parsed_outputs`.  Don't require expensive recollection just
   because the parser changed.

**10. Circuit breaker on transient failures.**
   When a tool call fails with a connection-class error (TCP, SSH,
   timeout), cache it and fast-fail subsequent calls to the same
   target for N seconds.  Stops the LLM from paying ~30s SSH timeout
   3 times in a row.

**16. Per-tool dedup at the source.**
   Instead of a framework-level "max tool calls per query" middleware
   (high blast radius), embed a small `_call_counts` dict in each tool
   that has been observed to ramble.  After 2 identical (tool, args)
   calls, return `error_kind: duplicate_call_budget` with a "stop"
   message.  Targeted, low-risk, no impact on healthy multi-step flows.

### Tier 3 — Routing & enforcement

**5. Hard constraint > soft template.**
   "We strongly recommend X" in a prompt is a suggestion the small
   model ignores at turn 20.  Removing the alternative tool (or having
   the tool return error_kind) is enforcement that survives any
   context length.

**13. Prompt-only adherence breaks at long contexts on small models.**
   If a behavior matters for safety/correctness, do not encode it in a
   prose prompt rule.  Either a) remove the path that lets the model
   misbehave (tool whitelist), b) intercept at middleware, or c)
   embed the rule in the tool's error envelope where it's seen at
   the moment of action, not buried in an upfront system prompt.

### Tier 4 — Memory & context

**14. Memory-driven workflows + auto-generated environment context.**
   Workflow templates live as intent-keyed memory guides
   (`*.guide.yaml`) loaded by AutoRecall when relevant.  The
   orchestrator prompt is a short skeleton; the rule library can
   grow indefinitely without bloating per-turn context budget.
   Per-deployment environment context (network overview) is
   auto-generated from the DB at init/snapshot time and surfaced
   as a memory guide so the LLM starts each query with
   "you have N routers, AS X/Y, peering shape Z" — eliminating
   the discovery loop.

### Tier 5 — Reasoning capacity

**7. Hybrid thinking — orchestrator on, sub-agent off.**
   Reasoning ON for the planning role, OFF for execution.
   gemma4:31b at think=true is 9× slower per call but produces
   genuine multi-step plans; at think=false it produces clean
   tool calls.  Hybrid: orchestrator pays the reasoning cost
   (1-2 calls per query); sub-agents stay fast (5-10 calls).
   Total: 5-10× faster than think=on everywhere with planning
   quality preserved.

**12. Empty input = discovery mode** (already listed under Tier 1
   for emphasis).

## Consequences

### Positive

- **Clear audit order** — when a behavior fails, follow the tier
  list (data quality first).  This focuses energy where ROI is
  highest.
- **Vendor / parser additions become routine** — UNION arm + textfsm
  template + reparse step.  No prompt rewrites.
- **Small-model adherence improves** — not because the model got
  smarter, but because the system makes the right action the only
  action available.
- **Memory library scales** — workflow rules grow without prompt
  bloat.

### Negative / Costs

- **More disciplined error/envelope authoring** — every tool author
  must implement the uniform shape.  Up-front cost.
- **More moving parts in the data layer** — cross-vendor views,
  reparse helpers, circuit breakers, dedup caches.  Correct but more
  surface area.
- **Less prompt-level visibility** — when behavior is enforced via
  tool data shape rather than prompt rules, "why did the agent do
  X?" requires reading more code paths.

### Follow-ups

- ADR-0010 (proposed): structural enforcement for compound-chain
  workflows — should orchestrator have a middleware that blocks
  final answer until all required sub-agents have been called?
- Governance: a quality test that scans every `@tool` for the
  uniform error envelope shape (status / error_kind / message).
- dev_docs/74 closeout section — empirical results of applying
  these principles end-to-end.
- Future model upgrades (gemma5? qwen4?) should ratchet up — these
  principles ALSO apply to bigger models, just less critically.

## Appendix — Empirical evidence

The 16 principles emerged from a single session (dev_docs/74,
2026-05-09 → 2026-05-10) of 19 commits.  Each principle is tied
to a specific bug fix or improvement:

| # | Principle | Commit |
|---|---|---|
| 1 | Data quality > prompt | (whole session) |
| 2 | Surface silent drops | 9e3be39, 7ea2b40, f0e3726, 77cf7dd |
| 3 | Decode overloaded fields | 9e3be39 (state field) |
| 4 | Uniform error envelope | 77cf7dd, 1d1cc3c |
| 5 | Hard constraint > soft template | 0e4c74e (remove execute_sql) |
| 6 | Capability-level routing | 6c59ed8, 13ba367 |
| 7 | Hybrid thinking | 5a7e7a5 |
| 8 | Vendor compat in view layer | f3068a4 |
| 9 | Reparse without recollect | f3068a4 |
| 10 | Circuit breaker | 592c2aa |
| 11 | Write-time denormalisation | 3f2ec5a |
| 12 | Empty input = discovery | 4e9f9e3 |
| 13 | Prompt adherence breaks long context | 9dd181b (architectural learning) |
| 14 | Memory-driven workflows | 9dd181b |
| 15 | Empty results carry steering | 2afec9f |
| 16 | Per-tool dedup | 2afec9f |

5-scenario boundary suite at session end: all PASS on gemma4:31b
including production-grade fault diagnosis with Junos/Cisco-specific
hypothesis ranking, polite refusal of out-of-domain prompts, and
correct BLOCKED feasibility for infeasible change requests.
