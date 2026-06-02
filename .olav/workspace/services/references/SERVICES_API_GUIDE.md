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
