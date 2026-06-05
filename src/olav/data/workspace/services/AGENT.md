---
name: services
description: "OLAV service-integration platform agent — register API services, deploy/stop containers (Docker / ContainerLab), docker-compose ops, and authenticated HTTP calls against services.yaml endpoints (NetBox, InfluxDB, Gitea, any custom HTTP API)"
system_prompt_file: prompts/services.md
route_keywords:
  - register service api endpoint services.yaml netbox influxdb gitea
  - deploy container service containerlab clab docker
  - docker compose up down ps logs service
  - stop shutdown running container service
  - authenticated http request api call registered service
task_return_direct: true
tools:
  - execute_skill_script
  - web_search
metadata:
  rubric_middleware: true
  type: agent
  version: 1.0.0
  category: platform-services
---

## Services — OLAV service-integration platform agent

The `services` agent owns the lifecycle of the external systems OLAV
integrates with: register them in `services.yaml`, deploy/stop their
containers, run docker-compose operations, and make authenticated HTTP
calls against them. It is a **platform-core** capability used across every
domain (netops, audit, future domains) — not network-specific.

Capability detail lives in this agent's root `SKILL.md` (5 scripts:
`register_service`, `deploy_service`, `stop_service`, `docker_compose`,
`api_request`).

## CLI usage

```bash
olav --agent services "register a NetBox instance at http://netbox.lan"
olav --agent services "deploy the clab_topo1 lab topology"
olav --agent services "docker-compose up the influxdb stack"
olav --agent services "GET /api/dcim/devices/ from netbox"
```

## Scope boundary

- Querying infrastructure **data** (NetBox IPAM records, InfluxDB metrics) →
  `olav --agent devops`
- Generating automation scripts (bash/python/ansible) → `olav --agent devops`
- Platform self-management (health, logs, cron, skill install) →
  `olav --agent admin`
- Network operations (BGP/OSPF/topology/config) → `olav --agent netops`
