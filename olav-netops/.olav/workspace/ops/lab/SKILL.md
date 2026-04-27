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
  - generate_clab_topology # Build CLAB YAML from netops.v_l2_links_auto — call BEFORE deploy_and_push_lab
  - run_python_simulation  # Build topology YAML, translate configs
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

## Flow

```
1. generate_clab_topology(nodes=[...], lab_name=...) → returns yaml_content (with links:)
2. save_lab_config(r1) → use EXACT template from references/CAB_WORKFLOW.md Step 2
3. save_lab_config(r4) → use EXACT template from references/CAB_WORKFLOW.md Step 3
4. deploy_and_push_lab(yaml_content=<from step 1>, configs={}) → deploy + push atomically
5. exec_on_node        → spot-check BGP neighbor state
6. REPORT              → PASS or FAIL (format: references/CAB_REPORT_FORMAT.md)
7. destroy_lab         → ALWAYS call destroy_lab(lab_name=...) — cleanup, even on failure
```

**⚠️ NEVER hand-write `yaml_content`** — small models routinely
omit the `links:` section, which silently breaks BGP (containers
have no veth pair, ARP fails, BGP stuck in `active`/`connect`).
Use `generate_clab_topology` to read `netops.v_l2_links_auto` and
emit a deploy-ready YAML with both `nodes:` AND `links:`.

**⚠️ NEVER use `run_python_simulation` / `run_python_code` to GENERATE
SRL config lines.**  SRL syntax is version-specific — use the EXACT
templates in `references/CAB_WORKFLOW.md`.  Substituting IPs / AS
numbers is the ONLY allowed modification.

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
