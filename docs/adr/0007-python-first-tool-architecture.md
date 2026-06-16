# ADR-0007: Python-first tool architecture; MCP only when justified

**Status**: Accepted
**Date**: 2026-04-27
**Round**: Round 90 (R90 close-out + R91 governance preparation)

## Context

In the R88-A → R89 → R90 → TCF arc (commits `efe381e` through
`8eaad54`) we shipped 7 new MCP tools — `generate_clab_topology`,
`generate_srl_lab_config`, `generate_srl_rollback_config`,
`tcf_emit_from_sim`, `tcf_load_for_lab`, `tcf_record_lab_run`,
`append_validation_footer`.

After delivery, an audit (recorded in `dev_docs/00 §
ISSUE-MCP-OVER-TOOLING`) showed each of those 7 tools is
fundamentally a Python function exposed in `olav.core.cab` /
`olav.core.lab` modules. The MCP wrapper does no work beyond
bridging LangChain tool args to a Python call. The wrappers exist
for two historical reasons:

1. The first such tool (R88-A `generate_clab_topology`) was
   designed to fix a small-model failure mode where free-form
   markdown synthesis dropped the `links:` section in a CLAB
   topology yaml. Making it an MCP tool (vs. a plain Python script
   called via `execute_skill_script`) felt like the most direct
   intervention at the time.

2. Each subsequent generator (R89 / R90 / TCF) followed the same
   pattern by reflex — the mental model became "deterministic
   transformation = MCP tool" without re-examining whether MCP
   was the right surface.

The cost of this pattern, surfaced in the audit:

* **Permanent prompt overhead.** Each MCP tool's docstring +
  Pydantic args schema costs ~150-300 prompt tokens. ops-lab now
  has 14 tools listed in SKILL.md → ~3200 tokens permanent
  prompt cost on every agent invocation. For small models
  (`x-ai/grok-4.1-fast` and similar tier), that is a meaningful
  fraction of the working context budget.

* **Tool-selection error rate rises with tool count.** R89 v1's
  empty-dict-args bug (committed `37b4bb7`, fixed `a507006`) was
  partly caused by the agent struggling to discriminate among too
  many similarly-named tools and to construct the nested args
  schema. A smaller tool surface reduces both vectors.

* **Edge-case extension is more expensive in MCP.** Adding a new
  intent type (e.g. `ibgp_route_reflector`) means a new MCP tool
  file with full Pydantic schema, args validation, audit
  registration, and SKILL.md update. The Python-API equivalent is
  one new function plus an `expert_knowledge` YAML row.

The full agent-by-agent audit (also in `dev_docs/00`) shows
~30 of 71 total tools across all agents (40%+) are candidates for
migration — not just our R90 leftovers. **audit/auditor**
alone has 9 of 11 tools fitting the pattern.

`execute_skill_script` provides a controlled script execution
channel: plain Python files under `<skill>/scripts/` are called
as subprocesses with full filesystem and network access but no
persistent in-process state. The deterministic core of any tool
that doesn't need cross-call state can be expressed as a script.

> **Correction (2026-05-25)**: The original text here referenced
> `run_python_simulation` as the delivery mechanism. That tool was
> never implemented. `execute_in_sandbox` (`platform/sandbox.py`)
> exists but is used only by `netops/learner` for validating
> potentially-broken TextFSM parser code — it is not a general
> agent execution mechanism. The correct delivery mechanism for
> "Python-first" logic is `execute_skill_script` + `scripts/`.

We are committing to a default-Python rule going forward.

## Decision

**1. The default tool surface for an agent is a script file under
`<skill>/scripts/`, called via `execute_skill_script`. Discovery
guidance lives in `expert_knowledge` or `usage_guide` YAML entries.**

**2. We escalate a script to an MCP `@tool` wrapper only when
at least one of the following conditions holds:**

* **Process-external privilege with persistent state.** The operation
  requires credentials, persistent connections, or auth state that
  must survive across multiple calls within the same agent run.
  Examples: CLAB REST API session, prod-device SSH (scrapli),
  Batfish snapshot cache (`batfish_q._LOADED_SNAPSHOTS`).
* **Cross-process write target.** The operation writes to a location
  that a later in-process tool call must read from the same process
  context. Example: `save_lab_config` writes to a tmpdir that
  `deploy_and_push_lab` reads — the path is a privileged contract.
