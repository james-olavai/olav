# ADR-0010: Fine-Tuning Graduation Line — Stop Compensating in Code for Model Deficiencies That Will Be Fine-Tuned Out

**Status**: Accepted
**Date**: 2026-05-10
**Round**: Post R-VERTICAL-SLICE governance

## Context

OLAV runs on local small models (gemma4:31b, qwen3.6:27b class). Through
rev 200–310 we accumulated 10+ patches in code, prompts, and middleware
specifically to compensate for known small-model deficiencies — wrong
tool selection, hallucinated tool names, infinite loops on duplicate
calls, refusal to delegate, dropped halves of compound chains, and
abuse of thinking budget under nothink. ADR-0009 codified the data-layer
principles that emerged from this work; this ADR addresses the
**second-order question** raised once OLAV's roadmap committed to a
fine-tuned gemma4 model: **which of those patches are structural, and
which are temporary scaffolding that should be removed once fine-tuning
lands?**

Without an explicit graduation line, the system prompt + middleware
keeps accreting "be careful, small model" rules indefinitely.
Each rule adds context tokens, code paths, and confusion about why a
behavior exists. By rev 310 the netops orchestrator system prompt was
~30% rules about *how the LLM should behave* rather than *what the
task is*.

The fine-tuned gemma4 (planned) is the right tool to teach the model
correct tool-selection, naming, dispatching, and chain-following. Once
it lands, every prompt-level reminder of those becomes redundant.

This ADR draws a line: **what we keep regardless of model strength,
and what we mark as `# FT-CRUTCH` for removal when the fine-tune
graduates.**

## Decision

### The four-layer optimization framework

OLAV's correctness is built in this stack, in this order:

```
Layer 1  Multi-agent orchestration         ┐  Structural — independent
Layer 2  Progressive discovery (data)      ├  of model strength.
Layer 3  Memory injection (context)        ┘  Always retained.
Layer 4  Fine-tuning                       ┘  Treats: hallucination,
                                              wrong-tool selection,
                                              loops, dispatch refusal,
                                              chain truncation.
```

**Layers 1–3 are not subject to graduation.** They exist because they
are correct architecture (typed tools, deterministic writers,
discovery from real data, intent-keyed memory). They benefit a
fine-tuned model exactly as much as a stock one.

**Layer 4 absorbs the work that prompt-level patches were doing.** Once
a fine-tuned gemma4 demonstrates ≥80% accuracy on a target behavior,
the corresponding Layer-4 patch graduates: it is removed from code,
prompts, and middleware.

### The fine-tuning graduation line

We acknowledge the following deficiencies of stock gemma4:31b nothink
as **model-class problems, not architectural problems**:

1. Wrong tool selection driven by surface-level keyword match
2. Hallucinated tool / agent names not in the registered set
3. Repeated identical calls (cycles, "鬼打墙")
4. Refusal to delegate — LLM tries to do sub-agent work itself
5. Compound-chain truncation — "X then Y" produces only X
6. Misuse of thinking budget under nothink (writing 100-line free-form
   Python and timing out)

These are the deficiencies fine-tuning is expected to address. The
patches we have added to compensate are listed in
**dev_docs/00. issues.md ISSUE-ARCH-41** and tracked there as
candidates for graduation.

### Rules for new work (effective immediately)

**Rule 1 — Don't add new Layer-4 patches.** If you observe a model
behavior bug that would be addressed by any of the six deficiencies
above, do NOT add a new prompt rule, middleware filter, alias table
entry, or hard gate. Instead:

  a. Capture the failing transcript as a fine-tune training case
  b. If functionality breaks meanwhile, file a Layer 1–3 issue (data
     quality, missing context, missing structural enforcement)
  c. Only as a last resort: add a temporary patch tagged
     `# FT-CRUTCH: <one-line description of the model deficiency>`
     and append it to the ARCH-41 graduation list

**Rule 2 — Layer 1–3 fixes are always in scope.** Hardcoded interface
names, default subnets, coupled supported-intent constants, missing
pre-checks, and undocumented inputs (see ARCH-30 through ARCH-40)
are NOT FT-CRUTCH candidates. They are bugs or design gaps. A fine-
tuned model cannot fix them. Fix in code.

**Rule 3 — PR review must answer the layer question.** Every PR
description must say which layer the change belongs to, and Layer-4
changes must additionally justify why fine-tuning is not the right
fix.

### Graduation procedure

Per FT-CRUTCH, when the fine-tuned model is available:

1. Measure baseline: run the relevant evaluation suite (e.g. V2
   chapters, boundary scenarios, CAB E2E) **with the patch in place**
2. Remove the patch on a feature branch
3. Re-run the same suite **with the fine-tuned model and patch
   removed**
4. Pass criteria: ≥80% on the metric the patch was protecting AND no
   regression on adjacent chapters
5. If pass: land the removal commit, mark the FT-CRUTCH `[DONE]` in
   ARCH-41 with the date, accuracy number, and removal commit SHA
6. If fail: keep the patch, file the failure case as additional
   training data for the next fine-tune iteration

### What "Layer 4 patch" looks like (illustrative)

