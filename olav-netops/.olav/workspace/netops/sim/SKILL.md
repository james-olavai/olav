---
name: sim
description: "Simulation + change planning. Designs network changes (eBGP / iBGP / VLAN / etc.), runs what-if simulations against the digital twin, and submits the plan via a structured tool call. Free-form prose analysis lives inside the tool's rationale + steps fields; schema-constrained metadata (intent, devices) drives deterministic TCF rendering on the Python side."
tools:
  - run_python_simulation
  - submit_change_plan
  - format_and_export
static_context_mode: on_intent
system: $ref:./prompts/system.md
metadata:
  version: 1.1.0
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - change_simulation
    - change_planning
    - what_if_analysis
    - feasibility_check
---

## Sim — write-side analysis

R-AGENT-HIERARCHY Phase B+C+D (2026-05-09).  Split out from `analyze`
(which kept the read-side: drift / topology Q&A / Mermaid).  Sim
owns forward-looking analysis: simulating proposed changes, checking
feasibility, and submitting the change plan via `submit_change_plan`.

## Workflow (3 steps, ends with tool call)

1. **Feasibility check** (ONE sandbox call):

       run_python_simulation(experiment_code='''
       asns = db.query("""
         SELECT device_name, local_as
         FROM netops.v_show_ip_bgp_summary_auto
         WHERE device_name IN ('R1','R3')
       """)
       _result = {"asns": asns}
       ''')

   Don't loop on this — ONE call is enough for the basic yes/no.

2. **Decide feasibility** based on the data.  For ebgp_direct:
   if both devices in same AS → BLOCKED; else OK.

3. **Submit** via the structured tool call.  This ENDS your loop:

       submit_change_plan(
           intent="ebgp_direct",
           devices=["R2", "R3"],
           summary="Add eBGP between R2 and R3",
           rationale=(
               "R2 (AS 65001) and R3 (AS 65000) currently rely on "
               "transit through R4 for reachability.  Direct eBGP "
               "gives a redundant path."
           ),
           steps=(
               "Phase 1: configure both devices simultaneously.\n"
               "Phase 2: verify session reaches Established within 60s.\n"
               "Phase 3: confirm both devices learn each other's loopback."
           ),
           feasibility="OK",
       )

   The tool returns `{plan_md_path, spec_path, facts, warnings}` on
   success or `{error, blockers}` on failure.

## What you DO NOT pass

- `device_platforms` / `device_loopbacks` / `device_asns` — these
  come from the DB; the writer queries them itself.
- `implementation_json` / `rollback_json` / `post_check_json` — the
  writer renders CLI from per-platform templates.
- `change_id` — auto-generated from devices + intent.

## Rationale + steps are FREE-FORM

These fields are Markdown.  Multi-paragraph.  Multi-section.  They
become the human-readable change-plan artifact for HITL review.
Write them well — they're the user's primary review surface.

## What sim DOES NOT do (read-side stays with analyze)

- Drift detection between snapshots → `task("ops-analyze", ...)`
- BGP attribute investigation / AS_PATH walks → analyze
- Topology Q&A / Mermaid rendering → analyze
- Blast-radius reachability → analyze

If the user's request is investigative (not a forward-looking
change), redirect them.

## Sandbox SQL rule (inherited)

`sim.execute()` with literal SQL starting with `CREATE` / `INSERT`
etc. MUST use a variable (sandbox_guard pattern):

```python
_sql = "CREATE TABLE sim_x (col VARCHAR)"
sim.execute(_sql)  # NOT: sim.execute("CREATE TABLE ...")
```

## Supported intents

| intent_type   | What it does |
|---|---|
| `ebgp_direct` | Direct eBGP session, 2 devices, different ASNs |
| `ibgp_direct` | iBGP session, 2 devices, same AS (placeholder) |
| `vlan_add`    | Add VLAN trunk between 2 switches (placeholder) |

For unsupported intents, the tool returns an explicit error;
escalate to a human operator.
