# Architecture Decision Records (ADRs)

This directory captures significant architectural decisions for the OLAV
platform. The format follows [MADR](https://adr.github.io/madr/) — a
lightweight, markdown-native ADR template.

## Index

| # | Title | Status | Round |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | Round 29 |
| [0002](0002-repo-boundary-ownership.md) | Repository boundary and ownership rules | Accepted | Round 29 (retrofit) |
| [0003](0003-audit-ops-sub-agent-parity.md) | Audit/ops sub-agent count parity | Accepted | Round 29 |
| [0004](0004-new-top-level-agent-extension-policy.md) | New top-level agent extension policy | Accepted | Round 29 |
| [0005](0005-probe-to-collect-rename-lab-stays-standalone.md) | Rename ops/probe → ops/collect; lab stays standalone | Accepted (supersedes part of ADR-0003) | Round 32 |
| [0006](0006-core-seven-cross-domain-tools.md) | Core agent advertises exactly 7 cross-domain tools | Accepted | Round 33 |
| [0007](0007-python-first-tool-architecture.md) | Python-first tool architecture | Accepted | Round 88-A / 90 |
| [0008](0008-skills-middleware-first-architecture.md) | SkillsMiddleware-first architecture | Accepted | R92 |
| [0009](0009-data-quality-over-prompt-engineering.md) | Data quality over prompt engineering for local small models | Accepted | R-VERTICAL-SLICE |
| [0010](0010-fine-tuning-graduation-line.md) | Fine-tuning graduation line — stop compensating in code for model deficiencies | Accepted | Post R-VERTICAL-SLICE |

## When to write an ADR

Write an ADR when a decision:

- Affects a boundary (repo / package / agent / tool)
- Changes a policy that future contributors need to obey
- Is one we'll want to defend, amend, or supersede later

Do *not* write an ADR for:

- Transient bug fixes or mechanical refactors
- Decisions fully captured by code + tests + governance pins
- Configuration choices that don't constrain future work

## How to add a new ADR

1. Copy [`template.md`](template.md) to `NNNN-kebab-case-title.md` where
   `NNNN` is the next available 4-digit number.
2. Fill in the four required sections: **Status**, **Context**,
   **Decision**, **Consequences**.
3. Set `Status: Proposed` until reviewed, then `Accepted` on merge.
4. Add a row to the Index above.
5. If the decision is pinned by a governance test, link it in
   **Consequences**.

## Superseding an ADR

When a later ADR replaces an earlier one:

- Mark the old ADR `Status: Superseded by ADR-NNNN`
- Mark the new ADR `Status: Accepted, supersedes ADR-MMMM`
- Keep both files — history matters

## Discovery hooks

- `CLAUDE.md` (repo-level agent instructions) points here for architecture policy
- `tests/governance/test_adr_discipline.py` pins the structure (naming, required sections, index consistency)
