# ADR-0011: LLM-first means typed APIs + structured output, not free-form code generation

**Status**: Accepted
**Date**: 2026-05-11
**Round**: post R-AGENT-HIERARCHY (Phase D + freeform_cli E2E experiment)

## Context

Two recurring questions surfaced in 2026-04 → 2026-05 work:

1. **Is the inspector pattern (typed `@tool` wrappers around NetworkX
   queries) over-engineering compared to a generic
   `run_python_simulation` sandbox?**
2. **For change-plan emission and lab translation, should we extend
   per-intent Python renderers (R89, tcf_writer) for every change
   type, or accept a model-class boundary?**

Both questions arise because OLAV calls itself "LLM-first" and there
is a temptation to interpret that as "let the LLM write whatever code
it needs". Empirical evidence over the last 6 weeks rejects this
interpretation:

- **Sandbox unworkable on 30B**: R-AGENT-HIERARCHY post-Phase-D
  found gemma4:31b nothink could not reliably compose 30-line
  NetworkX queries in `run_python_simulation`; the model hung trying
  to write the script. Replacement with 11 typed inspector tools
  pushed the matrix from ~10% to **87.5% PASS** on the same model
  (rev 236 → rev 240).
- **Markdown freeform vs structured**: 2026-05-11 sim→lab E2E
  experiment forced a side-by-side test. Markdown freeform
  `submit_change_plan` (no typed slots, just prose):
  **25min timeout + textbook 192.168.x.x hallucination** because
  gemma4 lost task-completion signal. Structured
  `submit_change_plan(intent='freeform_cli', cli_per_device={...})`:
  **6m23s clean PASS with grounded IPs**.
- **Extending per-intent Python templates is a closed-list debt**:
  R89 `_SUPPORTED_INTENTS = {"ebgp_direct"}` is the only intent the
  SRL renderer handles; tcf_writer originally had the same single-
  intent limit (commit 015a827 added freeform_cli). Adding per-
  pattern translators (static_route → SRL, ACL → SRL, ...) recreates
  the same closure problem at finer granularity.

The principle "LLM-first" is therefore ambiguous and needs a
concrete operational definition.

## Decision

We commit to the following interpretation of LLM-first:

### 1. LLM-first means typed APIs + structured output, not free-form code generation

The LLM's job is to:

- **Pick from typed tools** (inspector @tool functions, structured
  submit_change_plan, etc.)
- **Fill typed slots** in tool args (intent enum, devices list,
  cli_per_device dict, ...)
- **Compose prose for human reviewers** (rationale, summary, steps
  free-form fields — these are the LLM's analytical container, not
  load-bearing for downstream code)

The LLM's job is **not** to:

- Write multi-line Python code in a sandbox to compose queries
- Generate platform-specific CLI from scratch when no template
  applies
- Translate between vendor CLI dialects (IOS ↔ SRL ↔ Junos)

### 2. Inspector tools are the default; sandbox stays as an opt-in escape hatch

`run_python_simulation` (and similar arbitrary-code tools) remain in
the workspace tools/ directory but are **not** in default agent
tools-list whitelists. They are available when:

- An advanced user explicitly enables them for a session
- A larger-class model (e.g. ≥200B parameter cloud models) is the
  active backend and the workload would not be served by the
  inspector set
- A research / one-off analysis genuinely needs query composition
  not covered by the 11 standard inspectors

When in doubt, add a new typed inspector instead. Each inspector is
~30–100 lines wrapping a NetworkX or SQL call; this is a one-time
cost shared by all callers and all models.

### 3. Per-intent renderers are a transitional pattern, not a permanent strategy

`tcf_writer._INTENT_RENDERERS` and
`olav.core.lab.srl_render._SUPPORTED_INTENTS` will keep their
existing entries (`ebgp_direct`; the recently-added `freeform_cli`
on the writer side) but will not be expanded with additional per-
pattern translators (static_route, ACL, OSPF, MTU, …). The
freeform_cli entry on the writer side is the catch-all: any change
type sim can ground in inspector data can flow through it.

We reject:

- Adding R89 per-pattern SRL translators
- Adding R89 generic prod→SRL CLI translation (NLP problem)
- Multi-platform CLAB topology (cEOS/crpd/srl) just to make freeform
  CLI deployable on the digital twin

