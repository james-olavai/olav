---
name: services
description: "Service integrations + platform admin — register/deploy/stop services, manage cron, workspace health, bulk ingest, analyze logs, write workspace files."
tools:
  - register_service
  - deploy_service
  - stop_service
  - api_request
  # 2026-05-01: admin sub-agent folded into services (was at
  # core/admin/) — these 5 tools moved here so platform-mgmt and
  # service-integration ops live in one cohesive agent.
  - workspace_health
  - bulk_ingest
  - analyze_logs
  - manage_cron
  - write_workspace_file
static_context:
  - path: ./references/SERVICES_API_GUIDE.md
static_context_mode: on_intent
---

# services skill

Register and operate the external systems OLAV integrates with
(NetBox / InfluxDB / Gitea / ContainerLab / any custom HTTP API).

Call `tool_help('<tool>')` for the full per-tool schema.

## Tool quick-reference (one-liners)

- `register_service(name, endpoint, auth_type, auth_token_env)` — append a
  new entry to ``.olav/config/services.yaml``; refuses to overwrite.
- `deploy_service(name, ...)` — start a container service (CLAB / Docker).
- `stop_service(name)` — graceful shutdown of a running service.
- `api_request(service, method, path, ...)` — authenticated HTTP call
  to a service configured in services.yaml; write ops gated by
  ``--enable-api-write``.

## Typical flows

- "Add a new NetBox instance" → `register_service` then `api_request` to verify.
- "Spin up a lab topology" → `deploy_service(name="clab_topo1")`.
- "Query NetBox devices" → `api_request("netbox", path="/api/dcim/devices/")`.

## Reflection

When a tool errors, retry with corrections before surfacing. Unknown
service names → fall back to `tool_help('api_request')` for the
registered-service list.
