# ADR-0005: Rename ops/probe → ops/collect; lab stays a standalone sub-agent

**Status**: Accepted — supersedes part of [ADR-0003](0003-audit-ops-sub-agent-parity.md)
**Date**: 2026-04-18
**Round**: Round 32
**Related issue**: ARCH-21 B.1 (final half); v0.18.1 Sprint 3 Step D

## Context

[ADR-0003](0003-audit-ops-sub-agent-parity.md) declared that Sprint 3 Step D
would merge `ops/probe + ops/lab → ops/collect`, framing both as "live data
acquisition" (probe = from real network, lab = from simulated network). That
framing, on re-examination, does not survive contact with the tool counts
and the workflow semantics:

| Sub-agent | Tool count | Workflow |
|---|---|---|
| `ops/probe/` | **1** (`execute_cli_parallel`) | Active network scout — parallel CLI over Nornir (ping / traceroute / show commands) |
| `ops/lab/` | **10** (`deploy_lab`, `destroy_lab`, `exec_on_node`, `save_lab_config`, `deploy_and_push_lab`, `push_node_config`, `create_srl_links`, `fix_srl_topology`, `run_python_simulation` symlink, etc.) | CAB validation — deploy SR Linux containers from snapshot, push production-equivalent config, verify protocol convergence |

Merging these yields **11 tools** under one sub-agent. ADR-0003 itself
asserts that sub-agent counts should track "distinct workflow count" and
implicitly that one sub-agent should not carry an unbounded tool set. ADR-0003
also cited `≤5` as a design goal. 11 > 5.

Beyond the numbers, the workflows are distinct:

- **probe**: live network → DB. Read-only from devices' perspective.
- **lab**: DB → simulated network → validate → destroy. Completely different
  operator mode (CAB gate keeper, not scout). Has its own CAB Implementation
  Spec contract with `ops-analyze` that a merged agent would dilute.

The practical Sprint 3 goal — "rename probe so the ops sub-agent set reflects
v0.18.1 canonical names" — is satisfiable without merging lab in.

## Decision

1. **Rename `ops/probe/` → `ops/collect/`.** The agent's `name:` frontmatter
   becomes `ops-collect`; the directory moves accordingly. The single tool
   (`execute_cli_parallel`) comes along. The name upgrade reflects the
   broader intent: *parallel live data collection*, not just probing
   (ping/traceroute).

2. **Keep `ops/lab/` as a standalone sub-agent.** It is not merged into
   `ops/collect/`. The `ops-lab` SKILL.md `name:` stays and the orchestrator
   keeps `task("ops-lab", ...)` as a distinct delegation target.

3. **Post-Sprint-3 canonical ops sub-agent set** (5 total, matches ADR-0003
   "distinct workflow" accounting):

   | Sub-agent | Role |
   |---|---|
   | `analyze` | routing analysis + drift detection (Round 31) |
   | `collect` | active live data collection (this ADR) |
   | `lab` | CAB validation via ContainerLab |
   | `devops` | script generation workflows |
   | `infra` | API integrations (NetBox, InfluxDB, registry) |

   5 sub-agents is one more than the "≤4" ambition some readings of ADR-0003
   implied, but it matches the actual distinct-workflow count.

## Consequences

### Positive

- No sub-agent balloons to 11 tools
- `ops-lab`'s CAB Implementation Spec contract with `ops-analyze` is not
  disturbed (they remain peer sub-agents with a clean handoff, as documented
  in `ops/lab/SKILL.md` Verified Working Patterns section — merged in
  Round 18 Step D lite)
- The xfail `test_ops_subagents_merged_to_collect_analyze` flips green
  (asserts `analyze` + `collect` exist, `probe`/`analysis`/`diff` absent;
  does **not** require `lab` to disappear)

### Negative / Costs

- ADR-0003's scheduling table becomes partly obsolete (probe+lab merger row
  superseded by this ADR)
- One more sub-agent than some readers of ADR-0003 expected

### Follow-ups

- **Governance pin**: `tests/governance/test_step_d_probe_rename.py` —
  ensures `collect/` exists with correct frontmatter, `probe/` is gone,
  `lab/` persists
- **xfail flip**: `tests/governance/test_v018_1_spec_guardrails.py::`
  `test_ops_subagents_merged_to_collect_analyze` — xfail mark removed
- **Related ADRs**:
  - [ADR-0003](0003-audit-ops-sub-agent-parity.md) — partly superseded by
    this ADR on the probe+lab merger specifically; audit/ops "distinct
    workflow count" rationale still stands
  - [ADR-0004](0004-new-top-level-agent-extension-policy.md) — unaffected
    (this is a sub-agent decision, not a new top-level)
- **Future**: if `collect/` grows beyond 2-3 tools (e.g. active scanning
  with nmap, SNMP walk), revisit whether to split into `collect-active`
  and `collect-passive`. For v0.18.1 the single-tool `ops-collect` is
  correct; growing it is a separate future ADR.
