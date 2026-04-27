# ADR-0008: SkillsMiddleware-First tool architecture; supersedes ADR-0007 sandbox-Python sub-recommendation

**Status**: Accepted
**Date**: 2026-04-27
**Round**: Round 91 (R91 close-out reflection on ADR-0007)

## Context

ADR-0007 (Python-first tool architecture) introduced the rule
"default to Python in `olav.core.<domain>`, MCP `@tool` only when
justified" with a 4-condition escalation test. R91 executed
4 fold steps (ops/lab, audit/auditor CUT 1, ops/analyze,
audit/curator) — 20 tools moved to `olav.core.<domain>` Python
modules called from `run_python_simulation`.

After Step 4 the user asked:

> deepagents 不是支持基于 skill scripts 的 tool 自动注入么，
> 为什么还要 MCP？

Investigating the question revealed an architectural blind spot
in ADR-0007:

* **deepagents has a native `SkillsMiddleware`**
  (`deepagents.middleware.skills.SkillsMiddleware`). It loads
  `SKILL.md` files via configurable backends, validates their
  frontmatter (name / description / `allowed_tools`), and injects
  skill **metadata only** into the LLM system prompt — full SKILL.md
  content is read on demand (progressive disclosure).

* **OLAV has never enabled `SkillsMiddleware`.** `agent.py:400`
  calls `create_deep_agent(tools=orchestrator_tools, ...)` with
  an explicit BaseTool list assembled by OLAV's own
  `discover_tools()` scan.

* **OLAV explicitly bypasses `SubAgentMiddleware` "to avoid
  FilesystemMiddleware injection"** (agent.py:348). This is a
  deliberate security policy — sub-agents don't get free shell exec.

The cost of OLAV's current model, surfaced by the audit:

* Every `@tool` wrapper costs ~150-300 prompt tokens (docstring +
  Pydantic args schema). 14 tools = ~3200 tokens permanent
  overhead per agent invocation.
* ADR-0007's `run_python_simulation` fold reduces this by sharing
  one sandbox tool across many helpers (~200 tokens fixed).
* But skill-script-via-execute would cost **0 per-tool tokens** —
  scripts are referenced by absolute path inside SKILL.md (which
  is loaded on demand, not in the base prompt).

The gap:

| Pattern | Per-tool prompt overhead | Execution |
|---|---|---|
| `@tool` wrapper (legacy) | 150-300 tokens | langchain in-process |
| sandbox-Python (ADR-0007) | 0 (one shared sandbox tool ~200 tokens) | sandbox subprocess |
| **SkillsMiddleware + execute** | **0 (`execute` tool fixed; SKILL.md read on demand)** | **subprocess via execute** |

ADR-0007's rule was right about reducing per-tool overhead, but
its **prescribed mechanism** (sandbox Python) is a midpoint, not
the terminus. The full deepagents-native path is cheaper.

## Decision

**1. SkillsMiddleware is the default mechanism for exposing
deterministic Python helpers to agents.** SKILL.md frontmatter
declares the helpers; scripts live in `<skill>/scripts/` (or
analogous); the agent's prompt cost is bounded by SKILL.md
metadata (one line per skill) plus one fixed `execute_skill_script`
tool entry.

**2. We do NOT enable `FilesystemMiddleware` wholesale.** OLAV's
existing decision to avoid free `execute(command=...)` for sub-agents
stands. Instead, we ship a controlled `execute_skill_script` tool
(`olav.core.skill_runner`) that:
* Accepts `(skill_name, script_name, args_json)` — not arbitrary
  commands.
* Resolves script paths via the SkillsMiddleware's loaded skill
  registry.
* Refuses to execute anything outside the registered skill
  directory.
* Captures stdout/stderr/return-code into the audit log.

This keeps the security guarantees while unlocking the prompt
savings.

**3. R91 work is preserved as a Python API library, not deleted.**
`olav.core.cab`, `olav.core.lab`, `olav.core.auditor`,
`olav.core.curator`, `olav_netops.core.diff` continue to exist as
shared business logic. R92 skill scripts import them; the agent
no longer needs `run_python_simulation` for these helpers.

**4. The MCP-escalation rule (ADR-0007 §"Decision") remains valid
but updated.** Operations escalate to MCP `@tool` only when:
* **Sandbox-external privilege.** CLAB REST API auth, prod SSH
  (scrapli), privileged docker. Subprocess scripts can't do
  these without exposing credentials.
* **Cross-call shared in-process state.** A handle, connection,
  or cache that must persist across multiple invocations within
  a single agent turn. Subprocess scripts can't share heap.
