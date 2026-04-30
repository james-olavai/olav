---
name: ops-lab
description: >
  ContainerLab digital twin validation. Deploy SR Linux containers from snapshot DB,
  push production-equivalent config, verify protocol convergence, tear down labs.
  Use for Change Advisory Board (CAB) gate validation before production deployment.
metadata:
  version: 5.0.0
  type: agent
  category: network-operations
  intents:
    - cab_validation
    - digital_twin
    - change_validation
    - lab_emulation
    - deploy_lab
    - destroy_lab
    - push_config
tools:
  # All deterministic ops are skill scripts under ./scripts/ (ADR-0008
  # rev1 / R92.6).  Invoke via execute_skill_script(skill_name="lab",
  # script_name="<x>.py", script_args={...}).  Only @tool surface kept
  # is exec_on_node for real-time show-command streaming.
  - execute_skill_script
  - exec_on_node
static_context:
  - path: ./references/LAB_REFERENCE.md
static_context_mode: on_intent
---

## Flow (TCF-native, R92 SkillsMiddleware-first)

Each step is `execute_skill_script(skill_name="lab", script_name="<x>.py", ...)`.
For exact `script_args` shape, read the script's docstring or
`references/LAB_REFERENCE.md`.

```
0. tcf_load_for_lab.py              → r88_args, r89_args, post_check, tvt
1. generate_clab_topology.py        → yaml (NEVER hand-write — small models
                                      omit links: and break BGP)
2. generate_srl_lab_config.py       → 22-line SRL CLI per node (NEVER
                                      hand-translate prod CLI to SRL —
                                      hits YANG rejections)
3. save_lab_config.py               → writes deploy contract path (one call/node)
4. deploy_and_push_lab.py           → boots CLAB + pushes configs
5. exec_on_node                     → run each post_check.command, compare to
                                      expected_pattern (real-time streaming)

5b. ROLLBACK VALIDATION (only when 5 passed):
   generate_srl_rollback_config.py  → 7-line delete CLI per node
   push_node_config.py              → applies rollback
   exec_on_node                     → verify reversion

6. format_and_export                → standalone CAB Lab Report (.md)
7. tcf_record_lab_run.py            → writes verdict + journal + per-test
                                      actuals back to TCF
8. destroy_lab.py                   → ALWAYS run, even on failure
```

## CAB is a validation gate, NOT a fix-it loop

If `deploy_and_push_lab` returns `dry_run_failures`: fix with
`push_node_config` **ONCE** per CAB_WORKFLOW template, then report
FAIL if still failing.  Step 6 is REPORT, not "iterate and fix."

## Decision rules

* **✅ PASS** — all checks converge.  Output evidence + Design
  Commentary (🟠/🔵 allowed even on pass).
* **❌ FAIL** — any check fails.  Output evidence + classification
  (🔴 BLOCKER / 🟡 PREREQ / 🟠 SYNTAX) + revision instructions for
  Sim, then `destroy_lab.py`.

On FAIL: do NOT try alternatives to make it work.  Report → stop →
destroy lab.  Full rubric: `../references/CAB_REPORT_FORMAT.md`.

## Key rules

* **Change plan is the contract** — implement exactly what it says
* All production data comes from snapshot DB — NEVER access
  production devices from the lab agent
* Config push always uses `discard now` + base64 pipe + `2>&1`
  (LAB_REFERENCE § Config Push)
* Show commands: `exec_on_node` with `"bash -c 'sr_cli ... 2>&1'"`
* Never destroy a lab without confirming the lab name
* Every session must clean up; if cleanup fails mid-way, still
  attempt it before reporting failure

## References (on_intent)

* `references/LAB_REFERENCE.md` — CLAB API + SRL CLI + verified patterns
* `prompts/system.md` — full workflow rules
* `../references/CAB_WORKFLOW.md`, `CAB_REPORT_FORMAT.md`
