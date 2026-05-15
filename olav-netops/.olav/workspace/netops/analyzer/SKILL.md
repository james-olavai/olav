---
name: analyzer
# 2026-05-14 cross-domain upgrade (dev_docs/77 §2.6): analyzer is
# the *report author*.  For multi-substrate investigations it
# delegates config-layer questions to ``sim`` via deepagents'
# native ``task()`` tool (auto-injected because we declare
# ``subagents:`` here + agent.py builds us via ``create_deep_agent``
# per Phase 1 commit 360a8816).  ``agent_type: api`` is dropped:
# analyzer needs TodoListMiddleware (planning across delegations)
# and SubAgentMiddleware (task tool).
#
# 2026-05-13: standalone Markdown sub-agent (preserved).  Two output
# modes (both Markdown via format_and_export):
#   * Workflow A — change plan request → exports/change_plans/<topic>.md
#   * Workflow D — investigation / audit / deep research → exports/reports/<topic>.md
thinking_mode: enabled
# 2026-05-15: analyzer inherits global defaults (32K max_tokens, 64K
# num_ctx — see core/llm.py + .olav/config/api.json).  The earlier
# explicit ``llm:`` block was redundant once global max_tokens went
# 16K → 32K.  The per-skill override mechanism is now exercised by
# the deterministic-output sub-agents (sim/investigate/learner have
# ``temperature: 0.0``) and the short-message memory_curator.
subagents:
  - path: ../sim/SKILL.md
description: "Standalone Markdown-output analyzer + report author.  Two modes: (A) change-plan drafter — gather facts via execute_sql, write a vendor-specific change plan markdown (CLI per device + rollback + post-checks + risks) to exports/change_plans/; (B) investigation/audit reporter — gather facts, synthesise across L1-L4 layers, write a structured report to exports/reports/.  Mode picked from the prompt: 'plan / add / change X' → A; 'investigate / audit / write report on Y' → B.  For config-layer questions (BGP/OSPF compat, reachability, what-if), analyzer delegates to sim via task('sim', ...) per dev_docs/77 §2.6."
tools:
  # 5-tool minimal set (2026-05-13 final refactor):
  - execute_sql          # SQL on main.duckdb (read-only) — covers facts + cross-view JOIN + snapshot diff
  - describe_table       # Phase 0a schema discovery — one call returns columns + 2 sample rows
  - query_evidence       # log / syslog / command_output / config text search (3 sources via Literal arg)
  - inspect_drift_configs  # raw CLI config diff between two snapshots (difflib — not expressible as SQL)
  - format_and_export    # Markdown emission to exports/change_plans or exports/reports
# NetworkX / what-if / blast-radius are NOT analyzer's job — delegate
# to ``task("sim", ...)`` for config-layer evaluation.  Structured
# change-record (TCF) emission is enterprise-only (olav-ent lab).
allowed_tables:
  - netops.devices
  - netops.topology_links
  - netops.parsed_outputs
  - netops.raw_output_store
  - netops.commands
  - netops.v_show_ip_bgp_summary_auto
  - netops.v_show_ip_bgp_neighbors_auto
  - netops.v_show_ip_ospf_neighbor_auto
  - netops.v_show_ip_interface_brief_auto
  - netops.v_show_interfaces_auto
  - netops.v_show_interfaces_terse_auto
  - netops.v_l2_links_auto
static_context_mode: on_intent

# 2026-05-14: portability manifest — list YAML knowledge files
# located under ./references/.  OLAV runtime continues recursive
# import via ``olav kb import-guides`` (behaviour unchanged); this
# field is for downstream agent frameworks (LangGraph etc.) that
# need an explicit knowledge inventory to migrate the agent.
# Each referenced YAML carries its own ``keywords``/``priority``/
# ``body`` so the consumer can implement AutoRecall-style or
# fall-back-to-static loading.
dynamic_context:
  - path: ./references/topology_query.guide.yaml
  - path: ./references/change_plan_cli_authoring.guide.yaml
  - path: ./references/fault_analysis_workflow.guide.yaml
  - path: ./references/plan_act_reflect_workflow.guide.yaml
  - path: ./references/schema_introspection_via_describe_table.guide.yaml
  - path: ./references/troubleshoot_layered_l1_to_l4.guide.yaml

system: $ref:./prompts/system.md
metadata:
  version: 5.0.0
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - change_request
    - change_planning
    - complex_investigation
    - audit_report
    - deep_research
---

## Analyzer — standalone markdown analyzer

Designed for the **30B model tier**: no submission to a downstream
Python pipeline, no schema-validated envelope.  Plan, gather facts,
think layered (L1-L4), and produce a Markdown file an engineer can
read and act on.

### Tools (5 total — one tool per concern)

| Tool | Purpose |
|---|---|
| `execute_sql(sql=..., explain_only=False)` | read-only SQL on `main.duckdb`; covers per-device facts, cross-view JOINs, snapshot-id diff. Returns `list[dict]`. |
| `describe_table(table_name=..., include_samples=True)` | one-shot schema introspection: columns + types + 2 sample rows. Use in Phase 0a before writing JOIN SQL. |
| `query_evidence(source="syslog"\|"command_output"\|"config", pattern=..., device=..., time_range=..., snapshot=...)` | text search across recorded outputs / syslog / configs. |
| `inspect_drift_configs(device=..., snap_a=..., snap_b=...)` | raw CLI config diff between two snapshots (difflib — not expressible as SQL). |
| `format_and_export(data=<MD>, filename=..., format="md", subdir="change_plans"\|"reports")` | emit the Markdown artifact. |

### Two output modes

* **Workflow A — Change plan markdown** (`subdir="change_plans"`)
  Trigger: "plan / add / change / 变更 / new ... between X and Y / modify".
  Output: complete change plan including CLI per device, rollback,
  post-checks, risks.

* **Workflow D — Investigation / audit report** (`subdir="reports"`)
  Trigger: "investigate / audit / comprehensive report / 深度调研".
  Output: layered (L1-L4) health/audit report with findings,
  cross-layer anomalies, recommendations.

Detailed prompts for both workflows live in `prompts/system.md`.

### What this sub-agent does NOT do

- No CLI execution on devices (read-only).
- No NetworkX / graph algorithms / what-if simulation → `task("sim", ...)`.
- No structured-spec output (TCF / DraftChangePlan / Pydantic schemas) —
  that's enterprise-only (olav-ent lab).  This sub-agent emits Markdown.
- No `run_python_simulation` (sandbox) — every operation is one of the 5 tools above.
