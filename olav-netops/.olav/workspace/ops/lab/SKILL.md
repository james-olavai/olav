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
  - tcf_load_for_lab       # R90 Phase 3: read TCF spec, derive R88/R89 args + tvt schedule
  - generate_clab_topology # Build CLAB YAML from netops.v_l2_links_auto — call BEFORE deploy_and_push_lab
  - generate_srl_lab_config # R89: deterministic prod→SRL CLI translator — call BEFORE save_lab_config
  - generate_srl_rollback_config # R90 Phase 6: deterministic SRL rollback CLI (delete /...) — call AFTER post-check PASS to validate rollback can revert cleanly
  - run_python_simulation  # Build topology YAML, translate configs
  - save_lab_config        # Save node config to disk for later deploy_and_push_lab
  - deploy_and_push_lab    # Deploy lab + push saved configs atomically
  - deploy_lab             # POST CLAB YAML → auto fix_srl_topology + create_srl_links
  - push_node_config       # Push SRL CLI config to a node (REMOTE CLAB — NOT docker exec)
  - exec_on_node           # Verify node state after config push
  - create_srl_links       # Build SR Linux link definitions from topology
  - fix_srl_topology       # Patch CLAB topology YAML for SR Linux constraints
  - tcf_record_lab_run     # R90 Phase 3: write verdict + journal + tvt actuals back to TCF (replaces append_validation_footer)
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

## Flow (TCF-native, R90 Phase 3+)

```
0.  tcf_load_for_lab(spec_path=...)
       → derives r88_args + r89_args + post_check + tvt schedule
       (replaces markdown spec parsing — Pydantic validates the
        spec; FK errors surface here, not deep in deploy)
1.  generate_clab_topology(**r88_args) → yaml_content w/ links:
2.  generate_srl_lab_config(**r89_args) → {lab_node: 22-line srl_cli}
3.  save_lab_config(node=<lab_node>, config_lines=configs[lab_node].splitlines())
    [one call per node]
4.  deploy_and_push_lab(yaml_content=<step 1>, configs={})
5.  exec_on_node — run each post_check.command, compare to expected_pattern
    [collect actuals into TVT actuals list]

5b. ROLLBACK VALIDATION (R90 Phase 6) — only when apply tests PASSED:
    a. generate_srl_rollback_config(**r89_args)
         → {lab_node: 7-line delete CLI}
    b. push_node_config(node=<lab_node>, config=rollback_configs[lab_node])
       [one call per node]
    c. exec_on_node — verify reversion:
         - show network-instance default protocols bgp neighbor → empty
         - show interface ethernet-1/N detail → no IPv4 address on subif 0
       Add a TVT row T_rollback_clean (severity blocker if rollback
       is part of the contract) with status PASS/FAIL.

6.  format_and_export — standalone CAB Lab Report (.md, human readable)
7.  tcf_record_lab_run(spec_path=..., verdict=..., tvt_test_ids=[...],
        tvt_actual_lab=[...], tvt_status=[...], journal_json=..., ...)
       → writes verdict + journal + per-test actuals back to the TCF
       (replaces append_validation_footer — structured, not markdown)
8.  destroy_lab — ALWAYS, even on failure
```

**⚠️ NEVER hand-write `yaml_content`** — small models routinely
omit the `links:` section, which silently breaks BGP (containers
have no veth pair, ARP fails, BGP stuck in `active`/`connect`).
Use `generate_clab_topology` to read `netops.v_l2_links_auto` and
emit a deploy-ready YAML with both `nodes:` AND `links:`.

**⚠️ NEVER hand-translate prod CLI to SRL CLI for `save_lab_config`** —
Always call `generate_srl_lab_config(devices=[...], change_intent={...})`
and pass the returned `configs[node].splitlines()` straight to
`save_lab_config`.  The tool deterministically renders the 22-line
SRL skeleton (interface triad, system0 loopback, network-instance
binding, routing-policy, BGP afi-safi + ebgp-default-policy +
peer-group + neighbor) from a structured intent.  Hand-translation
hits SRL YANG rejections (`connectivity-endpoint`, `group type
external`, missing `peer-group`, wrong `afi-safi` placement) and
never converges.

**⚠️ NEVER use `run_python_simulation` / `run_python_code` to GENERATE
SRL config lines.**  Use `generate_srl_lab_config` (above) instead;
it's the deterministic Type B generator.

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
