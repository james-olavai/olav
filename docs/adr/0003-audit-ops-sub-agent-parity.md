# ADR-0003: Audit/ops sub-agent count parity

**Status**: Accepted
**Date**: 2026-04-18
**Round**: Round 29
**Related issue**: ARCH-21 C (rev 151, see `dev_docs/00. issues.md`)

## Context

v0.18.1 canonical top level is four agents: `audit`, `core`, `ops`,
`services`. Their sub-agent counts are visibly asymmetric:

| Top-level | Sub-agents | Count |
|---|---|---|
| `audit/` | `auditor`, `learner` | 2 |
| `core/` | `writer`, `admin`, `api_query`, `db_query`, `remote` | 5 |
| `ops/` | `analysis`, `diff`, `probe`, `lab`, `devops`, `infra` | 6 (Sprint 3 will collapse to ≤4) |
| `services/` | (none — flat, 4 tools at top level) | 0 |

Sprint 3 explicitly plans further ops consolidation:

- Step C: `ops/analysis + ops/diff → ops/analyze` (5→4)
- Step D (lite done Round 18, full pending): `ops/probe + ops/lab → ops/collect`

And the v0.18.1 spec (rev 151) proposed:

- B.1 collapse `ops/analysis + diff → analyze` (above)
- B.2 rename `audit/learner → audit/curator`

Open question: is the asymmetry (audit:2 vs ops:6, soon ops:4) a bug, a
symptom of incomplete consolidation, or a reflection of genuine domain
structure?

## Decision

**The asymmetry is legitimate and reflects domain structure, not
incomplete work. We commit to `sub-agent count = count of distinct
workflows`, not `sub-agent count = aesthetic parity`.**

### Audit — 2 sub-agents is correct

`audit/` is a **profile-driven single-flow domain**: draft a profile →
execute it → render a report. Two sub-agents decompose that flow
cleanly:

- `auditor/` — Phase 1 map (run SQL/LanceDB queries) + Phase 2+3 reduce
  (LLM renders segmented report). Deterministic; exactly two tool calls
  from the orchestrator.
- `learner/` — schema discovery, TextFSM template auto-learn, trace
  pattern analysis. Reads failures, extracts patterns, writes new
  templates/recipes.

Each sub-agent has its own system prompt, its own tool set, and
non-overlapping responsibilities. Collapsing them into one would blur
"execute known profile" and "learn from failure" — two fundamentally
different operating modes.

**v0.18.1 spec B.2 (learner → curator rename)** is a rename, not a
merger. `curator` may take on broader "schema + trace + memory index"
curation scope, but it replaces `learner` rather than merging with
`auditor`. Count stays at 2.

### Ops — up to 4 sub-agents is correct

`ops/` is a **cross-vendor network operations domain** that is
genuinely multi-modal:

- `analyze/` (post-Sprint-3 C; merges current `analysis + diff`) —
  theoretical analysis (routing sim via networkx sandbox) and
  historical comparison (snapshot diffs)
- `collect/` (post-Sprint-3 D full; merges `probe + lab`) — live data
  acquisition: active probes (ping/traceroute) + lab validation
  (ContainerLab CAB gate)
- `devops/` — code-generation workflows (backup scripts, import
  scripts from snapshot data)
- `infra/` — NetBox / InfluxDB / service-registry reads/writes

Each sub-agent represents a distinct operator mental mode (what am I
trying to understand vs. predict vs. change?). Collapsing further would
force the orchestrator to re-route based on arbitrary keyword
disambiguation inside one giant prompt.

### Services — 0 sub-agents is correct

`services/` is a **flat 4-tool surface**: `register_service`,
`deploy_service`, `stop_service`, `api_request`. Adding sub-agents would
inflate the prompt with no workflow separation. Flat is right when
tool count ≤ ~5 and tools share a common mental model.

### Core — 5 sub-agents is a separate question

Core's sub-agents (`writer`, `admin`, `api_query`, `db_query`,
`remote`) exist for platform reasons (tool namespacing, permission
gating). ARCH-21 A / Sprint 3 Step E ("core ≤7 tools") is about
*tools on core itself*, not sub-agent count. Out of scope for this ADR.

### General rule

Future sub-agent proposals must justify with **distinct-workflow
evidence**. A sub-agent proposal must answer:

1. What operator question does this agent uniquely answer?
2. Which existing agent's tools does it duplicate?
3. Would a keyword-disambiguated router inside an existing agent serve
   the same need?

If (2) is non-empty or (3) is "yes", reject.

## Sub-agent tool count allowlist

Default target per "distinct workflow count": **≤5 tools** per sub-agent.
Exceptions must be documented here and pinned by
`tests/governance/test_v018_1_spec_guardrails.py::_TOOL_COUNT_EXCEPTIONS`.

Accepted exceptions (as of Round 35):

| Sub-agent | Tools | Justification |
|---|---|---|
| `audit/auditor` | 12 | Profile Authoring (6 tools merged from audit-designer in Round 17 Step B) + execution engine (map_engine, render_report, anomaly_engine, baseline_engine, incident_engine, render_report_linter). Dual-mode workflow — one of this ADR's motivating examples. |
| `ops/lab` | 10 | ContainerLab CAB validation requires the full lifecycle: deploy_lab / destroy_lab / exec_on_node / save_lab_config / deploy_and_push_lab / push_node_config / create_srl_links / fix_srl_topology + run_python_simulation symlink. [ADR-0005](0005-probe-to-collect-rename-lab-stays-standalone.md) kept lab standalone rather than merging with probe → collect specifically because the merged agent would have exceeded this cap. |

New exceptions require an ADR (this one or a successor) + allowlist entry
added in the same PR. `test_tool_count_exceptions_cite_adr_or_round`
enforces the citation.

## Consequences

### Positive

- The audit/ops count difference has a written rationale — future
  contributors asking "shouldn't audit have more?" have a pointer
- Sprint 3 post-consolidation ops count (4) is the committed
  steady-state, not a way-point
- The "distinct-workflow evidence" criterion is cite-able for future
  sub-agent proposals

### Negative / Costs

- Some contributors may still find the asymmetry unusual; this ADR is
  a defense but not a silencer
- `core/` sub-agent count (5) is not justified here — a separate ADR
  would be needed if challenged

### Follow-ups

- **Sprint 3 Step C** — `ops/{analysis,diff} → ops/analyze` merge is
  pre-authorized by this ADR (reducing "theory + history" ambiguity)
- **Sprint 3 Step D full** — `ops/{probe,lab} → ops/collect` is
  similarly pre-authorized
- **ARCH-21 B.2** — `audit/learner → audit/curator` rename documented
  here as a rename (not a merger). **Executed in Round 34** — see
  `tests/governance/test_b2_learner_to_curator_rename.py` for the pin.
- **Related ADRs**:
  - [ADR-0002](0002-repo-boundary-ownership.md) — boundary rules
  - [ADR-0004](0004-new-top-level-agent-extension-policy.md) —
    new top-level agent policy (sibling decision to this sub-agent one)
- **Governance pin**: `tests/governance/test_v018_compliance.py` +
  `test_v018_1_spec_guardrails.py` lock the canonical 4-top-level set;
  no pin on sub-agent count (it's a design guideline, not a hard cap)
