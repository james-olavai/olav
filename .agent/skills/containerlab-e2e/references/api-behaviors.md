# ContainerLab REST API — Confirmed Behaviors

**API Base**: `http://192.168.100.12:8080/api/v1`  
**Version confirmed**: `clab-0.73.0-api-0.2.1`

---

## Authentication

```bash
# Endpoint:  POST /login   (NOT /auth)
curl -s -X POST http://192.168.100.12:8080/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"yhvh","password":"jAmes92323"}'
# Response: {"token": "<jwt>"}

# Use in requests:
Authorization: Bearer <jwt>
```

Token is stored in `CLAB_API_TOKEN` env var. `get_auth_headers()` in `models.py`
reads it. **Refresh the token whenever you get 401 errors.**

---

## Deploy Lab  (`POST /labs`)

**Request body**:
```json
{
  "topologyContent": { ... },   // JSON dict from yaml.safe_load() — NOT a YAML string
  "reconfigure": false
}
```

**CRITICAL**: `topologyContent` must be a parsed JSON object. Passing a raw YAML
string causes a 400 or silent topology parse error.

**Response body** is a dict keyed by lab name:
```json
{
  "bgp-2node": {
    "containers": [
      {
        "name": "clab-bgp-2node-r1",
        "kind": "srl",
        ...
      }
    ]
  }
}
```

Extract lab name: `lab_name = next(iter(response_body))`.  
Extract containers: `response_body[lab_name]["containers"]`.  
Container naming: `clab-{lab_name}-{node_name}`.

---

## Exec API  (`POST /labs/{lab_name}/exec`)

**Request body**:
```json
{
  "command": ["bash", "-c", "echo hello"],
  "Command": "bash -c 'echo hello'"   // some versions accept string
}
```

**CRITICAL — NodeFilter is COMPLETELY IGNORED**:
- The API accepts `NodeFilter`, `nodeFilter`, `node_filter` — all silently ignored
- Every exec command runs on **ALL containers** in the lab, not a subset
- Workaround: embed the hostname into the logic of the command itself

**Response body**:
```json
{
  "clab-bgp-2node-r1": [
    {
      "stdout": "...",
      "stderr": "...",
      "return-code": 0
    }
  ],
  "clab-bgp-2node-r2": [...]
}
```

---

## Exec Patterns Used in This Skill

### Write per-node config files to ALL containers (Step 4)
```bash
# Write each node's config as a uniquely-named temp file
bash -c 'echo <b64_r1> | base64 -d > /tmp/olav_<rid>_r1.cfg && echo <b64_r2> | base64 -d > /tmp/olav_<rid>_r2.cfg'

# Then apply hostname-conditionally in a second exec
bash -c 'H=$(hostname); cfg=/tmp/olav_<rid>_${H}.cfg; [ -f "$cfg" ] && sr_cli < "$cfg" 2>&1 || echo SKIP_$H'
```

Why two exec calls? The write command succeeds on all nodes (idempotent).
The apply command uses `$(hostname)` to pick the right file.

### Collect BGP state (Step 7)
```bash
bash -c 'echo "show network-instance default protocols bgp neighbor" | sr_cli'
```

### Health-check for readiness (Step 5 fallback)
```bash
hostname
```
If exec returns rc=0 with a non-empty hostname, node is alive.

---

## Destroy Lab  (`DELETE /labs/{lab_name}`)

Returns 200 on success. Verify by `GET /labs/{lab_name}` — should 404 after deletion.

Also verify residual containers/networks/volumes via Docker inspect if needed.

---

## Management IPs

- Allocated by `compile_scenario.py` starting at `192.168.100.110` (MGMT_CLOUD_START_OFFSET)
- **NOT reachable from 192.168.100.50 (CI host)** — only accessible from the clab
  server's Docker bridge network
- All readiness checks and data collection use the exec API instead of SSH/direct connect

---

## Common Error Patterns

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | JWT expired | Re-run the token refresh curl command |
| `topologyContent parse error` | Passed YAML string not dict | `yaml.safe_load(content)` before posting |
| All nodes get both configs / ARP duplicate on SRL | NodeFilter ignored | Already handled by hostname-conditional pattern |
| BGP stays in `active` state | Missing `transport local-address` | Add to `20_bgp.cfg` for each node |
| `destination IP does not match local-address 0.0.0.0` | Same as above (SRL BGP log) | Same fix |
| `return-code: 1` on apply | SRL CLI syntax error in .cfg | Check config syntax, remove unsupported commands |
