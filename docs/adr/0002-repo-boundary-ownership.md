# ADR-0002: Repository boundary and ownership rules

**Status**: Accepted (retrofit)
**Date**: 2026-04-18
**Round**: Round 29 (retrofits rules that predated the ADR practice)

## Context

OLAV is a mono-repo hosting five delivery units:

| Unit | Location | Role |
|---|---|---|
| `olav` | `src/olav/`, `.olav/workspace/{audit,core,ops,services}/` | Platform core (control plane, runtime, CLI, plugin contracts) |
| `olav-netops` | `olav-netops/` | Network domain extension |
| `olav-ent` | `olav-ent/` | Enterprise extension |
| `olav-doc` | `olav-doc/` | MkDocs site (`docs.olavai.com`) |
| `olav-web` | `olav-web/` | Marketing site (Astro + Cloudflare Worker, `olavai.com`) |
| `olav-post` | `olav-post/` | Local-only content archive |

Without boundary rules we risk:

- Runtime imports from platform core into domain extensions (platform
  learns domain specifics → plugin contract broken)
- Docs/web dual-sourcing across the root and `olav-doc/` / `olav-web/`
- Publishing `olav-post` (local-only archive) to any remote

Rules have been enforced since v0.17 via `CLAUDE.md` prose and
`ownership_manifest.yaml` path-level rules, plus
`scripts/scan_ownership.py` as a CI gate. ADR-0001 mandates that such
rules live as a decision record; this ADR retrofits them.

## Decision

### Allowed dependency directions

- `olav-netops → olav` (platform contract)
- `olav-ent → olav` (platform contract)
- `olav-doc → none` (no runtime dependency)
- `olav-web → none` (no runtime dependency)
- `olav-post → none` (no runtime dependency, local-only)

### Reverse coupling (`olav → olav-netops`, `olav → olav-ent`)

Permitted *only* via:

- Entry-point / plugin discovery (dynamic, lazy)
- Guarded optional imports (`try/except ImportError`)
- **Never** as a hard startup dependency

### Forbidden

- `olav-doc` importing `src/olav` runtime code
- `olav-web` importing `src/olav` runtime code
- `olav-post` importing `src/olav` runtime code
- `olav` core hard-coding network-domain or enterprise-specific semantics
- Dual-source editing of docs/web in both root and `olav-doc` / `olav-web`
- Publishing `olav-post` to any remote

### Single source of truth

- `ownership_manifest.yaml` at repo root — every path covered by a rule
  (`owner`, `class`, `status`, `git: track|ignore|secret`)
- `.gitignore` is **auto-generated** from that manifest via
  `scripts/gen_gitignore.py --write` — manual edits are rejected
- `scripts/scan_ownership.py --summary` must report `0 ERROR`

### Release surface

Only the following are published:

- `src/olav/**` — platform Python package
- `pyproject.toml`, `README.md`, `LICENSE`
- `ownership_manifest.yaml`
- `.olav/config/*.example` — config templates
- `.olav/workspace/{core,audit,services}/**` — platform agents

Everything else (tests, scripts, dev_docs, sub-repos, exports, databases)
stays on-disk for development and is not in the release.

## Consequences

### Positive

- Boundary rules are cite-able from one place instead of reading
  `CLAUDE.md` + `ownership_manifest.yaml` + dev_docs in parallel
- `scan_ownership.py` `0 ERROR` invariant has a recorded rationale

### Negative / Costs

- The manifest + ADR pair must stay in sync; a rule change without a
  corresponding ADR update creates drift. Governance tests below catch
  the cases we've seen so far.

### Follow-ups

- **Governance pins**:
  - `scripts/scan_ownership.py` — `0 ERROR` invariant
  - `tests/governance/test_platform_boundary_*` — platform / netops boundary
  - `tests/governance/test_claude_md_consistency.py` — CLAUDE.md paths exist
- **Related**:
  - ADR-0003 (audit/ops sub-agent parity) — uses these boundary rules
  - ADR-0004 (new top-level agent extension policy) — extends boundary
    with admission criteria for new top-level workspace agents
