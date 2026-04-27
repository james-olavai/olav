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
  - run_python_simulation  # SANDBOX — call olav.core.cab + olav.core.lab Python API: tcf_load_for_lab, generate_clab_topology, generate_srl_lab_config, generate_srl_rollback_config, tcf_record_lab_run (per ADR-0007)
  - save_lab_config        # Save node config to disk for later deploy_and_push_lab
  - deploy_and_push_lab    # Deploy lab + push saved configs atomically
  - deploy_lab             # POST CLAB YAML → auto fix_srl_topology + create_srl_links
  - push_node_config       # Push SRL CLI config to a node (REMOTE CLAB — NOT docker exec)
  - exec_on_node           # Verify node state after config push
  - create_srl_links       # Build SR Linux link definitions from topology
  - fix_srl_topology       # Patch CLAB topology YAML for SR Linux constraints
  - destroy_lab            # Tear down CLAB lab — always call on completion or failure
static_context:
  - path: ./references/LAB_REFERENCE.md
# R86 — on_intent (~4K tokens, largest reference of all).
# LAB_REFERENCE only matters for CAB / lab-deploy flows; baking it
# on EVERY ops-orchestrator invocation that happens to route to
# ops-lab is wasteful.  Lazy-loaded; agent fetches via
# get_static_context when the workflow actually starts a lab.
static_context_mode: on_intent
---

## Flow (TCF-native, R91 Python-first per ADR-0007)

The deterministic generators (`tcf_load_for_lab`,
`generate_clab_topology`, `generate_srl_lab_config`,
`generate_srl_rollback_config`, `tcf_record_lab_run`) are Python
functions in `olav.core.cab` / `olav.core.lab`. **Call them via
`run_python_simulation`**, not as MCP tools — they're not in the
agent's tool list anymore.

```
0.  run_python_simulation:
        from olav.core.cab import tcf_load_for_lab
        out = tcf_load_for_lab("<spec_path>")
        # → r88_args + r89_args + post_check + tvt schedule
        #   (Pydantic validates; FK errors surface here)

1.  run_python_simulation:
        from olav.core.lab import generate_clab_topology
        yaml_content = generate_clab_topology(**out["r88_args"])

2.  run_python_simulation:
        from olav.core.lab import generate_srl_lab_config
        cfg = json.loads(generate_srl_lab_config(**out["r89_args"]))
        # cfg["configs"] = {lab_node: 22-line srl_cli}

3.  save_lab_config(node=<lab_node>, config_lines=cfg["configs"][lab_node].splitlines())
    [one call per node — MCP, writes to deploy contract path]

4.  deploy_and_push_lab(yaml_content=<step 1>, configs={})
5.  exec_on_node — run each post_check.command, compare to expected_pattern

5b. ROLLBACK VALIDATION — only when apply tests PASSED:
    a. run_python_simulation:
           from olav.core.lab import generate_srl_rollback_config
           rb = json.loads(generate_srl_rollback_config(**out["r89_args"]))
    b. push_node_config(node=<lab_node>, config=rb["configs"][lab_node])
    c. exec_on_node — verify reversion (BGP gone, no IPv4 on subif).

6.  format_and_export — standalone CAB Lab Report (.md)
7.  run_python_simulation:
        from olav.core.cab import tcf_record_lab_run
        tcf_record_lab_run("<spec_path>", verdict=..., lab_name=...,
            tvt_test_ids=[...], tvt_actual_lab=[...], tvt_status=[...],
            journal=[...])
        # writes verdict + journal + per-test actuals back to TCF
8.  destroy_lab — ALWAYS, even on failure
```

**⚠️ NEVER hand-write `yaml_content`** — small models omit
`links:` and silently break BGP. Always import + call
`olav.core.lab.generate_clab_topology` from the sandbox.

**⚠️ NEVER hand-translate prod CLI to SRL CLI** — always import
+ call `olav.core.lab.generate_srl_lab_config`. It deterministically
renders the 22-line SRL skeleton; hand-translation hits SRL YANG
rejections (`connectivity-endpoint`, missing `peer-group`, etc.)
and never converges.

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
