---
name: ops-lab
description: "CAB lab validation — deploys ContainerLab digital twin, pushes config, verifies convergence, reports PASS/FAIL."
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
  - format_and_export   # Patch D' Step 5 (2026-05-08): lab needs it
                        # to write the standalone CAB Lab Report (.md,
                        # human read) per system.md step 6.
static_context:
  - path: ./references/LAB_REFERENCE.md
static_context_mode: on_intent
---

## Flow — DEFAULT: one atomic call (Patch L, 2026-05-07)

For the standard CAB validation path (TCF spec → PASS/FAIL verdict)
make ONE call:

```
execute_skill_script(skill_name="lab",
                     script_name="validate_tcf_in_lab.py",
                     script_args={"spec_path": "<path>"})
```

Returned envelope: ``verdict`` (PASS/FAIL), ``post_check_results``,
``tvt_results``, ``journal``, ``lab_name``, ``tcf_recorded``,
``lab_destroyed``, ``errors``. The script runs the full pipeline
server-side (load → topology → srl render → save × N → deploy +
push → verify each post_check → record back to TCF → destroy).

After this returns, write the CAB report straight from
``post_check_results`` + ``journal``. No further skill_script calls
needed for the happy path.

### Optional flags
* ``destroy_on_finish: false`` — leave lab running for ad-hoc inspection
* ``skip_record: true`` — dry-run without touching the TCF spec
* ``deploy_wait_seconds`` / ``post_commit_wait_seconds`` /
  ``convergence_wait_seconds`` — tune the BGP/OSPF settle time

### Manual flow (only when validate_tcf_in_lab is not enough)

If you need to deviate (e.g. fix-and-retry on a YAML error, run
rollback validation, exec ad-hoc show commands), fall back to the
individual skill scripts:

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