These are over-engineering: each adds significant code surface for
narrow extensions to the supported scope, and the bigger model path
(see §4) makes them unnecessary as model classes mature.

### 4. The 30B-class boundary is acknowledged and named

For the gemma4:31b nothink model class (and similar 30B local
models), reliable behavior empirically extends to:

- Data queries (inspect_devices / topology / routing / path /
  blast_radius / interfaces): **~90% PASS**
- Path / impact analysis: **~85% PASS**
- Drift detection, basic fault triage: **~80% PASS**
- Simple change planning for **known intents** (with grounded
  inspector data and structured `submit_change_plan` slots):
  **~80% PASS, including correct BLOCKED on data gaps**
- Compound multi-step prompts ("X then save it"): **50–67% — known
  attention-decay weakness**

For non-trivial cross-format translation (IOS ↔ SRL CLI, multi-
vendor mass changes), free-form configuration generation, and
chains > ~10 tool calls, the 30B class is unreliable. These tasks
will route to one of:

- Larger cloud model (Claude, GPT-4-class, DeepSeek V3/V4)
- Fine-tuned 30B (per ADR-0010 graduation line — for the 10–15%
  residual cases inside the supported scope)
- HITL escape hatch (see §5)

### 5. `feasibility = OK_HITL_ONLY` makes the lab boundary explicit

`submit_change_plan` accepts a third feasibility value beyond `OK`
and `BLOCKED`:

- `OK`: sim verified the change is feasible AND the lab digital twin
  can validate it deterministically (e.g. `intent='ebgp_direct'`
  reaches lab via R89 SRL renderer)
- `OK_HITL_ONLY`: sim verified the change is feasible but the lab
  digital twin cannot deterministically validate it (e.g.
  `intent='freeform_cli'` — sim emits valid prod CLI but R89 has no
  SRL translator). The TCF spec is still written, the human-readable
  plan is still emitted, but `next_step.action = 'hitl_review'` and
  the orchestrator surfaces the spec for manual prod application.
  This is **not a failure**; it is honest scope marking.
- `BLOCKED`: sim found a hard blocker (same-AS for eBGP, missing
  inspector data after 4 calls, infeasible topology, …). No spec
  emitted.

## Consequences

### Positive

- **Clear scope contract**: small-model deployments understand what
  works automatically (eBGP changes through full lab validation) and
  what requires HITL (freeform changes get full spec + plan, no lab
  validation).
- **No more closed-list debt growth**: per-intent Python templates
  cap at the current 1–2 entries; future change-type expansion uses
  the freeform_cli typed-slot path on the sim side, with HITL on the
  lab side.
- **Architecture work stops chasing model deficiencies**: future
  effort goes into broadly-useful infra (typed inspectors, memory
  guides, structured envelopes), not narrow per-intent translators.
- **Bigger-model upgrade path is clean**: when a larger backend is
  swapped in, the sandbox + memory-guided translation paths become
  available without removing any existing scaffolding.

### Negative / Costs

- Lab digital twin remains effectively eBGP-only for automated
  validation. Non-eBGP changes go through HITL, which means slower
  iteration when the user wants to validate a static route or ACL
  change in lab before prod apply.
- Some users may expect "throw any change at OLAV and it auto-
  validates"; this ADR formalizes that expectation as deferred to a
  larger-model backend (or a future R89 LLM-translation layer that
  does not exist today).

### Follow-ups

- Implementation of `OK_HITL_ONLY` in `submit_change_plan` +
  `tcf_writer.render_tcf_from_change_plan` happens in the same
  commit landing this ADR.
- ADR-0010 (fine-tuning graduation line) is preserved unchanged —
  fine-tuning targets the 10–15% residual within the supported
  scope, not scope expansion.
- ADR-0008 (SkillsMiddleware-First) is reinforced: lab-side write
  operations stay deterministic Python (skill scripts), not LLM-
  authored CLI.
- Monitoring: the `OK_HITL_ONLY` count over time is a leading
  indicator. If it grows large for a single change type, that is a
  signal the bigger-model path or a per-intent renderer becomes
  worth the cost.
