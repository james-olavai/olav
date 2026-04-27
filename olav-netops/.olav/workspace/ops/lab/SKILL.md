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
  # Per ADR-0008 rev1 (R92.6): all deterministic + REST/SSH-callable
  # ops live as skill scripts under ./scripts/. Invoke via
  # execute_skill_script(skill_name="lab", script_name="<name>.py", args={...}).
  # The agent's @tool surface for ops/lab is just 1 tool (real-time
  # streaming) — everything else is a skill script.
  - execute_skill_script   # Inherited from core/tools/. Drives all ./scripts/ entries.
  - exec_on_node           # @tool kept: real-time streaming for show commands during verification
static_context:
  - path: ./references/LAB_REFERENCE.md
# R86 — on_intent (~4K tokens, largest reference of all).
# LAB_REFERENCE only matters for CAB / lab-deploy flows; baking it
# on EVERY ops-orchestrator invocation that happens to route to
# ops-lab is wasteful.  Lazy-loaded; agent fetches via
# get_static_context when the workflow actually starts a lab.
static_context_mode: on_intent
---

## Flow (TCF-native, R92 SkillsMiddleware-first per ADR-0008)

The deterministic generators are **skill scripts** under
``./scripts/``. The agent calls them via ``execute_skill_script``
(inherited from ``core/tools/``). The script imports the relevant
``olav.core.cab`` / ``olav.core.lab`` Python helper, parses JSON
args from stdin, and emits JSON on stdout — the tool returns the
parsed dict.

```
0.  execute_skill_script(
        skill_name="lab", script_name="tcf_load_for_lab.py",
        args={"spec_path": "<path>"})
    # stdout → {status, change_id, r88_args, r89_args, post_check, tvt, ...}

1.  execute_skill_script(
        skill_name="lab", script_name="generate_clab_topology.py",
        args=out["stdout"]["r88_args"])
    # stdout → {status, yaml}

2.  execute_skill_script(
        skill_name="lab", script_name="generate_srl_lab_config.py",
        args=out["stdout"]["r89_args"])
    # stdout (parsed) → {status, configs: {lab_node: 22-line srl_cli}}

3.  execute_skill_script(
        skill_name="lab", script_name="save_lab_config.py",
        args={"lab_name": ..., "node": <lab_node>,
              "config_lines": configs[lab_node].splitlines()})
    [one call per node — writes to deploy contract path]

4.  execute_skill_script(
        skill_name="lab", script_name="deploy_and_push_lab.py",
        args={"lab_name": ..., "yaml_content": <step 1 yaml>, "configs": {}})

5.  exec_on_node — run each post_check.command, compare to expected_pattern
    (stays as @tool — real-time streaming for interactive show commands)

5b. ROLLBACK VALIDATION — only when apply tests PASSED:
    a. execute_skill_script(
           skill_name="lab", script_name="generate_srl_rollback_config.py",
           args=r89_args)
       # stdout → {status, configs: {lab_node: 7-line delete CLI}}
    b. execute_skill_script(
           skill_name="lab", script_name="push_node_config.py",
           args={"lab_name": ..., "node": <lab_node>,
                 "config_lines": rollback_configs[lab_node]})
    c. exec_on_node — verify reversion (BGP gone, no IPv4 on subif).

6.  format_and_export — standalone CAB Lab Report (.md)
7.  execute_skill_script(
        skill_name="lab", script_name="tcf_record_lab_run.py",
        args={"spec_path": ..., "verdict": ..., "lab_name": ...,
              "tvt_test_ids": [...], "tvt_actual_lab": [...],
              "tvt_status": [...], "journal": [...]})
    # writes verdict + journal + per-test actuals back to TCF
8.  execute_skill_script(
        skill_name="lab", script_name="destroy_lab.py",
        args={"lab_name": ...})
    — ALWAYS run, even on failure
```

**⚠️ NEVER hand-write `yaml_content`** — small models omit
`links:` and silently break BGP. Always invoke the
``generate_clab_topology.py`` skill script.

**⚠️ NEVER hand-translate prod CLI to SRL CLI** — always invoke
the ``generate_srl_lab_config.py`` skill script. It
deterministically renders the 22-line SRL skeleton; hand-translation
hits SRL YANG rejections (``connectivity-endpoint``, missing
``peer-group``, etc.) and never converges.

**⚠️ CAB is a validation gate, NOT a fix-it loop.**  If
`deploy_and_push_lab` returns `dry_run_failures`: fix with
`push_node_config` **ONCE** using the CAB_WORKFLOW template, then
report FAIL if still failing.  Step 6 is REPORT, not "iterate and fix."

## CAB Decision Rules (summary)

**✅ PASS** — all checks converge.  Output evidence + Design Commentary
(🟠/🔵 items allowed even on pass).

**❌ FAIL** — any check fails.  Output evidence + classification
(🔴 BLOCKER / 🟡 PREREQ / 🟠 SYNTAX) + revision instructions for Sim,
then `destroy_lab`.

Full rubric and classification rules:
**`references/CAB_REPORT_FORMAT.md`**.

On FAIL: do NOT try alternatives to make it work.  Report → stop →
destroy lab.

## Key Rules

- **The change plan is the contract** — implement exactly what it says
- **All production data comes from snapshot DB** — never access
  production devices
- Config push always uses `discard now` + base64 pipe + `2>&1` — see
  `references/LAB_REFERENCE.md` § Config Push
- Show commands: use `exec_on_node` with `"bash -c 'sr_cli ... 2>&1'"`
- `deploy_lab` handles CLAB REST API bugs automatically
- Never destroy a lab without confirming the lab name
- Every session must clean up — if cleanup fails mid-way, still
  attempt it before reporting failure

## References (load on demand)

- `references/LAB_REFERENCE.md` — schema, CLAB API, SRL CLI (interface / BGP / OSPF), verified patterns, multi-node adaptation, sandbox policy
- `prompts/system.md` — full workflow rules and mandatory tool sequence
- See also `../references/CAB_WORKFLOW.md` and
  `../references/CAB_REPORT_FORMAT.md` (referenced by system.md at the
  relevant workflow steps)
