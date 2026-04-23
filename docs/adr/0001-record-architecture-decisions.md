# ADR-0001: Record architecture decisions

**Status**: Accepted
**Date**: 2026-04-18
**Round**: Round 29

## Context

OLAV's architectural decisions have, until now, been scattered across:

- `CLAUDE.md` — repo-level agent instructions and boundary rules
- `ownership_manifest.yaml` — path-level ownership
- `dev_docs/*.md` — design notes, sprint specs, boundary proposals
- `dev_docs/00. issues.md` — issue tracker with decision rationale mixed
  into matrices
- Git history and PR descriptions

That scattering has three concrete costs:

1. **Discovery**: contributors cannot find the rationale for a past choice
   without knowing which dev_doc to read. We have been reconciling 
   "is it still true?" across rounds (16-28) instead of reading a record.
2. **Precedent without record**: Round 16 added `services/` as a new
   top-level agent with no explicit decision document. Later rounds had
   to infer the approval criteria from exit conditions. ADR-0004
   addresses this by writing the policy down.
3. **Supersession is opaque**: when v0.18 migrated away from v0.17's
   7-agent sprawl, the reasoning lives in migration notes rather than
   a single "we supersede X with Y" record.

## Decision

We will record significant architectural decisions in `docs/adr/` as
[MADR](https://adr.github.io/madr/)-formatted ADRs, one file per decision,
numbered sequentially starting at `0001`.

Scope of "significant":

- Changes a boundary (repo / package / agent / tool ownership)
- Sets or changes a policy future contributors must obey
- Is one we will want to defend, amend, or supersede later

We will *not* write ADRs for:

- Transient bug fixes, mechanical refactors, or stylistic choices
- Decisions fully captured by code + tests + governance pins
- Configuration choices that don't constrain future work

Each ADR must carry four sections: **Status**, **Context**, **Decision**,
**Consequences**. Template lives at [`template.md`](template.md).

Supersession is explicit: old ADR marks `Status: Superseded by ADR-NNNN`;
new ADR marks `Status: Accepted, supersedes ADR-MMMM`. Both files persist.

## Consequences

### Positive

- Future architectural questions have a single discovery path: `docs/adr/`
- Precedent for new decisions is explicit and cite-able
- Governance test `test_adr_discipline.py` pins the structure so ADRs
  don't drift into an unused directory
- CLAUDE.md points at `docs/adr/` for policy-level lookups

### Negative / Costs

- Extra discipline cost per decision (~30-60 min to write an ADR)
- Risk of ADR sprawl if the "significant" filter slips

### Follow-ups

- ADR-0002 retrofits the existing repo-boundary rules from CLAUDE.md /
  ownership_manifest into the record
- ADR-0003 addresses the audit/ops sub-agent parity question (ARCH-21 C)
- ADR-0004 formalizes the new top-level agent extension policy (ARCH-21 D)
- Governance pin: `tests/governance/test_adr_discipline.py`