| Pattern | Example |
|---|---|
| Prompt rule listing forbidden tool / agent names | `❌ task("quick-query") — never existed` |
| Middleware that intercepts duplicate tool calls | per-tool `_call_counts` dict with budget envelope |
| Alias table mapping likely typos to real names | `_SEMANTIC_ALIASES["analyse"] → "ops-analyze"` |
| Hard retry gate enforcing argument shape | `emit_tcf` 6-retry content gate |
| "Did you mean?" suggestions | `_best_match` substring matcher |
| Removal of capability the LLM kept misusing | dropping `execute_sql` from orchestrator to force `task()` |
| Long enumeration of "DO NOT do X" hints | orchestrator.md "never `ls/glob/olav_recall_memory before delegate`" |

### What is NOT a Layer 4 patch (illustrative)

| Pattern | Why it stays |
|---|---|
| Inspector `@tool` wrapping NetworkX | Type-system schema enforcement; benefits any model |
| `submit_change_plan` structured tool | Type-B deterministic-writer contract (ADR-0007) |
| `tcf_writer` deterministic YAML rendering | LLM should never produce production YAML |
| Discovery mode (`devices=[]` → enumerate) | Sensible API for callers that don't know names |
| `scope_guard` business-boundary refusal | Policy decision, not model competence |
| Auto-generated `network_overview.guide.yaml` | Layer-2 entry point; data, not prompt rules |
| Hybrid `thinking_mode` (orchestrator on, sub off) | Correct allocation of inference cost |
| Cross-vendor SQL views (UNION over per-vendor raw) | Architectural separation; vendor-add stays SQL |

## Consequences

### Positive

- **PR scope clarity** — every change is consciously placed in a layer.
  Layer-4 changes get challenged; Layer 1–3 changes get supported.
- **Bounded scope of fine-tuning** — we stop hoping fine-tuning will
  fix data quality or hardcoded constants. Fine-tuning is targeted
  at the six listed deficiencies.
- **Removable scaffolding** — every FT-CRUTCH carries removal criteria.
  When the fine-tune lands we know exactly what to take out and how
  to verify.
- **Stops orchestrator-prompt sprawl** — explicit ban on adding
  new "DO NOT" rules.
- **Empirically grounded** — FT-CRUTCH list is built from actual
  observed gemma4:31b nothink failures (rev 200–310 commits), not
  speculation.

### Negative / Costs

- **Discipline cost on PR review** — every reviewer must ask the
  layer question. Initially feels like ceremony.
- **Some short-term breakage cost when the fine-tune underperforms**
  — until graduation a patch is removed, behavior may regress on
  whatever scenario the patch was protecting. Mitigated by the
  pass-criteria gate (≥80% + no adjacent regression).
- **Risk of misclassifying** — a patch we think is FT-CRUTCH might
  turn out to be Layer 1–3 in disguise (e.g. a missing data field).
  Counter-mitigation: ADR-0009 rule "audit data layer first" still
  applies; if removing a patch reveals a data gap, the gap is the
  real fix.

### Follow-ups

- **dev_docs/00. issues.md ARCH-41** maintains the live FT-CRUTCH
  list with `# FT-CRUTCH:` source-code grep being the
  source-of-truth for "what's still scaffolding".
- **Governance test** (proposed): assert that every `# FT-CRUTCH:`
  comment in the codebase has a corresponding entry in ARCH-41's
  table.
- **Fine-tune training set assembly** — when a Layer-4 issue is
  refused under Rule 1, the captured transcript should land in a
  shared `fine-tune-cases/` directory (path TBD) ready for the
  next training run.
- **Future ADR** — when fine-tuning lands, an ADR-00XX should
  retrospectively update this one's status to `Accepted, partially
  superseded by <fine-tune deployment ADR>` and document which
  FT-CRUTCH actually graduated.

## Relationship to prior ADRs

- **Extends ADR-0009** — Data quality > prompt engineering. ADR-0009
  said "fix the data". ADR-0010 says "and don't compensate for
  model deficiencies in prompts either, because that's
  fine-tuning's job".
- **Compatible with ADR-0007** (Python-first tools) — typed
  deterministic helpers stay regardless of fine-tune state.
- **Compatible with ADR-0008** (SkillsMiddleware-first) — script
  contracts are Layer 1, not FT-CRUTCH.

## Appendix — Initial FT-CRUTCH inventory (2026-05-10)

These ten patches (full descriptions in ARCH-41 table) are the
initial graduation list. The list is maintained in
`dev_docs/00. issues.md`, not here, so it can grow without rewriting
this ADR.

1. `sub_agent_dispatch.guide.yaml` ❌ hallucinated-name blocklist
2. Per-tool `_call_counts` duplicate-call budget envelope
3. orchestrator.md long "DO NOT" rule list
4. `delegate_tool.py:_best_match` "did you mean" suggester
5. `delegate_tool.py:_SEMANTIC_ALIASES` typo/old-name mapping table
6. Three-layer tool whitelist redundancy (SKILL.md + Patch D'
   enforcement + AGENT.md tools list)
7. emit_tcf 6-retry content-correctness hard gate
8. AutoRecall keyword-match boost for exact tool-name mentions
9. Removal of `execute_sql` from netops orchestrator (forced delegation)
10. compound_chain_workflow detailed scaffold guide

Each is currently working as designed. None should be removed
**before** the fine-tune lands and graduates them.
