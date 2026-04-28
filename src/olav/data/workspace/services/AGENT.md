---
name: services
kind: Agent
description: "Service integrations — register APIs, deploy/stop containers, issue authenticated HTTP calls against services.yaml endpoints"
version: "1.0.0"
system_prompt_file: prompts/system.md
route_keywords:
  - deploy service
  - stop service
  - register service
  - api request
  - service registry
  - services.yaml
  - netbox
  - influxdb
  - gitea
  - containerlab
static_context:
  - path: ./references/SERVICES_API_GUIDE.md
static_context_mode: on_intent
---

# Services Workspace (v0.18.1)

Dedicated agent for **service integrations** — the things that live in
`.olav/config/services.yaml` and have a lifecycle: register → deploy →
call → stop.

## Capabilities

- **Register** a new API service (`register_service`) — appends to
  `services.yaml` with optional bearer / basic auth.
- **Deploy** container services (`deploy_service`) — launches ContainerLab
  / Docker stacks.
- **Stop** container services (`stop_service`) — graceful shutdown.
- **Call** any registered service (`api_request`) — authenticated HTTP
  with compact-by-default response truncation (ARCH-18 #2).

## When to use this agent vs core

- **Use `services/`** for anything touching `services.yaml` or the list
  of external systems OLAV integrates with (NetBox, InfluxDB, Gitea,
  ContainerLab, …).
- **Stay in `core/`** for data queries (`execute_sql`, `recall_memory`)
  and general orchestration.

## Delegation

Other agents reach this one via:

```python
olav_delegate("services", "register a new NetBox service at https://...")
```

## Tools

See ``SKILL.md``. Full docs via ``tool_help('<tool_name>')``.
