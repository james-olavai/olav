# ADR-0012: Promote admin to fifth canonical top-level agent

**Status**: Accepted, supersedes ADR-0004 § "exactly four canonical agents"
**Date**: 2026-05-20
**Round**: Round post-R-AGENT-HIERARCHY (FINDING-04 from dev_docs/81)

## Context

ADR-0004 pinned `.olav/workspace/` to exactly `{audit, core, ops, services}`.
That invariant is enforced by `tests/governance/test_v018_compliance.py` and
several xfail marks in `test_v018_1_spec_guardrails.py`.

During v0.18 → v0.19 the `core/admin/` sub-agent (platform self-management:
`workspace_health`, `bulk_ingest`, `manage_cron`, `deploy_service`,
`stop_service`) grew to 9+ tools and two independent sub-agents
(`ops`, `developer`). It exceeded the core sub-agent budget by a factor of
three and its lifecycle (operator-facing platform management) was distinct
from core's query-routing role.

Rev 280 formally dissolved `core/admin/` and re-established its components
as a standalone top-level workspace. At that point five top-level agents
existed: `{admin, audit, core, ops, services}`.

ADR-0004's four-criteria approval bar was satisfied:

| Criterion | admin evidence |
|---|---|
| 1. Distinct domain | Platform self-management (health, cron, deploy, workspace edits); cannot be placed under core without re-expanding core's tool budget past ADR-0006's 7-tool cap, nor under audit (wrong concern), nor ops (network-domain) |
| 2. Non-trivial tool surface | 15 tools across 2 sub-agents (`ops`, `developer`); none are pure aliases of existing tools |
| 3. Independent lifecycle | Owns `olav admin …` CLI surface; an operator adding a new platform command doesn't touch core/audit/ops |
| 4. Governance pin completeness | `admin/AGENT.md`, sub-agent `SKILL.md` files, and `tests/governance/test_v018_compliance.py` `_EXPECTED_TOP_LEVEL_DIRS` updated atomically |

## Decision

We formally accept `admin` as the fifth canonical top-level agent.

1. `_EXPECTED_TOP_LEVEL_DIRS` in `test_v018_compliance.py` is updated to
   `{admin, audit, core, ops, services}` in the same PR (rev 280 / post-R-AGENT-HIERARCHY).
2. ADR-0004's approval criteria remain unchanged — they correctly governed
   the `admin` promotion and will govern any future proposals. The supersession
   is scoped to the "exactly four" enumeration, not the policy.
3. The xfail marks in `test_v018_1_spec_guardrails.py` that assert the old
   four-agent set (`{audit, core, ops, services}`) are kept as `_REV_259_SPLIT_XFAIL`
   for historical traceability until the spec doc is updated to v0.19.

## Consequences

### Positive

- ADR corpus is consistent with workspace state (`admin` is no longer an
  undocumented exception)
- ADR-0004's four-criteria bar is validated by a real-world promotion, making
  it a tested policy rather than a theoretical one
- Admin's distinct lifecycle (operator tooling) is formally bounded;
  future proposals to add network-admin helpers to `core/` have a clear
  rejection path ("add to `admin/` instead")

### Negative / Costs

- The "exactly four" invariant in ADR-0004 is weakened to "four plus named
  exceptions with ADR coverage"; `_EXPECTED_TOP_LEVEL_DIRS` is now the
  enforcement anchor, not the count
- Future test_v018_compliance drifts need an ADR to justify; the process
  cost is intentional but non-zero

### Follow-ups

- **Governance pin**: `tests/governance/test_v018_compliance.py::test_top_level_matches_v018_target`
  — updated to include `admin` in `_EXPECTED_TOP_LEVEL_DIRS`
- **Supersedes**: [ADR-0004](0004-new-top-level-agent-extension-policy.md) §
  "Default position: reject / exactly four agents" (criteria remain valid)
- **Related ADRs**:
  - [ADR-0006](0006-core-seven-cross-domain-tools.md) — core tool-budget cap
    that made `core/admin/` overflow untenable
  - [ADR-0004](0004-new-top-level-agent-extension-policy.md) — original policy
    whose criteria `admin` met
