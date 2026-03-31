# Lab Reference — Schema + SRL CLI

## Database Schema

**Source data (qualify with `netops.`):**

| Table | Key Columns |
|---|---|
| `netops.devices` | `hostname`, `ip_address`, `platform`, `role`, `site` |
| `netops.topology_links` | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `discovery_protocol`, `link_status` |
| `netops.parsed_outputs` | `device_name`, `command`, `parsed_data` (JSON array), `snapshot_id` |
| `netops.raw_output_store` | `device_name`, `command`, `raw_output` (text), `snapshot_id` |

**Views (no prefix):**

| View | Key Columns |
|---|---|
| `v_interfaces_auto` | `device_name`, `interface`, `ip_address`, `prefix_length`, `admin_status` |
| `v_bgp_neighbors_auto` | `device_name`, `neighbor_ip`, `neighbor_as`, `state`, `prefixes_received` |
| `v_ospf_neighbors_auto` | `device_name`, `neighbor_id`, `neighbor_ip`, `interface`, `state` |
| `v_topo_links_clean` | `src`, `source_interface`, `dst`, `destination_interface`, `discovery_protocol` |
| `v_device_neighbors_summary` | `device_name`, `connected_device`, `discovery_protocol`, `link_status` |

**Config extraction priority per device:**
1. `netops.raw_output_store WHERE command = 'show running-config'` — full running config (best)
2. `netops.parsed_outputs` — structured TextFSM records per command
3. `v_*_auto` views — flat, single-field queries

---

## CLAB API

Config file: `.olav/workspace/ops/lab/config/config.json` — `{"base_url", "username", "password"}`
Auth: `POST {base_url}/login` → `{"username": ..., "password": ...}` → `{"token": "..."}`
All requests: `Authorization: Bearer <token>`

| Endpoint | Purpose |
|---|---|
| `GET  /api/v1/labs` | List running labs |
| `POST /api/v1/labs` | Deploy lab — body: `{"content": "<topology YAML>"}` |
| `DELETE /api/v1/labs/{name}` | Destroy lab |
| `POST /api/v1/labs/{name}/nodes/{node}/exec` | Run command on node |

**Exec endpoint body:**
```json
{"cmd": "sr_cli", "stdin": "sr_cli -c 'show version'"}
```

**Config push via exec:**
```json
{"cmd": "sr_cli", "stdin": "enter candidate\n/ interface ethernet-1/1 admin-state enable\ncommit now\n"}
```

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
/ interface ethernet-1/1 subinterface 0 ipv4 address 192.168.1.1/30
/ network-instance default interface ethernet-1/1.0
```

### OSPF
```
/ network-instance default protocols ospf instance default admin-state enable
/ network-instance default protocols ospf instance default area 0.0.0.0 interface ethernet-1/1.0
/ network-instance default protocols ospf instance default area 0.0.0.0 interface ethernet-1/1.0 interface-type point-to-point
```

### BGP
```
/ network-instance default protocols bgp admin-state enable
/ network-instance default protocols bgp autonomous-system 65001
/ network-instance default protocols bgp router-id 10.0.0.1
/ network-instance default protocols bgp neighbor 10.0.0.2 peer-as 65002
/ network-instance default protocols bgp neighbor 10.0.0.2 admin-state enable
```

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

If using `call_api` to deploy manually, run `fix_srl_topology` + `create_srl_links` after every POST.
