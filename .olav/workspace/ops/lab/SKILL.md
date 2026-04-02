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
  - run_python_simulation  # Build topology YAML, translate configs, push via httpx, diff
  - deploy_lab             # POST CLAB YAML → auto fix_srl_topology + create_srl_links
  - call_api               # CLAB REST: GET/DELETE labs
  - exec_on_node           # Verify node state after config push
  - create_srl_links       # Build SR Linux link definitions from topology
  - fix_srl_topology       # Patch CLAB topology YAML for SR Linux constraints
static_context:
  - path: ./references/LAB_REFERENCE.md
---

## Flow

```
1. execute_sql       → discover devices + topology + configs from DB
2. run_python_simulation → build topology YAML + translate configs to SRL CLI
3. deploy_lab        → POST YAML → lab up (handles CLAB REST API bugs automatically)
4. run_python_simulation → push configs via httpx exec API, verify convergence
5. exec_on_node      → spot-check BGP/OSPF neighbors
6. iterate           → run_python_simulation to diff + fix gaps autonomously
```

## Key Rules

- **All production data comes from snapshot DB** — never access production devices
- **run_python_simulation is the primary workhorse** — query DB, build YAML, push config, diff
- Inside sandbox: use `db.query(sql)` for DB access, `httpx` for CLAB exec API calls
- Config format: SRL sr_cli candidate transaction — see LAB_REFERENCE.md for syntax
- deploy_lab handles CLAB REST API bugs (fix_srl_topology + create_srl_links) — use it, not call_api, for deployment
- If lab already exists (409): `call_api DELETE /api/v1/labs/{name}` then retry deploy_lab
- Never destroy a lab without confirming the lab name with the user

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
