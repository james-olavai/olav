# Services integration guide

Reference for the `services` agent (v0.18.1). Read via
`get_static_context('SERVICES_API_GUIDE')` when the agent is in
`on_intent` / `lazy` mode.

## `.olav/config/services.yaml` layout

```yaml
services:
  netbox:
    endpoint: https://netbox.internal/api
    auth_type: bearer              # none | bearer | basic
    auth_token_env: NETBOX_TOKEN   # env var holding the secret
    default_headers:
      Accept: application/json

  clab_lab1:
    endpoint: http://lab1.local:8080
    auth_type: none
    kind: containerlab             # hint for deploy/stop_service
```

## Tool cheat-sheet

### `register_service`

```python
register_service(
    name="netbox-stage",
    endpoint="https://netbox.stage.example.com/api",
    auth_type="bearer",
    auth_token_env="NETBOX_STAGE_TOKEN",
)
```

Appends to `services.yaml`. Returns `{status, path, entry}`. Refuses to
overwrite existing names — operator must remove the old entry first.

### `api_request`

```python
api_request(
    service="netbox",
    method="GET",
    path="/api/dcim/devices/",
    params={"site": "DC1", "limit": 50},
)
```

Auth is auto-resolved from `services.yaml`. Write methods require
`--enable-api-write` on the CLI. First page caps at 50 rows (ARCH-18
#2 compact mode); pass `page_size=-1` to auto-follow pagination.

### `deploy_service` / `stop_service`

```python
deploy_service(name="clab_lab1")
stop_service(name="clab_lab1")
```

Looks up the `kind` hint in `services.yaml` and calls the matching
launcher. Emits HITL prompts for destructive actions.

## Typical flows

- **New NetBox dev instance:**
  `register_service(…)` → `api_request("<new>", path="/api/status/")`
  to verify → done.
- **Spin up a CLAB lab:**
  already-registered name → `deploy_service(name=…)` → poll with
  `api_request` if the lab exposes health endpoints.
- **Sanity check a running integration:**
  `api_request("<name>", method="GET", path="/")` — most services
  accept an anonymous `GET /`.

## NetBox data import pattern

Use this pattern whenever importing network data (interfaces, devices,
prefixes, VLANs, etc.) that already exists in the OLAV DuckDB databases.

### Threshold rule: 5 items

| Volume | Flow |
|---|---|
| ≤ 5 items | Query DB → build payload → `api_request` PATCH/POST directly |
| > 5 items | Query DB → map schema → save CSV audit file via `write_compose_file` → `api_request` bulk POST |

The 5-item threshold keeps small-model context manageable. Never try to
hold a large payload in the LLM context — write it to a file first.

### Bulk import (> 5 items)

NetBox REST API accepts JSON arrays for bulk creation:

```python
# Step 1 — query OLAV DB (via netops execute_sql or query_evidence)
# Step 2 — map fields to NetBox schema
# Step 3 — save audit CSV (optional but recommended)
write_compose_file(
    name="netbox-import",
    content="device,interface,type,mac\n...",
    filename="audit/interfaces_import.csv",
)
# Step 4 — bulk POST (NetBox accepts JSON array, NOT CSV via API)
api_request(
    service="netbox",
    method="POST",
    path="/api/dcim/interfaces/",
    body=[
        {"device": {"name": "sw01"}, "name": "GigabitEthernet0/0", "type": "1000base-t"},
        {"device": {"name": "sw01"}, "name": "GigabitEthernet0/1", "type": "1000base-t"},
        ...
    ],
)
```

NetBox returns `[{id, name, ...}, ...]` — check every item's `id` is set
(null id = validation error on that row).

### Small update (≤ 5 items)

```python
# Single create
api_request(service="netbox", method="POST", path="/api/dcim/interfaces/",
            body={"device": {"name": "sw01"}, "name": "Gi0/2", "type": "1000base-t"})

# Single update (requires NetBox object id)
api_request(service="netbox", method="PATCH", path="/api/dcim/interfaces/42/",
            body={"description": "uplink to core"})
```

### Fetch NetBox schema (for field mapping)

```python
# Full OpenAPI spec — large, cache result
api_request(service="netbox", method="GET", path="/api/schema/")

# Schema for one endpoint only
api_request(service="netbox", method="GET", path="/api/schema/?path=/api/dcim/interfaces/")
```

Cache the schema in a `write_compose_file` call if you need to refer to
it multiple times — do not re-fetch on every mapping step.

### Common NetBox endpoint paths

| Data type | Create/List | Update/Delete |
|---|---|---|
| Devices | `/api/dcim/devices/` | `/api/dcim/devices/{id}/` |
| Interfaces | `/api/dcim/interfaces/` | `/api/dcim/interfaces/{id}/` |
| IP Addresses | `/api/ipam/ip-addresses/` | `/api/ipam/ip-addresses/{id}/` |
| Prefixes | `/api/ipam/prefixes/` | `/api/ipam/prefixes/{id}/` |
| VLANs | `/api/ipam/vlans/` | `/api/ipam/vlans/{id}/` |
| Sites | `/api/dcim/sites/` | `/api/dcim/sites/{id}/` |
