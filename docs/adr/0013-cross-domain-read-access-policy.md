# ADR-0013: Cross-domain sub-agent read-access via allowed_tables

**Status**: Accepted
**Date**: 2026-05-20
**Round**: Post-R-AGENT-HIERARCHY (FINDING-08 from dev_docs/86)

## Context

`audit/explorer` is the first sub-agent registered under one domain (`audit`)
that explicitly reads data from another domain's tables (`netops.*`). Its
`SKILL.md` carries an `allowed_tables` field that enumerates the tables it
may query.

This access pattern is structurally correct — the audit domain legitimately
needs to inspect network state when generating compliance findings — but it
establishes a precedent with no written policy on:

- When cross-domain data access is acceptable
- Whether cross-domain *write* access is ever permitted
- How the OLAV scope guard enforces `allowed_tables` at runtime
- What governance steps are required to grant a new cross-domain read grant

Without a policy, future sub-agents may silently add broad `allowed_tables`
grants (or skip the field entirely and rely on ambient DB access), undermining
the domain-boundary contract that makes individual agents auditable.

## Decision

### 1. Read-only cross-domain access is permitted under explicit grant

A sub-agent registered under domain `A` may read data from domain `B`'s tables
when **all three** of the following hold:

1. `SKILL.md` carries an explicit `allowed_tables` list naming each table
   (no glob patterns; no wildcard grants)
2. The cross-domain read serves a documented purpose that cannot be served
   by a same-domain alternative (e.g. audit/explorer reading `netops.devices`
   because the audit domain has no device inventory of its own)
3. The grant is reviewed in the PR that introduces it; the PR description
   references this ADR

### 2. Cross-domain write access is unconditionally forbidden

No sub-agent may insert, update, or delete rows in another domain's tables.
Cross-domain writes are permitted only through the owning domain's own `@tool`
functions (which carry their own audit logging and validation).

The rationale: a write from a non-owning agent bypasses the owning domain's
validation, audit trail, and schema migration discipline. There is no exception
to this rule.

### 3. The scope guard enforces allowed_tables at tool invocation time

`execute_sql` (and any future SQL-executing tool) checks the calling agent's
`allowed_tables` claim before executing a query. Queries against tables not in
the grant receive a `PermissionError` with the table name and calling agent
surfaced in the error message.

This is a defense-in-depth check; the first line of enforcement is code review
(criterion 1 above). The guard catches regressions if `allowed_tables` is
widened without a corresponding policy review.

### 4. Approved precedent: audit/explorer reads netops.*

`audit/explorer` is retroactively documented here as meeting all three criteria:

| Criterion | audit/explorer evidence |
|---|---|
| 1. Explicit grant | `SKILL.md allowed_tables: [netops.devices, netops.bgp_sessions, netops.interfaces, ...]` |
| 2. No same-domain alternative | Audit has no network inventory; findings require device and topology context |
| 3. PR-reviewed | Introduced with the explorer sub-agent in the R-AGENT-HIERARCHY phase |

## Consequences

### Positive

- Cross-domain data access is bounded and auditable; `allowed_tables` in
  `SKILL.md` is the single visible access-control declaration
- Write isolation is absolute: no accidental cross-domain data mutation
- Future sub-agents seeking cross-domain access have a clear procedure
  (add `allowed_tables`, cite this ADR in the PR)
- The scope guard provides runtime enforcement independent of code review

### Negative / Costs

- Sub-agents cannot perform ad-hoc cross-domain queries outside their declared
  `allowed_tables`; adding a new table requires a SKILL.md change + PR review
- The scope guard adds a small per-query overhead for table-name matching

### Follow-ups

- **Implementation**: `execute_sql` scope-guard enforcement lives in
  `src/olav/core/db_query/` — verify it is active for all SQL-executing tools
- **Governance pin**: no dedicated test today; a future governance test should
  scan all `SKILL.md` files for `allowed_tables` and assert each table name
  is owned by a recognized domain prefix
- **Related ADRs**:
  - [ADR-0002](0002-repo-boundary-ownership.md) — repo-level boundary rules
    (this ADR is the workspace / data-layer analogue)
  - [ADR-0004](0004-new-top-level-agent-extension-policy.md) — top-level agent
    extension policy (cross-domain grants require the owning domain to be a
    recognized top-level)
