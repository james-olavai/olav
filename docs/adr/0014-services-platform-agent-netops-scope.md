# ADR-0014: `services` is a platform core agent; netops scoped to netops + audit

**Status**: Proposed
**Date**: 2026-06-02
**Round**: Architecture audit batch (follows ISSUE-ARCH-AUDIT-WORKSPACE-DUAL-COPY-DEBT)

## Context

The workspace SSOT audit (dev_docs/102, ADR-0002) surfaced a `devops`
fork that turned out to be a deeper ownership question. Findings on
branch `0.20.0`:

- The **`services`** capability — register API services, deploy/stop
  containers (Docker **and** ContainerLab), `docker-compose` ops,
  authenticated HTTP calls against `services.yaml` — currently exists
  only as a **sub-agent of `devops`** in the runtime workspace
  (`.olav/workspace/devops/services/`).
- The platform packaging source `src/olav/data/workspace/services/`
  is **missing**. This is a documented bug: `CLAUDE.md:127` lists
  `src/olav/data/workspace/services/**` as "authoritative
  service-integration tool source", and
  `tests/governance|unit/test_platform_workspaces_packaging.py::
  test_platform_workspaces_source_includes_services` exists *specifically*
  to catch "services lived only in `.olav/workspace/services/` (dev
  runtime)". That test is currently failing.
- The `devops` AGENT.md copies disagree: the netops-bundled source
  routes service tasks **out** to a top-level `--agent services`, while
  the runtime copy makes `services` a devops **sub-agent**.
- `services` is **not network-domain-specific**. Container/service
  lifecycle and API registration are platform infrastructure used by
  every domain (netops, audit, future domains).
- `devops` itself = automation script generation (bash/python/ansible)
  + infra integrations (NetBox DCIM/IPAM, InfluxDB) — also cross-domain
  platform tooling, not netops-specific.
- `ops` retains no agent definition on this branch (only
  `netops_init/state/*.json` runtime snapshots).
- `admin` is already an established platform top-level agent (ADR-0012).
- A separate, abandoned design once planned for `services` to absorb 5
  admin platform-management tools (`workspace_health`, `bulk_ingest`,
  `analyze_logs`, `manage_cron`, `write_workspace_file`); a stale test
  (`test_workspace_health_tool_batch2.py`) still imports
  `olav.data.workspace.services.tools.workspace_health`. `workspace_health`
  does not exist on this branch at all (only in an unrelated worktree).

Per ADR-0002, the platform core (`olav`) must not hard-code
network-domain semantics, and domain ownership boundaries are
authoritative in `ownership_manifest.yaml`. Per ADR-0004, adding a
top-level agent requires an admission decision recorded as an ADR.

## Decision

**1. `services` becomes a platform (`olav`) top-level agent.**
Its authoritative source is `src/olav/data/workspace/services/`
(ships in the wheel; deployed to `.olav/workspace/services/` by
`olav init`). Scope: service lifecycle only — `register_service`,
`deploy_service` (Docker / ContainerLab), `stop_service`,
`docker_compose`, `api_request`. This satisfies ADR-0004's admission
criteria: it is cross-domain platform infrastructure, used by netops,
audit, and future domains alike.

**2. `services` does NOT absorb admin's platform-management tools.**
`admin` remains a separate platform top-level agent (ADR-0012), owning
`installer` / `ops` / `editor` and the platform-management tools
(`workspace_health`, `bulk_ingest`, `analyze_logs`, `manage_cron`,
`write_workspace_file`). Service lifecycle (`services`) and platform
administration (`admin`) are distinct scopes and stay separate. The
stale `test_workspace_health_tool_batch2.py` import must be
**redirected to admin**, not satisfied by `services`.

**3. The netops domain owns only `netops` and `audit`.**
`olav-netops` ships exactly two workspaces: `netops` and `audit`.
`devops`, `ops`, and `services` leave the netops ownership tree.

**4. `devops` moves to platform (`olav`) ownership.**
Its work — automation script generation + service/infra queries
(NetBox/InfluxDB) — is cross-domain platform tooling, not
network-domain semantics. It remains a top-level agent, owned by
`olav`, with `services` removed from it (delegates to the top-level
`services` agent instead, matching the netops-source routing). *(This
sub-decision is the least settled; if `devops` is judged
netops-specific it could instead stay with netops or dissolve — see
Alternatives.)*

**5. `ops` is retired.**
No agent definition remains; only runtime state snapshots
(`netops_init/state/`) which are already `git: ignore`. Remove the
`ops` workspace ownership rules; keep the runtime state dir as
generated/ignored.

### Resulting top-level agent set

| Agent | Owner | Notes |
|---|---|---|
| `core` | olav | unchanged |
| `services` | olav | **new top-level** (was devops sub-agent) — service lifecycle |
| `admin` | olav | unchanged (ADR-0012) |
| `devops` | olav | **moved from netops** — script-gen + infra queries |
| `netops` | olav-netops | unchanged |
| `audit` | olav-netops | unchanged (bundled w/ netops) |

## Consequences

### Positive

- `services` lives where CLAUDE.md and the packaging test already expect
  it; the failing `test_platform_workspaces_source_includes_services`
  passes.
- netops ownership tree matches the stated domain boundary
  (netops + audit only), simplifying `ownership_manifest.yaml`.
- Clear scope split: `services` (service lifecycle) vs `admin`
  (platform administration) vs `devops` (automation/infra) — no more
  overlapping tool homes.

### Negative / Costs

- Cross-package file movement (services + devops out of netops) — a
  multi-step migration with manifest, packaging, and agent-discovery
  updates. Sequenced in dev_docs/103.
- A new top-level agent raises the base agent-discovery surface (ADR-0004
  cost), though `services` already existed as a sub-agent.
- `workspace_health` must be (re)created/located under `admin` on this
  branch (it currently exists only in an unrelated worktree).

### Follow-ups / acceptance criteria

- `src/olav/data/workspace/services/` exists and is in the wheel.
- `test_platform_workspaces_source_includes_services` passes.
- `test_workspace_health_tool_batch2.py` redirected to admin (or admin
  ships `workspace_health`).
- `ownership_manifest.yaml`: services + devops → owner `olav`; ops rules
  removed; netops tree = netops + audit only.
- Execution is **gated on the new e2e suite** per the maintainer
  directive (no release blessing before e2e green).
- Migration plan: **dev_docs/103.SERVICES_PLATFORM_MIGRATION.md**.

## Alternatives considered

- **Keep `services` as a devops sub-agent** (runtime status quo).
  Rejected: contradicts CLAUDE.md + the packaging test, and buries a
  cross-domain platform capability inside a (to-be-moved) agent.
- **`services` absorbs admin's management tools** (the abandoned
  design). Rejected by maintainer: admin stays a distinct platform
  agent; service lifecycle ≠ platform administration.
- **`devops` stays in netops / dissolves into core+services.**
  Open alternative to Decision 4 — devops's NetBox/InfluxDB integrations
  are network-adjacent. Left as a sub-decision to confirm; the default
  here is "devops → platform" because script generation is generic and
  the maintainer scoped netops to netops+audit only.
