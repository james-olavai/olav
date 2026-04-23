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
---

## Flow

```
1. [SKIP DB query — change plan provides all needed IPs/ASNs directly]
2. save_lab_config(r1) → use EXACT template from system.md Step 2 (substitute IPs/ASNs only)
3. save_lab_config(r4) → use EXACT template from system.md Step 3 (substitute IPs/ASNs only)
4. deploy_and_push_lab → deploy lab + push configs atomically (configs={} auto-loads saved files)
5. exec_on_node        → spot-check BGP neighbor state (show network-instance default protocols bgp neighbor)
6. REPORT              → PASS or FAIL with evidence (see CAB Decision rules below)
7. destroy_lab         → ALWAYS call destroy_lab(lab_name=...) — cleanup, even on failure
```

**⚠️ CRITICAL: NEVER use run_python_simulation or run_python_code to GENERATE SRL config lines.**
SRL config syntax is version-specific. Use the EXACT templates in system.md Steps 2-3.
Substituting IPs and AS numbers from the change plan is the ONLY allowed modification.

**⚠️ CAB is a validation gate, NOT a fix-it loop.**
- If `deploy_and_push_lab` returns `dry_run_failures`: fix with `push_node_config` **ONCE** using system.md template, then report FAIL if still failing.
- Step 6 is REPORT, not "iterate and fix". After 1 failed retry → report → destroy_lab → stop.

## CAB Decision Rules

**✅ PASS** — all checks converge. Output evidence table + Design Commentary (🟠/🔵 items even on pass).

**❌ FAIL** — any check fails. Output:
1. Evidence table with what passed/failed
2. Design Commentary with failure classification:
   - 🔴 **BLOCKER** — design error (e.g., iBGP without IGP, wrong AS type)
   - 🟡 **PREREQ** — missing prerequisite not in plan (e.g., no route to peer loopback)
   - 🟠 **SYNTAX** — platform version constraint (e.g., feature not in SRL v26.3.1)
3. Concrete revision instructions for Sim
4. Destroy lab

On FAIL: do NOT try alternatives to make it work. Report → stop → destroy lab.

## Key Rules

- **The change plan is the contract** — implement exactly what it says, nothing more
- **All production data comes from snapshot DB** — never access production devices
- Config push: always use `discard now` + base64 pipe + `2>&1` — see LAB_REFERENCE.md
- Show commands: use `exec_on_node` with `"bash -c 'sr_cli ... 2>&1'"`
- deploy_lab handles CLAB REST API bugs — use it for deployment
- Never destroy a lab without confirming the lab name

## Test Environment Cleanup

**Every test session must clean up after itself — no leftover containers.**

After completing any test or validation:
1. Call `deploy_lab` with `action="destroy"` to tear down the lab
2. Verify no containers remain: `exec_on_node` will return error if lab is gone (expected)
3. If destroy fails, escalate — do NOT leave orphaned containers

```
# Cleanup sequence after any test run:
deploy_lab({"action": "destroy", "lab_name": "<name>"})
```

If the user interrupts mid-test or an error occurs mid-way:
- Still attempt cleanup before reporting failure
- Report what was cleaned up and what may remain (if cleanup also failed)

## Sandbox Network Policy

**`network_isolation=False`** — lab sandbox REQUIRES external network access.

The sandbox code pushes configs to the ContainerLab exec API via httpx:
```python
execute_in_sandbox(code, network_isolation=False)  # lab agent always uses this
```

This is intentional: the lab agent's primary function is to push configurations to
running containers and verify convergence, which requires HTTP access to the CLAB
REST API (typically `http://clab-api:8080`). Do NOT set `network_isolation=True`
for lab sandbox tasks — it will cause all httpx calls to fail with Connection refused.

## Verified Working Patterns

Merged from v0.18.0 ops-lab-standalone. Canonical patterns exercised end-to-end
against real CLAB deployments:

- **Fixed SRL image**: always deploy with `ghcr.io/nokia/srlinux:24.10.1`. Older
  tags drop the YANG models the config-push relies on; newer tags haven't been
  regression-tested against the topology recipe.
- **cEOS ZTP disable**: the first `deploy_lab` step writes a startup-config shim
  that disables ZTP, otherwise the container hangs for ~3 minutes on boot.
- **CLAB REST API ≤ 0.74.1 topology.yml bug**: the API creates a *directory* at
  `topology.yml` instead of a file — workaround via nsenter + privileged helper
  container; see `references/LAB_REFERENCE.md`.

## Multi-Node Topology Adaptation

Merged from v0.18.0 ops-lab/AGENT.md. The lab skill adapts to the node count in
the topology recipe — 2 / 4 / 6 / 8-node variants share the same tool surface
but differ in:

- **veth pair allocation**: cEOS requires the management-network BGP workaround
  when > 2 nodes (single mgmt net can't carry all eBGP sessions).
- **CLAB_LABEL_CLAB_NODE_NAME**: mandatory in every multi-node scenario;
  `deploy_lab` exports it automatically before the config push.
- **Convergence wait**: scales linearly with node count (~15 s per cEOS node,
  ~30 s per SRL node). The `verify` step in `deploy_lab` honours this.
