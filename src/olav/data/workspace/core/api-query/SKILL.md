---
name: api-query
description: "API service queries — lightweight read-only HTTP requests to registered services (NetBox, InfluxDB, Grafana, etc.), health checks, report export"
tools:
  - execute_skill_script
  - execute_sql
  - web_search
  - format_and_export
scripts:
  - name: api_request
    description: "Make HTTP requests to a registered service"
    file: api_request.py
  - name: service_health
    description: "Check health and reachability of a registered service"
    file: service_health.py
static_context:
  - path: ./references/netbox_dcim_api.md
  - path: ./references/netbox_ipam_api.md
  - path: ./references/influxdb_netops_Query_api.md
static_context_mode: on_intent
metadata:
  category: api-integration
  rubric_middleware: true
  type: agent
  version: 1.1.0
---

# API Query Agent

Handle lightweight read-only API requests. For bulk operations or script
generation, tell the user to use `olav --agent devops`.

## Service discovery first

Before calling `api_request`, check what's registered:

```sql
execute_sql("SELECT name, endpoint, readonly_only FROM api_registry.services")
execute_sql("SELECT endpoint FROM api_registry.services WHERE name = 'netbox'")
```

Use the endpoint from DuckDB — never guess or hardcode URLs.

## Read-only scope

Only GET requests. For write operations → `olav --agent devops`.

## Schema reference

Use `references/` docs for correct NetBox endpoint paths and parameters.
NetBox device query: `api_request(service="netbox", path="/api/dcim/devices/", params={...})`
InfluxDB query: `api_request(service="influxdb_netops", path="/api/v2/query", ...)`
