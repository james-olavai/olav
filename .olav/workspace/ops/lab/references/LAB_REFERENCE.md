# Lab Reference — Schema + SRL CLI

## Database Schema

**Source data (qualify with `netops.`):**

| Table | Key Columns |
|---|---|
| `netops.devices` | `hostname`, `ip_address`, `platform`, `role`, `site` |
| `netops.topology_links` | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `discovery_protocol`, `link_status` |
| `netops.parsed_outputs` | `device_name`, `command`, `parsed_data` (JSON array), `snapshot_id` |
| `netops.raw_output_store` | `device_name`, `command`, `raw_output` (text), `snapshot_id` |

**Views (all in `netops.` schema):**

| View | Key Columns |
|---|---|
| `netops.v_bgp_neighbors_auto` | `device`, `neighbor_ip`, `neighbor_as`, `local_as`, `router_id`, `state`, `uptime`, `snapshot_id` |
| `netops.v_ospf_neighbors_auto` | `device`, `neighbor_id`, `neighbor_ip`, `interface`, `area`, `state`, `dead_time`, `snapshot_id` |
| `netops.v_l2_links_auto` | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `discovery_protocol`, `link_status`, `snapshot_id` |

⚠️ Interface / ARP / route data — no dedicated view.  JSON-extract from `netops.parsed_outputs.parsed_data` for the matching command.

**Config extraction priority per device:**
1. `netops.raw_output_store WHERE command = 'show running-config'` — full running config (best)
2. `netops.parsed_outputs` — structured TextFSM records per command
3. `v_*_auto` views — flat, single-field queries

---

## CLAB API

Config file: `.olav/workspace/ops-lab/config/config.json` — `{"base_url", "username", "password"}`
Auth: `POST {base_url}/login` → `{"username": ..., "password": ...}` → `{"token": "..."}`
All requests: `Authorization: Bearer <token>`

| Endpoint | Purpose |
|---|---|
| `GET  /api/v1/labs` | List running labs |
| `POST /api/v1/labs` | Deploy lab — body: `{"content": "<topology YAML>"}` |
| `DELETE /api/v1/labs/{name}` | Destroy lab |
| `POST /api/v1/labs/{name}/exec?nodeFilter={container_name}` | Run command on node |

### Topology YAML format (VERIFIED — 2-node SRL example)

**⚠️ SRL interface naming in topology links: use `e1-1`, `e1-2` etc. (NOT `eth1`, NOT `eth0`)**
**⚠️ Node kind: use `nokia_srlinux` (NOT `srlinux` — that alias is not supported on this CLAB version)**
**⚠️ Image: ALWAYS use `ghcr.io/nokia/srlinux:24.10.1` — do NOT web_search for image tags, do NOT use `latest`**

```yaml
name: my-lab
topology:
  nodes:
    r1:
      kind: nokia_srlinux
      image: ghcr.io/nokia/srlinux:24.10.1
    r4:
      kind: nokia_srlinux
      image: ghcr.io/nokia/srlinux:24.10.1
  links:
  - endpoints: ["r1:e1-1", "r4:e1-1"]
```

- Node kind: MUST be `nokia_srlinux` — ❌ NOT `srlinux`, NOT `srl`
- Link endpoint format: `<nodename>:<interface>` where interface MUST match `ethernet-L/P`, `eL-P` (L,P ≥ 1)
- ✅ Valid: `e1-1`, `e1-2`, `ethernet-1/1`, `ethernet-1/2`
- ❌ WRONG: `eth1`, `eth0`, `ge-0/0/0`, `Ethernet0/0` — these will cause deploy to fail
- First link to a node → `e1-1`, second link → `e1-2`, etc.
- The in-container SRL interface for `e1-1` is `ethernet-1/1` (use this in sr_cli config)

**Exec endpoint body (VERIFIED):**
```json
{"command": "sr_cli -c 'show version'"}
```
- `command` is shell-split by CLAB; single-quoted strings are preserved as one arg
- `sr_cli -c 'show version'` → CLAB parses as `["sr_cli", "-c", "show version"]` ✅
- `sr_cli -c 'show network-instance default protocols ospf neighbor'` ✅ (multi-word)

**Multi-line config push via base64 stdin (VERIFIED — required for candidate transactions):**
```python
import base64
config = "enter candidate\nset / interface ethernet-1/1 admin-state enable\ncommit now\n"
b64 = base64.b64encode(config.encode()).decode()
# CRITICAL: always use 2>&1 to capture sr_cli errors (CLAB only captures stdout, not stderr)
command = f"bash -c 'echo {b64} | base64 -d | sr_cli 2>&1'"
# body = {"command": command}
```

**⚠️ CRITICAL — Always use `2>&1` when running sr_cli through CLAB exec:**
- The CLAB exec API only captures **stdout** in the response, NOT stderr
- `sr_cli` prints error messages (commit failures, parse errors) to stderr
- Without `2>&1`, commit failures appear to succeed (rc=0 with empty stderr in response)
- **Always check the merged output for:** `"Commit failed"`, `"Error in /"`, `"Parsing error"`

