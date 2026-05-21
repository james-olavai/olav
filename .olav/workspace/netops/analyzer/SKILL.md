---
name: analyzer
# 2026-05-14 cross-domain upgrade (dev_docs/77 §2.6): analyzer is
# the *report author*.  For multi-substrate investigations it
# delegates config-layer questions to ``simulator`` via deepagents'
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
# num_ctx — see core/llm.py + .olav/config/api.json).  The per-skill
# override mechanism is used by deterministic sub-agents (sim/learner
# have ``temperature: 0.0``).
subagents:
  - path: ../simulator/SKILL.md
description: "Standalone Markdown-output analyzer + report author.  Three modes: (A) change-plan drafter — gather facts via execute_sql, write a vendor-specific change plan markdown (CLI per device + rollback + post-checks + risks) to exports/change_plans/; (B) investigation/audit reporter — gather facts, synthesise across L1-L4 layers, write a structured report to exports/reports/; (C) L2 topology what-if — inspect_blast_radius simulates device/link failures on the NetworkX graph (not Batfish — see capability boundary below).  Mode picked from the prompt: 'plan / add / change X' → A; 'investigate / audit / write report on Y' → B; 'what if X fails / blast radius of Y' → C.  For control-plane questions (BGP/OSPF compat, reachability policy), analyzer delegates to simulator via task('simulator', ...) per dev_docs/77 §2.6."
tools:
  - execute_sql          # SQL on main.duckdb (read-only) — covers facts + cross-view JOIN + snapshot diff
  - execute_skill_script # call analyzer scripts (describe_table, query_evidence)
  - diff_configs           # raw CLI config diff between two snapshots (difflib — not expressible as SQL)
  - diff_snapshots         # SQL-based structural diff across parsed_outputs/topology_links/raw_output_store between two snapshot IDs
  - inspect_blast_radius   # L2 topology what-if: remove devices/links → NetworkX weakly-connected components
  - format_and_export    # Markdown emission to exports/change_plans or exports/reports
scripts:
  - name: describe_table
    description: "Phase 0a schema discovery — columns + types + 2 sample rows per table call"
    file: describe_table.py
  - name: query_evidence
    description: "Unified text search across syslog/command_output/config (3 sources via Literal arg)"
    file: query_evidence.py
# Capability boundary — inspect_blast_radius vs sim (Batfish):
#   inspect_blast_radius → L2 graph: "if device X fails, how many nodes are isolated?"
#   sim → control plane: routing policy, BGP/OSPF config compatibility, ACL reachability
# Structured change-record (TCF) emission is enterprise-only (olav-ent lab).
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

### Tools (5 tools + 2 scripts)

| Tool | Purpose |
|---|---|
| `execute_sql(sql=..., explain_only=False)` | read-only SQL on `main.duckdb`; covers per-device facts, cross-view JOINs, snapshot-id diff. Returns `list[dict]`. |
| `diff_configs(device=..., command=..., snapshot_id_1=..., snapshot_id_2=...)` | raw CLI config diff between two snapshots (difflib — not expressible as SQL). |
| `diff_snapshots(snapshot_id_1=..., snapshot_id_2=..., table_name=None, device=None)` | SQL-based structural diff across `parsed_outputs`/`topology_links`/`raw_output_store` between two snapshot IDs. |
| `inspect_blast_radius(remove_devices=[...], remove_links=[[A,B]])` | L2 topology what-if: remove devices/links from NetworkX graph → returns isolated nodes + component count delta. NOT Batfish — graph topology only, no control-plane. |
| `format_and_export(data=<MD>, filename=..., format="md", subdir="change_plans"\|"reports")` | emit the Markdown artifact. |

| Script | Purpose |
|---|---|
| `scripts/describe_table.py` | one-shot schema introspection: columns + types + 2 sample rows. Use in Phase 0a before writing JOIN SQL. Invoke via stdin JSON: `{"table_name": "netops.devices", "include_samples": true}`. |
| `scripts/query_evidence.py` | text search across recorded outputs / syslog / configs. Invoke via stdin JSON: `{"source": "syslog"\|"command_output"\|"config", "pattern": "...", "device": "...", "time_range": "...", "snapshot": "..."}`. |

### Two output modes

* **Workflow A — Change plan markdown** (`subdir="change_plans"`)
  Trigger: "plan / add / change / change request / new ... between X and Y / modify".
  Output: complete change plan including CLI per device, rollback,
  post-checks, risks.

* **Workflow D — Investigation / audit report** (`subdir="reports"`)
  Trigger: "investigate / audit / comprehensive report / deep research".
  Output: layered (L1-L4) health/audit report with findings,
  cross-layer anomalies, recommendations.

Detailed prompts for both workflows live in `prompts/system.md`.

### What this sub-agent does NOT do

- No CLI execution on devices (read-only).
- No control-plane evaluation (BGP policy, route-map, ACL reachability) → `task("simulator", ...)`.
- No structured-spec output (TCF / DraftChangePlan / Pydantic schemas) —
  that's enterprise-only (olav-ent lab).  This sub-agent emits Markdown.
- Every operation uses one of the 7 tools above.
