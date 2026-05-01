---
name: devops_infra
kind: Agent
description: "Infrastructure integrations — query NetBox (DCIM/IPAM), InfluxDB (metrics), generate bulk change scripts. Spun out from ops sub-agent → top-level (2026-05-01)."
version: "1.0.0"
system_prompt_file: prompts/system.md
route_keywords:
  - netbox
  - dcim
  - ipam
  - influxdb
  - metrics
  - inventory
  - bulk change
  - 网管
  - 资源
  - 库存
static_context:
  - path: ./references/netbox_dcim_api.md
  - path: ./references/netbox_ipam_api.md
  - path: ./references/influxdb_netops_Query_api.md
  - path: ./references/influxdb_netops_Health_api.md
static_context_mode: on_intent
---

# Infrastructure Integrations Agent

Top-level agent (was `ops/infra/` sub-agent, promoted 2026-05-01).

## Capabilities

* Query NetBox DCIM (devices / racks / cables) + IPAM (prefixes / VLANs).
* Query InfluxDB metrics (router CPU / link utilization / etc.).
* Generate bulk change scripts (e.g. add 50 prefixes to NetBox)
  for user review before applying.

## Workflow

See `prompts/system.md` and the API references in `references/`.

## Cross-agent dependencies

* For service registration / auth token mgmt: delegate to `services`.
* For device CLI / fresh snapshots: delegate to `ops` (collect/analyze).