* **Critical audit row.** Every invocation must produce a row in
  `audit.duckdb.audit_tool_calls` — the controlled
  `execute_skill_script` already audits, so this category
  shrinks to "needs *named* audit rows, not generic ones".
* **Real-time streaming output to the agent.** Subprocess output
  is captured and returned at completion; tools that need to
  stream tokens to the agent mid-execution stay MCP.

The 4-condition test from ADR-0007 still applies — but condition
(2) "sandbox-external write target" is removed because skill scripts
write within the workspace freely.

**5. Migration path (R92):**

* R92.0: this ADR. Deprecate ADR-0007's sandbox-Python sub-rule
  (the broader Python-first rule stays).
* R92.1: ship `olav.core.skill_runner.execute_skill_script` MCP
  tool. Add SkillsMiddleware to platform (opt-in via agent
  metadata `skills_middleware: true`). Convert ops/lab as
  proof-of-concept (1 script, in-vivo verify).
* R92.2: convert ops/lab fully (6 scripts). Measure prompt
  savings vs R91 sandbox-Python.
* R92.3: convert audit/auditor (CUT 1+2 in single pass — the
  redesign-deferral from R91 dissolves under the new pattern).
* R92.4: ops/analyze, audit/curator.
* R92.5: orchestrators (ops, core) — these are smaller; tail.

## Consequences

### Positive

* **Per-agent prompt savings escalate.** R91 saved
  ~3600 tokens; R92 expected to save another ~3000-4000 tokens
  (the `run_python_simulation` overhead × N agents that no
  longer need it for their fold targets). Total
  ~6500-7500 tokens of permanent prompt cost reclaimed.
* **Aligns with deepagents native idiom.** Future deepagents
  features (SkillsMiddleware enhancements, skill marketplace,
  remote skills) become available without bespoke OLAV
  re-implementation.
* **Cleaner mental model.** `SKILL.md` becomes the source of
  truth for "what this agent can do"; scripts are
  self-documenting; the LLM tool list shrinks to genuinely
  privileged operations.
* **Subprocess isolation for free.** Each script run is a fresh
  Python process; no cross-call state leaks. (Sometimes this is
  a feature; sometimes a constraint — see Negative.)

### Negative / Costs

* **Subprocess startup latency.** Each script run pays ~200-500ms
  Python startup. For tight loops of small operations, this is
  expensive vs in-process import. Mitigation: scripts that need
  to do many small operations should batch within a single run.
* **No shared in-memory cache across calls.** Each script is a
  fresh process. Mitigation: persistent state goes to DuckDB /
  workspace files.
* **Args/output serialisation friction.** Args are CLI-style
  (string-shaped); output is stdout (parseable to dict). Less
  ergonomic than direct Python call. Mitigation: scripts use
  `json` for args + stdout.
* **R91 fold work was a stepping stone, not the terminus.** The
  sandbox-Python `run_python_simulation` workflow built up over
  R91 will be partially supplanted in R92. Not wasted (the
  Python helpers stay) but the agent-side calling convention
  changes.
* **Migration cost ~3-4 days.** Equivalent to R91; the second
  half of the same architectural debt.

## Alternatives considered

* **Stop at ADR-0007 (sandbox-Python is good enough).** Rejected:
  measurable token savings of going one step further; aligns
  with deepagents idiom; simpler operationally (no need to
  maintain `run_python_simulation` semantics for non-sandbox
  use cases).

* **Adopt `FilesystemMiddleware` wholesale.** Rejected: violates
  OLAV's deliberate security stance against free `execute()` for
  sub-agents. The controlled `execute_skill_script` tool gives
  90% of the benefit without breaking that policy.

* **Keep `run_python_simulation` as the universal helper-call
  vehicle.** Rejected: pays sandbox subprocess cost on every
  call AND a ~200-token sandbox-tool overhead. Strictly
  dominated by the skill-script path for non-sandbox-needing
  helpers.

## Reference

* `dev_docs/00 § ISSUE-DEEPAGENTS-SKILLS-MIDDLEWARE-NOT-USED` —
  the audit that surfaced the gap.
* ADR-0007 (`docs/adr/0007-python-first-tool-architecture.md`) —
  the predecessor; its broad rule stays, only the
  sandbox-Python sub-recommendation is superseded.
* `deepagents.middleware.skills` — upstream API.
* `deepagents.middleware.filesystem` — the `execute` tool that
  OLAV deliberately does not expose; ADR-0008's
  `execute_skill_script` is a controlled subset.