**Response format:**
```json
{"clab-{lab}-{node}": [{"stdout": "...", "stderr": "...", "return-code": 0, "cmd": [...]}]}
```
- `stderr` field is ALWAYS empty (CLAB doesn't capture it) — use `2>&1` to merge into stdout
- `return-code` is ALWAYS 0 even when sr_cli commands fail (don't rely on it)
- Must scan `stdout` for error strings: `"Commit failed"`, `"Error in /"`, `"Parsing error"`

**NOTE:** `/api/v1/labs/{name}/nodes/{node}/exec` (per-node path) returns 404 — use lab exec endpoint with `nodeFilter` instead.

---

## SR Linux CLI Reference

### Candidate transaction (required for all config changes)
```
enter candidate
<config lines>
commit now
```

### Interface
```
/ interface ethernet-1/1 admin-state enable
/ interface ethernet-1/1 subinterface 0 admin-state enable
/ interface ethernet-1/1 subinterface 0 ipv4 admin-state enable
/ interface ethernet-1/1 subinterface 0 ipv4 address 192.168.1.1/30
/ network-instance default interface ethernet-1/1.0
```
**Note:** Set each attribute on its own line. `address` uses CIDR notation — no `prefix-length` token.

### OSPF (verified working on SRL ixrd3 latest)
```
/ network-instance default protocols ospf instance main admin-state enable
/ network-instance default protocols ospf instance main version ospf-v2
/ network-instance default protocols ospf instance main router-id 1.1.1.1
/ network-instance default protocols ospf instance main area 0.0.0.0 interface ethernet-1/1.0
/ network-instance default protocols ospf instance main area 0.0.0.0 interface ethernet-1/1.0 interface-type point-to-point
```
**Required fields:** `version ospf-v2` and `router-id` are mandatory — omitting either causes commit failure.

### BGP — eBGP direct link (verified working, SRL v26.3.1)

**Mandatory fields for eBGP (commit fails without ALL of these):**
1. `peer-group` — REQUIRED for all neighbors (peer-as on group level, not neighbor level)
2. `afi-safi ipv4-unicast admin-state enable` — at BOTH global BGP level AND group level
3. Do NOT set `transport local-address` unless peer is a loopback — causes TCP source mismatch on direct-link sessions

```
# Global BGP section
/ network-instance default protocols bgp admin-state enable
/ network-instance default protocols bgp autonomous-system 65000
/ network-instance default protocols bgp router-id 1.1.1.1
/ network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable

# Peer group
/ network-instance default protocols bgp group ebgp-peer peer-as 65001
/ network-instance default protocols bgp group ebgp-peer afi-safi ipv4-unicast admin-state enable

# Neighbor — reference the group, set peer-as on GROUP not neighbor
/ network-instance default protocols bgp neighbor 10.0.0.2 admin-state enable
/ network-instance default protocols bgp neighbor 10.0.0.2 peer-group ebgp-peer
```

**⚠️ transport local-address pitfall:** If `transport local-address X.X.X.X` is set on a group, BGP TCP will source from X.X.X.X. If the neighbor address is on a different subnet (e.g., group has `transport local-address 1.1.1.1` but neighbor is `10.0.0.2`), the remote peer will reject the connection (source not matching expected neighbor). For direct-link eBGP, **never set transport local-address**.

**⚠️ Candidate datastore pollution:** If a commit fails mid-push, sr_cli leaves dirty state in the GLOBAL candidate. The next `enter candidate` picks up the stale bad state. **Always start each push session with `discard now` before your config:**
```
enter candidate
discard now
```
Note: `discard` alone (without `now`) fails — must be `discard now`.

**⚠️ ebgp-multihop NOT supported under peer-group in SRL v26.3.1** — `ebgp-multihop` is not a valid attribute under `protocols bgp group`. For loopback-based BGP, use direct-link peer + static routes (or use a different approach).

### BGP — eBGP multihop via loopbacks (CORRECTED — v26.3.1)
```
# 1. Assign loopback IP (system0 is the SRL loopback interface)
/ interface system0 admin-state enable
/ interface system0 subinterface 0 admin-state enable
/ interface system0 subinterface 0 ipv4 admin-state enable
/ interface system0 subinterface 0 ipv4 address 1.1.1.1/32
/ network-instance default interface system0.0

# 2. Add static route toward peer loopback via direct-link next-hop
/ network-instance default static-routes route 4.4.4.4/32 admin-state enable
/ network-instance default static-routes route 4.4.4.4/32 next-hop-group nhg-r4
/ network-instance default next-hop-groups group nhg-r4 nexthop 0 ip-address 10.0.0.2
/ network-instance default next-hop-groups group nhg-r4 nexthop 0 admin-state enable

# 3. eBGP peer toward loopback with multihop
/ network-instance default protocols bgp admin-state enable
/ network-instance default protocols bgp autonomous-system 65000
/ network-instance default protocols bgp router-id 1.1.1.1
/ network-instance default protocols bgp neighbor 4.4.4.4 peer-as 65001
/ network-instance default protocols bgp neighbor 4.4.4.4 admin-state enable
/ network-instance default protocols bgp neighbor 4.4.4.4 afi-safi ipv4-unicast admin-state enable
/ network-instance default protocols bgp neighbor 4.4.4.4 transport local-address 1.1.1.1
/ network-instance default protocols bgp neighbor 4.4.4.4 ebgp-multihop admin-state enable
/ network-instance default protocols bgp neighbor 4.4.4.4 ebgp-multihop maximum-hops 255
```
**Required:** static route to peer loopback via direct link + `local-address` set to own loopback + `ebgp-multihop` enabled + **`afi-safi ipv4-unicast admin-state enable`** (commit fails silently without it, rc=0 but no BGP session).

**IMPORTANT — Config push workflow (NEVER use JSON startup-config in clab YAML):**
1. Deploy bare topology YAML (no `config:` field in nodes)
2. Wait for mgmt plane ready (`exec_on_node` → `sr_cli -c 'show version'`)
3. Push sr_cli text config via `exec_on_node` using base64 pipe
4. Verify with show commands

### Show commands (for verification)
```
show network-instance default protocols bgp neighbor
show network-instance default protocols ospf neighbor
show interface brief
show version
```

### Cisco → SRL translation guide
| Cisco IOS | SRL equivalent |
|---|---|
| `interface GigabitEthernet0/1` | `/ interface ethernet-1/N` (N = link order) |
| `ip address A.B.C.D M.M.M.M` | compute prefix-len → `/ interface ethernet-1/N subinterface 0 ipv4 address A.B.C.D/plen` |
| `router ospf 1` | `/ network-instance default protocols ospf instance default admin-state enable` |
| `network X.X.X.X W.W.W.W area Y` | `/ network-instance default protocols ospf instance default area 0.0.0.Y interface ethernet-1/N.0` |
| `router bgp AS` | `/ network-instance default protocols bgp autonomous-system AS` |
| `neighbor IP remote-as PEER` | `/ network-instance default protocols bgp neighbor IP peer-as PEER` |

---

## CLAB REST API Known Bugs (≤0.74.1)

`deploy_lab` handles both automatically — no manual action needed:
- **topology.yml directory bug** — REST API creates a directory instead of a file; `fix_srl_topology` patches it via nsenter
- **veth pairs not created** — `create_srl_links` injects veth pairs between node network namespaces

---

## Config Push via push_node_config

`push_node_config` is the ONLY correct way to push SRL config to lab nodes. CLAB is REMOTE.
**Never use docker exec, ssh, or containerlab CLI — these are remote and not available locally.**

### Tool signature — use config_lines (list of strings, NOT a single string)

```json
{
  "lab_name": "r1-r4-ebgp-direct",
  "node": "r1",
  "config_lines": [
    "set / interface ethernet-1/1 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30",
    "set / network-instance default interface ethernet-1/1.0",
    "set / network-instance default protocols bgp admin-state enable",
    "set / network-instance default protocols bgp autonomous-system 65000",
    "set / network-instance default protocols bgp router-id 10.0.0.1",
    "set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable",
    "set / network-instance default protocols bgp group ebgp-r4 peer-as 65001",
    "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-group ebgp-r4"
  ]
}
```

⚠️ `config_lines` is a **JSON array of strings** — NOT a single multiline string.
Using a single string with `\n` will cause JSON parsing errors. Always use the list form.

⚠️ **CRITICAL**: SRL BGP requires `afi-safi ipv4-unicast admin-state enable` or commit will fail with
"One of the address families must be enabled." Always include it.

⚠️ **Do NOT include `discard now`** in your config_lines. The tool wraps with just `enter candidate / ... / commit now`.
`discard now` exits candidate mode and breaks all subsequent `set` commands.

The tool automatically wraps your config in `enter candidate / discard now / ... / commit now`.
Returns `{"status": "ok", "stdout": "..."}` on success, `{"status": "error", "stdout": "..."}` on SRL error.

### Full E2E pattern after deploy_lab

```
1. deploy_lab(yaml_content=<topology_yaml>)
2. push_node_config(lab_name="r1-r4-ebgp-direct", node="r1", config_lines=["set / interface ...", ...])
3. push_node_config(lab_name="r1-r4-ebgp-direct", node="r4", config_lines=["set / interface ...", ...])
4. exec_on_node(lab_name="r1-r4-ebgp-direct", node="r1", command="sr_cli -c 'show network-instance default protocols bgp neighbor'")
5. exec_on_node(lab_name="r1-r4-ebgp-direct", node="r4", command="sr_cli -c 'show network-instance default protocols bgp neighbor'")
```

### BGP verification — expected output
```
+-------------------+--------+------------+--------------------+
| Net-Inst          |Peer    |Group       |State               |
+===================+========+============+====================+
| default           |10.0.0.2|ebgp-r4     |established         |
```
