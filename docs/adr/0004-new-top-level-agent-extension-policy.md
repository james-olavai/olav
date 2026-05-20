# ADR-0004: New top-level agent extension policy

**Status**: Accepted, superseded in part by ADR-0012 (§ "exactly four agents" → five)
**Date**: 2026-04-18
**Round**: Round 29
**Related issue**: ARCH-21 D (rev 151, see `dev_docs/00. issues.md`)

## Context

v0.18.1 canonical top-level workspace is **exactly four agents**:
`audit`, `core`, `ops`, `services`. The history getting here is
instructive:

| Era | Count | What happened |
|---|---|---|
| v0.17 | 7+ top-level | `audit-auditor/`, `audit-designer/`, `config/`, `devops/`, `gitea/`, `infra/`, `ops-lab/`, etc. — ad-hoc additions over time |
| ARCH-20 Phase 1 | 4 | Seven v0.17 residual agents deleted; content migrated to sub-agent positions |
| Round 16 | 5 (transitional) | `services/` added for API integration domain |
| Round 18 Step D lite | 4 (canonical) | `ops-lab/` top-level shell removed (redundant with `ops/lab/` sub-agent) |

The `services/` addition in Round 16 passed review without an explicit
decision record. The criteria were implicit: distinct lifecycle,
dedicated tool set, warrants its own `AGENT.md` frontmatter. But
without those criteria being written down, future proposals
("observability/", "database/", "secrets/") would each start from
first principles.

Without a policy we risk v0.17-era sprawl returning. With a policy
that's too restrictive we block genuinely-distinct domains
(`services/` was legitimately out of scope for `core/` and `ops/`).

## Decision

### Default position: **reject**

New top-level agents are forbidden by default. `.olav/workspace/`
contains exactly `{audit, core, ops, services}` as of v0.18.1, pinned by
`tests/governance/test_v018_compliance.py::test_top_level_matches_v018_target`
against `_EXPECTED_TOP_LEVEL_DIRS`.

Changing that set requires an ADR (this one or a successor) + the same
governance test updated atomically.

### Approval criteria (all four must hold)

A proposed new top-level agent `X/` is approved only when:

1. **Distinct domain**: `X` cannot be naturally placed as a sub-agent
   under any existing top-level. If a skill maps to `<existing>/<X>/`
   without contortion, it becomes a sub-agent, not a top-level.
2. **Non-trivial tool surface**: `X` must advertise at least 3 tools
   that are not pure aliases/symlinks of existing tools. Symlinks for
   cross-domain reuse are fine; a top-level consisting *only* of
   symlinks fails this test.
3. **Independent lifecycle**: `X` has a distinct operator / release
   cadence / configuration surface. "Independent" means a change to
   `X` does not require coordinated edits to an existing agent's
   prompt/tools in the same PR.
4. **Governance pin completeness**: Before merge, `X/AGENT.md`,
   `X/SKILL.md`, `X/prompts/system.md`, and `X/tools/` must each have
   at least one dedicated governance test. `test_v018_compliance.py`
   `_EXPECTED_TOP_LEVEL_DIRS` is updated in the same PR.

### Approved precedent: services/

The Round 16 addition of `services/` is retroactively documented here
as meeting all four criteria:

| Criterion | services/ evidence |
|---|---|
| 1. Distinct domain | API service integrations (NetBox/InfluxDB/ContainerLab); neither core (too domain-specific) nor ops (not a network-ops task) fit |
| 2. Non-trivial tool surface | 4 tools: `deploy_service`, `stop_service`, `api_request` (3 symlinks from `core/tools/` — shared utilities), plus `register_service` (new @tool, services.yaml CRUD) |
| 3. Independent lifecycle | Owns `.olav/config/services.yaml`; ops engineer adding a new service doesn't touch audit/core/ops |
| 4. Governance pins | `tests/governance/test_services_agent.py` (14 assertions), plus references in `test_v018_compliance.py` |

### Rejection examples

To illustrate the criterion, the following hypothetical proposals are
**rejected**:

| Proposal | Reason |
|---|---|
| `database/` | Criterion 1 fails: fits as `core/db_query/` (already exists) or `ops/db/` |
| `logs/` | Criterion 1 fails: `core/tools/search_logs.py` already exists; no distinct workflow |
| `observability/` | Criterion 1 marginal, criterion 2 likely fails (1-2 tools only); prefer `core/monitor/` sub-agent |
| `writer/` standalone | Already exists as `core/writer/` sub-agent; promoting to top-level would duplicate tool surface |

### Procedure for a new top-level agent proposal

1. Write an ADR in `docs/adr/` that argues each of the four criteria
2. Add the governance tests (AGENT.md pin, SKILL.md pin, tool pins)
3. Update `tests/governance/test_v018_compliance.py`
   `_EXPECTED_TOP_LEVEL_DIRS` in the same PR
4. Run `olav refresh` to regenerate `PLATFORM.md`
5. Review ensures ADR + tests + manifest are atomic

## Consequences

### Positive

- Proliferation risk is bounded: a new top-level requires deliberate
  effort (ADR + governance tests)
- The `services/` precedent is documented; future reviewers can point
  to it as "this is the bar"
- `test_v018_compliance.py::_EXPECTED_TOP_LEVEL_DIRS` becomes a **policy
  frozen** marker, not just an enumeration

### Negative / Costs

- Adding a legitimate new domain takes longer (ADR cycle + tests)
- The 4 criteria are judgment calls; disputes will still need review
- Historical additions (v0.17 era) cannot be reasoned about with this
  policy — superseded by ARCH-20 Phase 1 cleanup

### Follow-ups

- **Governance pin**: `tests/governance/test_v018_compliance.py::`
  `test_top_level_matches_v018_target` — the runtime anchor of the
  canonical 4 agents
- **Governance pin**: `tests/governance/test_adr_discipline.py` — ensures
  this ADR doesn't drift out of existence
- **Related ADRs**:
  - [ADR-0002](0002-repo-boundary-ownership.md) — broader repo
    boundary rules
  - [ADR-0003](0003-audit-ops-sub-agent-parity.md) — sibling
    decision about sub-agent (not top-level) count
- **Amendment / supersession**: a future v0.19 or v1.0 re-org that
  changes the canonical top-level set must supersede this ADR
