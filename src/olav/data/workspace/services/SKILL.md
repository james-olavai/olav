---
name: services
description: "Service lifecycle management — register APIs, deploy/stop containers, make authenticated HTTP calls against services.yaml endpoints (NetBox, InfluxDB, Gitea, ContainerLab, any custom HTTP API)"
agent_type: api
tools:
  - execute_skill_script
  - web_search
scripts:
  - name: register_service
    description: "Register a new API service endpoint in services.yaml"
    file: register_service.py
  - name: deploy_service
    description: "Deploy a container service via ContainerLab or Docker"
    file: deploy_service.py
  - name: stop_service
    description: "Stop a running container service"
    file: stop_service.py
  - name: api_request
    description: "Make HTTP requests to a registered service"
    file: api_request.py
  - name: docker_compose
    description: "Run docker-compose operations (up/down/ps/logs) for a service"
    file: docker_compose.py
static_context:
  - path: ./references/SERVICES_API_GUIDE.md
static_context_mode: on_intent
metadata:
  rubric_middleware: true
  type: agent
  version: 1.0.0
  category: platform-services
---

## services — service lifecycle (platform agent root skill)

Register and operate the external systems OLAV integrates with.

## Script quick-reference

- `register_service(name, endpoint, auth_type, auth_token_env)` — append a
  new entry to `.olav/config/services.yaml`; refuses to overwrite existing names.
- `deploy_service(name, ...)` — start a container service (CLAB / Docker).
- `stop_service(name)` — graceful shutdown of a running service. Pass
  `action=list` to list all managed services.
- `api_request(service, method, path, ...)` — authenticated HTTP call
  to a service configured in services.yaml; write ops gated by
  `--enable-api-write`.
- `docker_compose(subcommand, service_dir, timeout)` — run an allowlisted
  docker compose subcommand (ps, logs, up, down, restart, stop, start, pull,
  build, config, images, version, ls). `exec` and `run` are blocked.
  `service_dir` is relative to project root; defaults to project root.

## Typical flows

- "Add a new NetBox instance" → `register_service` then `api_request` to verify.
- "Spin up a lab topology" → `deploy_service(name="clab_topo1")`.
- "Query NetBox devices" → `api_request("netbox", path="/api/dcim/devices/")`.
- "Stop the staging InfluxDB" → `stop_service("influxdb-staging")`.

## Boundary

- **Do NOT** query infrastructure databases (NetBox IPAM, InfluxDB metrics) — that's the `devops` agent's `infra`.
- **Do NOT** generate scripts — that's the `devops` agent's `scripts`.
- When a service name is unknown, call `api_request` with `service=<name>` and let the
  tool error surface the registered list.