* **Critical audit.** Every invocation of the operation must
  produce a row in `audit.duckdb.audit_tool_calls`. A subprocess
  call inside a script cannot guarantee this per invocation.
  Examples: `register_service`, `record_network_event`,
  `take_snapshot`.
* **Persistent in-process state.** Tool maintains module-level caches
  or connection pools across calls (e.g. circuit breaker state in
  `execute_cli_parallel`). Scripts reset state on every invocation.

**Failing all four conditions, the operation MUST be a plain Python
script in `<skill>/scripts/`, registered in `SKILL.md` under
`scripts:` with name-form entries.**

**3. The rule applies retroactively.** Existing MCP tools that
fail the four-condition test are tagged for refactor in
`dev_docs/00 § full-agent MCP governance audit`. The R91 milestone
will fold them in priority order: ops/lab → audit/auditor →
ops/analyze → audit/curator → topology → core/* margins.

**4. New tool proposals go through this filter at design time.**
Before opening a PR that introduces a new MCP `@tool`, the author
documents which of the four conditions it satisfies. If none, the
tool ships as a Python function instead.

## Consequences

### Positive

* **Smaller per-agent prompt footprint.** Estimated ~6000-7000
  tokens of permanent prompt cost reclaimed across the agent fleet
  once the R91 governance refactor lands.
* **Better behavior on small models.** Less tool-selection
  noise, fewer Pydantic args-construction failures.
* **Cheaper extensions.** New intents become a Python function +
  YAML entry, not a new MCP tool with all its supporting
  infrastructure.
* **Cleaner governance boundary.** "MCP = touches the world"
  becomes the test of conscience. Anything else is Python.
* **Aligns with existing R87 + R88 + R89 + R90 Type B pattern.**
  Those tools' deterministic cores are already Python; this ADR
  recognises that the MCP wrappers were optional, not load-bearing.

### Negative / Costs

* **Memory recall is now load-bearing.** Agents need expert /
  usage YAMLs to discover which Python functions exist.
  Misclassified scope or weak keywords mean agents won't surface
  the guidance. R87 Phase 1.5 scoping is the foundation.
* **Script debug is slightly different from tool-call debug.** A
  failed script returns stdout/stderr from the subprocess; a failed
  tool call produces a single error envelope. Both surface errors to
  the agent, but the format differs.
* **Some discoverability is lost.** A tool list in SKILL.md is
  visible to humans reviewing config; Python-API + memory
  guidance requires reading `dev_docs` or the YAMLs. Mitigation:
  the R91 refactor will keep tools list short and documented, and
  agent-specific `references/` files can summarise the Python
  surface.
* **R91 cleanup work is real.** ~30 tools to fold across 5+
  agents, 2.5-3.5 days of engineering. We accept this cost as
  one-time.

## Alternatives considered

* **Keep MCP-everything.** Status quo. Rejected: prompt cost
  + tool-selection error rate keeps rising as we add features.
* **Auto-generate MCP wrappers from Python functions.** Tooling
  that introspects `olav.core.*` and generates @tool wrappers.
  Rejected: same prompt cost problem; doesn't help small models.
* **Per-tier rule (small models = Python-first, large models =
  MCP-everything).** Rejected: configuration sprawl; the
  Python-first rule is a strict improvement at all model sizes.

## Implementation plan

* R91.0: this ADR; CLAUDE.md note (local-only, mirroring this
  ADR's rule for live Claude Code sessions).
* R91.1: ops/lab refactor — fold the 5 tools shipped this round
  into Python API + `cab_validation_workflow.expert.yaml`.
  In-vivo verify ch4→ch5 still works.
* R91.2: audit/auditor refactor — biggest single-agent prompt
  reclaim (~1500-2000 tokens). Likely needs deeper agent
  redesign, not just tool deletion.
* R91.3: ops/analyze + audit/curator (P2).
* R91.4: topology + core/* margins (P3).
* R91.5: validate prompt-token savings on a real demo run; record
  the improvement in `dev_docs/00 § ISSUE-MCP-OVER-TOOLING`.

## Reference

* `dev_docs/00 § ISSUE-MCP-OVER-TOOLING` — full architectural
  reflection + audit table.
* `dev_docs/60 § Type B classification` — the prior pattern this
  ADR generalises.
* R88-B v1 → v5 closed-loop log (in `dev_docs/60`) — the original
  small-model adherence problem that motivated the deterministic
  generators in the first place.
* CLAUDE.md (local-only) — repeats the rule for live sessions.
