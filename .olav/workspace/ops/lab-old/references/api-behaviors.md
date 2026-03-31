# ContainerLab REST API — Confirmed Behaviors

**API Base**: `http://192.168.100.12:8080/api/v1`
**Version confirmed**: `clab-0.74.1-api-0.2.2`
**Default credentials**: `admin` / `admin` (verified 2026-03-27)

---

## Authentication

```bash
# Endpoint:  POST /login   (NOT /auth)
curl -s -X POST http://192.168.100.12:8080/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}'
# Response: {"token": "<jwt>"}

# Use in requests:
Authorization: Bearer <jwt>

# Quick token export:
export CLAB_API_TOKEN=$(curl -s -X POST http://192.168.100.12:8080/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
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

**Response body** is a dict keyed by lab name → flat list of node objects:
```json
{
  "olav-exec-test": [
    {
      "name": "r1",
      "container_id": "95f10b8f697a",
      "image": "ceos:4.35.2",
      "kind": "arista_ceos",
      "state": "running",
      "ipv4_address": "172.20.20.3/24",
      "lab_name": "olav-exec-test",
      ...
    },
    { "name": "r2", ... }
  ]
}
```

Extract lab name: `lab_name = next(iter(response_body))`.
Extract nodes: `response_body[lab_name]` is a **flat list** (NOT nested under "containers").
Node short name is `node["name"]` (e.g. `"r1"`) — NOT prefixed with `clab-{lab}-`.

---

## Exec API  (`POST /labs/{lab_name}/exec`)

**Request body** — `command` must be a **plain string** (NOT an array):
```json
{ "command": "hostname" }
{ "command": "Cli -c \"show interfaces\"" }
{ "command": "bash -c 'echo hello'" }
```

Sending `"command": ["bash", "-c", "..."]` returns HTTP 400:
`"cannot unmarshal array into Go struct field ExecRequest.command of type string"`

**CRITICAL — NodeFilter is COMPLETELY IGNORED**:
- The API accepts `NodeFilter`, `nodeFilter`, `node_filter` — all silently ignored
- Every exec command runs on **ALL containers** in the lab, not a subset
- Workaround: embed the hostname into the logic of the command itself

**Response body** — keyed by **container name**:
- `prefix: ""` in topology → short name (`r1`)
- default prefix → full name (`clab-{lab}-r1`)

Both forms appear in practice:
```json
{
  "r1": [
    {
      "cmd": ["hostname"],
      "stdout": "r1\n",
      "stderr": "",
      "return-code": 0
    }
  ],
  "r2": [...]
}
```

**Platform-specific CLI invocation**:
| Platform | Exec command pattern |
|----------|---------------------|
| Nokia SRL | `bash -c 'echo "CMD" \| sr_cli 2>/dev/null'` |
| Arista cEOS | `Cli -c "CMD"` |
| Cisco IOL/IOS/IOS-XE | `bash -c 'CMD 2>/dev/null'` (varies) |
| Juniper (vJunos) | `cli -c "CMD"` (unconfirmed) |

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

## cEOS-Specific Behaviors (Arista cEOS via REST API)

### ZTP (Zero-Touch Provisioning)
cEOS starts with ZTP Active. ZTP blocks ALL configure-mode changes (they succeed silently but are not applied to Sysdb).

**Detection**: `Cli -p 15 -c "show zerotouch"` → `ZeroTouch Mode: Active/Enabled/Disabled`

**Fix**: Cancel ZTP and poll until disabled before applying config:
```bash
Cli -p 15 -c "zerotouch cancel" 2>&1
for i in 1 2 3 4 5 6 7 8; do
  ZS=$(Cli -p 15 -c "show zerotouch" 2>&1)
  echo "$ZS" | grep -qi disabled && break
  sleep 5
done
```
ZTP typically disables within 15-25 seconds (4-5 checks × 5s).

Note: During ZTP active phase (first ~16s), `show zerotouch` returns `% Authorization denied`. This is normal — keep polling.

### Config Application
Apply config via stdin pipe AFTER ZTP is disabled:
```bash
H=$CLAB_LABEL_CLAB_NODE_NAME
cfg=/tmp/olav_$H.cfg
{ printf "configure\n"; cat "$cfg"; printf "end\n"; } | Cli -p 15 2>&1; echo CFG_RC=$?
```

**NEVER use `$(hostname)`** — cEOS changes the container hostname to `localhost` after EOS initializes. Use `$CLAB_LABEL_CLAB_NODE_NAME` instead.

**Write config files to `/tmp/`** (accessible from bash exec context). `/mnt/flash/` is also accessible.

### Link Creation (CRITICAL)
**CLAB REST API does NOT create veth pairs between nodes.** Links defined in the topology dict are silently ignored — no `eth1` or other data interfaces appear inside the containers.

Workaround: Use the Docker management network (172.20.20.0/24) for all data-plane communication. Management IPs are returned in the deploy response (`node["ipv4_address"]`).

For BGP testing:
```python
nodes_in_lab = deploy_resp[lab_name]
mgmt_ips = {n["name"]: n["ipv4_address"].split("/")[0] for n in nodes_in_lab}
# Configure Management0 with these IPs and peer BGP via management network
```

### Management0 IP
Management0 shows `unassigned` in EOS by default. Configure it explicitly:
```
interface Management0
   ip address 172.20.20.x/24
```
The 172.20.20.x value comes from the deploy response `ipv4_address` field.

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
| `cannot unmarshal array` on exec | `command` sent as array | Send `command` as a plain string |
| `bash -c 'show ...'` returns CMD_ERROR on arista | arista has no bash CLI | Use `Cli -c "show ..."` for arista_ceos |
| cEOS BGP stays `Idle(NoIf)` | Ethernet1 not created (CLAB REST API link bug) | Use management network for BGP instead |
| cEOS config applied but not in running-config | ZTP was still active when config was sent | Cancel ZTP + poll until disabled, then apply |
| `$(hostname)` returns wrong node name in cEOS | EOS overrides container hostname to `localhost` | Use `$CLAB_LABEL_CLAB_NODE_NAME` instead |
