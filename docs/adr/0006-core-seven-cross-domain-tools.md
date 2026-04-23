# ADR-0006: Core agent advertises exactly 7 cross-domain tools

**Status**: Accepted
**Date**: 2026-04-18
**Round**: Round 33
**Related issue**: ARCH-21 A (Sprint 3 Step E); supports ARCH-17 static-context budget

## Context

`core` is OLAV's default top-level agent — the one that runs when a user
types `olav "<question>"` with no `--agent`. In v0.18.0 `core/SKILL.md`
advertised **21 @tool entries**. The content broke down roughly as:

| Bucket | Count | Examples |
|---|---|---|
| Cross-domain (computation, memory, KB, web, export) | 5-6 | `run_python_code`, `execute_sql`, `recall_memory`, `search_knowledge_lancedb`, `web_search`, `format_and_export` |
| Network-ops domain | 4 | `execute_cli`, `search_commands`, `diff_configs`, `take_snapshot` |
| Service lifecycle | 3 | `deploy_service`, `stop_service`, `api_request` |
| Platform admin | 4 | `write_workspace_file`, `run_shell`, `load_reference`, `search_logs` |
| Scheduling CRUD | 4 | `list_cron`, `add_cron`, `remove_cron`, `apply_cron_schedules` |

Problems:

1. **Prompt budget** (ARCH-17): 21 tool signatures at init → ~10K tokens of
   system prompt before a single user message. Small-model tier (8K context)
   can't afford this.
2. **"Right tool on first try" miss**: confronted with 21 options the LLM
   often picks a generic tool when a domain tool would be more appropriate.
   Trimming the top-level list sharpens routing.
3. **Domain leakage**: `execute_cli` / `diff_configs` don't belong in a
   "what should I do by default" agent — they belong in `ops/` sub-agents
   whose SKILL.md already advertises them.

v0.18.1 spec (ADR-0003 rev 151) proposed "core ≤7 cross-domain tools". This
ADR nails down *which* 7 and *how to count*.

## Decision

### 1. `core/SKILL.md` advertises exactly 7 capabilities

```yaml
tools:
  - run_python_code
  - execute_sql
  - recall_memory
  - search_knowledge_lancedb
  - web_search
  - format_and_export
  - manage_cron
```

### 2. "Capability" vs "@tool" count

The budget counts **advertised capabilities**, not underlying Python
`@tool` function count. `manage_cron` is **one capability** even though
`core/tools/manage_cron.py` has four `@tool`-decorated functions
(`list_cron`, `add_cron`, `remove_cron`, `apply_cron_schedules`) — they
are the CRUD operations of a single scheduling capability and share the
same mental model.

**Round 34 consolidated** the four `@tool` decorators into a single
`manage_cron(action=...)` dispatcher. The four CRUD operations
(`list_cron`, `add_cron`, `remove_cron`, `apply_cron_schedules`)
remain as plain-Python functions called by the dispatcher. See
`tests/governance/test_step_e_core_capabilities.py::test_manage_cron_is_single_tool_dispatcher`.

### 3. Removed from core advertised list (14 tools)

| Removed from core | New home (primary) | Access path |
|---|---|---|
| `execute_cli` | `ops/` (canonical `ops/tools/execute_cli.py`) | `--agent ops` or orchestrator `task("ops-analyze"/"ops-collect", …)` |
| `search_commands` | `ops/` | same |
| `diff_configs` | `ops/analyze/` (Round 31) | same |
| `take_snapshot` | `ops/collect/` (Round 32) | same |
| `deploy_service` | `services/` (Round 16) | `--agent services` |
| `stop_service` | `services/` | same |
| `api_request` | `services/` | same |
| `write_workspace_file` | `core/admin/` sub-agent | delegated internally; user-visible via `--agent core` which auto-routes |
| `run_shell` | `core/remote/` sub-agent | same |
| `load_reference` | `core/` internal lazy-loading (not an advertised tool; called on demand via static_context resolver) | automatic |
| `search_logs` | `audit/auditor/` (log analysis is an audit concern) or `core/admin/` | `--agent audit` for diagnostic queries |
| `list_cron`, `add_cron`, `remove_cron`, `apply_cron_schedules` | consolidated under `manage_cron` capability | remain as `@tool` fns in `core/tools/manage_cron.py`; advertised as one |

### 4. Physical file layout unchanged

**`core/tools/*.py` files are not moved or deleted.** ARCH-20 Phase 2
("canonical home + symlinks") continues to apply. Sub-agents that need
the moved tools symlink to `core/tools/` or `ops/tools/` as appropriate.
The 21→7 trim is a change to **advertised** surface only; **canonical
ownership** of the tool implementations is independent.

### 5. Governance test semantics

`test_core_agent_has_at_most_7_tools` is updated from counting
`core/tools/*.py` physical files (19+ and irreducible under ARCH-20 P2)
to counting `core/SKILL.md` advertised `tools:` entries (≤7). The
physical file count is no longer a useful metric for this budget.

## Consequences

### Positive

- **Prompt budget**: core init prompt drops ~2-3K tokens; small-model tier
  fits much more comfortably
- **"Right tool on first try"**: LLM sees a focused 7-capability menu and
  picks more accurately; domain work naturally escalates to the correct
  sub-agent or `--agent <domain>` flag
- **Explicit policy**: future contributors proposing to add a new tool to
  core have a written rubric ("Is it cross-domain? If no → which sub-agent
  takes it?")

### Negative / Costs

- Users whose habit was `olav "<network command>"` now get a one-hop
  delegation (orchestrator → ops-analyze) instead of direct execution.
  Latency impact: ~1 LLM round trip. The semantic router (v0.15+) already
  does this automatically for keyword-rich queries; the additional cost
  is observable only for edge-case wording.
- `core/tools/` directory content (19 files) visibly exceeds the
  `tools:` declaration (7 entries). This is by design but surprising at
  first glance; ADR and test docstrings document it.

### Follow-ups

- **Governance pins**:
  - `tests/governance/test_v018_1_spec_guardrails.py::test_core_agent_has_at_most_7_tools`
    — updated to count SKILL.md advertised tools; xfail mark removed
  - `tests/governance/test_step_e_core_capabilities.py` — pins the exact 7
    capabilities, verifies removed tools still exist as canonical files,
    confirms ADR-0006 is present
- **Related ADRs**:
  - [ADR-0003](0003-audit-ops-sub-agent-parity.md) — sub-agent count
    principle ("distinct workflow count"); this ADR is the core-level
    analog ("cross-domain capability count")
  - [ADR-0005](0005-probe-to-collect-rename-lab-stays-standalone.md) —
    similar supersede-in-part pattern when scheduling reality meets spec
- **Round 34 (completed)**: consolidated 4 cron `@tool` fns → 1 dispatcher
  `manage_cron(action=...)`. Cosmetic but symmetric with the capability
  declaration. Not required for ADR-0006 compliance.
- **ARCH-17 static context budget**: this trim is one of several
  converging pressures on core's prompt size. `core/AGENT.md`
  `static_context_mode: on_intent` (Round 24) is the complementary fix.

## Closes

Sprint 3 Step E (last of the five canonical Sprint 3 steps).
ARCH-21 A ("core 'god agent' 瘦到 ≤7 跨域 tools") → ✅ Closed.
