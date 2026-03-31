---
name: ops-lab
description: >
  ContainerLab digital twin validation (emulation). Deploys real SR Linux
  containers via CLAB REST API, pushes OpenConfig-derived config from the
  snapshot DB, runs protocol convergence assertions, and emits a CAB
  evidence artifact. Use for Change Advisory Board (CAB) gate validation
  before production deployment.
metadata:
  version: 1.0.0
  type: agent
  category: network-operations
  intents: [cab_validation, digital_twin, change_validation, lab_emulation]
scripts_dir: ./scripts
tools:
  - run_e2e          # Full E2E pipeline: deploy → configure → assert → destroy
  - clab_cab         # CLABCABAgent: build_reduced_topology + evaluate_assertions
  - cab_config_extractor  # Schema-aware OC config extraction from snapshot DB
static_context:
  - path: ./references/api-behaviors.md
  - path: ./references/SCHEMA_REFERENCE.md
---

## Overview

The Lab skill provides **full digital twin emulation** using ContainerLab with SR Linux nodes.
Config is extracted directly from the snapshot database (no Jinja2 templates), translated to
SRL CLI via the OC→SRL renderer, and pushed to the live lab via the CLAB exec API.

## Two-Stage Validation Architecture

```
Fast path (ops-sim):   change_intent → NetworkX graph model → milliseconds
Emulation path (ops-lab): change_intent → CLAB deploy → real BGP/OSPF → minutes
```

## Capabilities

| Protocol/Feature | Snapshot View | SRL Configurable | Status |
|-----------------|--------------|-----------------|--------|
| BGP eBGP neighbors | v_bgp_neighbors_auto | ✅ | ✅ Tested |
| BGP global AS + router-id | v_bgp_neighbors_auto | ✅ | ✅ Tested |
| Interface IPs (CIDR) | v_interfaces_auto | ✅ | ✅ Tested |
| OSPF adjacency | v_ospf_neighbors | ✅ | ❌ P1 |
| IS-IS adjacency | v_isis_adjacencies | ✅ | ❌ P2 |
| EVPN/VXLAN | v_evpn_instances | ✅ | ❌ P2 |

## Usage

```bash
uv run python .olav/workspace/ops/lab/scripts/run_e2e.py \
  --scenario .olav/workspace/ops/lab/scenarios/cab_digital_twin_bgp.yaml
```
