# CAB Workflow — Step-by-step lab validation

The mandatory 7-step sequence expanded with SRL v24.10.1 templates.
Load this reference every time you execute a change-plan validation.

---

## Step 1 — Discover (execute_sql)

```sql
SELECT hostname, ip_address, platform FROM netops.devices;

SELECT source_device, source_interface, destination_device, destination_interface
  FROM netops.topology_links WHERE link_status = 'up';

SELECT device_name, raw_output FROM netops.raw_output_store
  WHERE command = 'show running-config'
    AND snapshot_id IN (SELECT MAX(snapshot_id) FROM netops.raw_output_store GROUP BY device_name);
```

## Step 2 — Save R1 config (save_lab_config)

> ⚠️ **COPY THIS TEMPLATE EXACTLY.** Do NOT use `run_python_simulation`
> or any code generation to build SRL config. Substitute only IPs and
> AS numbers from the change plan.

```json
{
  "lab_name": "r1-r4-ebgp-direct",
  "node": "r1",
  "config_lines": [
    "set / interface ethernet-1/1 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30",
    "set / interface system0 subinterface 0 admin-state enable",
    "set / interface system0 subinterface 0 ipv4 admin-state enable",
    "set / interface system0 subinterface 0 ipv4 address 1.1.1.1/32",
    "set / network-instance default interface ethernet-1/1.0",
    "set / network-instance default interface system0.0",
    "set / routing-policy prefix-set loopbacks prefix 1.1.1.1/32 mask-length-range exact",
    "set / routing-policy policy export-bgp statement 10 match prefix-set loopbacks",
    "set / routing-policy policy export-bgp statement 10 action policy-result accept",
    "set / routing-policy policy export-bgp default-action policy-result reject",
    "set / network-instance default protocols bgp admin-state enable",
    "set / network-instance default protocols bgp autonomous-system 65000",
    "set / network-instance default protocols bgp router-id 1.1.1.1",
    "set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable",
    "set / network-instance default protocols bgp ebgp-default-policy import-reject-all false",
    "set / network-instance default protocols bgp group ebgp-r4 peer-as 65001",
    "set / network-instance default protocols bgp group ebgp-r4 export-policy [export-bgp]",
    "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-group ebgp-r4"
  ]
}
```

## Step 3 — Save R4 config (save_lab_config)

```json
{
  "lab_name": "r1-r4-ebgp-direct",
  "node": "r4",
  "config_lines": [
    "set / interface ethernet-1/1 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable",
    "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.2/30",
    "set / interface system0 subinterface 0 admin-state enable",
    "set / interface system0 subinterface 0 ipv4 admin-state enable",
    "set / interface system0 subinterface 0 ipv4 address 4.4.4.4/32",
    "set / network-instance default interface ethernet-1/1.0",
    "set / network-instance default interface system0.0",
    "set / routing-policy prefix-set loopbacks prefix 4.4.4.4/32 mask-length-range exact",
    "set / routing-policy policy export-bgp statement 10 match prefix-set loopbacks",
    "set / routing-policy policy export-bgp statement 10 action policy-result accept",
    "set / routing-policy policy export-bgp default-action policy-result reject",
    "set / network-instance default protocols bgp admin-state enable",
    "set / network-instance default protocols bgp autonomous-system 65001",
    "set / network-instance default protocols bgp router-id 4.4.4.4",
    "set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable",
    "set / network-instance default protocols bgp ebgp-default-policy import-reject-all false",
    "set / network-instance default protocols bgp group ebgp-r1 peer-as 65000",
    "set / network-instance default protocols bgp group ebgp-r1 export-policy [export-bgp]",
    "set / network-instance default protocols bgp neighbor 10.0.0.1 peer-group ebgp-r1"
  ]
}
```

## Step 4 — Deploy + Push (deploy_and_push_lab)

Call deploy_and_push_lab after ALL saved configs.  Pass `configs: {}`
— it auto-loads from the saved temp files:

```json
{
  "lab_name": "r1-r4-ebgp-direct",
  "yaml_content": "name: r1-r4-ebgp-direct\ntopology:\n  nodes:\n    r1:\n      kind: nokia_srlinux\n      image: ghcr.io/nokia/srlinux:24.10.1\n    r4:\n      kind: nokia_srlinux\n      image: ghcr.io/nokia/srlinux:24.10.1\n  links:\n  - endpoints: [\"r1:e1-1\", \"r4:e1-1\"]\n",
  "configs": {},
  "wait_seconds": 40
}
```

### CLAB YAML rules (wrong format = 500 error; do NOT search for tags)

```yaml
name: r1-r4-ebgp-direct
topology:
  nodes:
    r1:
      kind: nokia_srlinux        # ← MUST be nokia_srlinux (NOT srlinux, NOT srl)
      image: ghcr.io/nokia/srlinux:24.10.1   # ← FIXED tag
    r4:
      kind: nokia_srlinux
      image: ghcr.io/nokia/srlinux:24.10.1
  links:
  - endpoints: ["r1:e1-1", "r4:e1-1"]   # ← two strings, use e1-1 (NOT eth1)
```

- `endpoints` — list of TWO strings, never concatenated
- interface MUST be `e1-1`, `e1-2`, … (NOT `eth1`)
- node kind MUST be `nokia_srlinux`
- image MUST be `ghcr.io/nokia/srlinux:24.10.1` — never `latest`
- Do NOT set `startup-config:` or `mgmt_ipv4:` — push config via exec API

### 🛑 SUCCESS DETECTION & STOP RULES — read before every call

- `"committed": true` = **COMPLETE SUCCESS** — stop, do NOT call again
- `"lab_reused": true` + `"committed": true` = lab already running, config pushed — **COMPLETE SUCCESS**
- `"ALREADY RUNNING"` in message = **COMPLETE SUCCESS**
- **NEVER call deploy_and_push_lab more than TWICE per session**
  (once for fresh deploy, once for retry if committed=false)
- If you have already seen `deployed: true` — lab exists, do NOT deploy again

### Step 4b — Config Retry (push_node_config) — ONLY on dry_run_failed

If `deploy_and_push_lab` returns `dry_run_failed` or `committed: false`:
1. Lab IS already deployed — **do NOT call deploy_and_push_lab again**
2. Call `push_node_config` with the **EXACT template from Step 2/3**
3. **MAX 1 retry per node.** If it fails again → FAIL, destroy_lab, stop

---

## SRL v24.10.1 syntax reference

### Interface naming
- Physical subinterface bind: `ethernet-1/1.0` (dot notation)
- Loopback: `system0` (NOT `lo0`, NOT `loopback0`)
- Set commands: `set / interface ethernet-1/1 ...` — no `name` keyword

### Routing-policy — WRONG vs CORRECT

| ❌ WRONG (Junos/IOS style) | ✅ CORRECT (SRL v24.10.1) |
|---|---|
| `policy-options { ... }` | `set / routing-policy ...` (flat set commands) |
| `policy-statement EXPORT { ... }` | `set / routing-policy policy EXPORT ...` |
| `term 10 { from { ... } }` | `set / routing-policy policy EXPORT statement 10 match ...` |
| `entry 10 { ... }` | `set / routing-policy policy EXPORT statement 10 ...` |
| `from { prefix-list LOOPBACKS; }` | `set / routing-policy policy EXPORT statement 10 match prefix-set LOOPBACKS` |
| `then accept;` | `set / routing-policy policy EXPORT statement 10 action policy-result accept` |
| `prefix-list LOOPBACKS { ... }` | `set / routing-policy prefix-set LOOPBACKS prefix 10.0.0.1/32 mask-length-range exact` |

Rules:
- **ALWAYS use `prefix-set`** to match specific prefixes — NEVER
  `match protocol host`, `match protocol direct`, or `match protocol local`
- `action policy-result accept` (NOT `action accept`)
- Always add `default-action policy-result reject`
- Bind: `set / network-instance default protocols bgp group <grp> export-policy [<policy-name>]`
- The `[...]` brackets are literal SRL syntax — required

Minimal working R1 policy:
```
set / routing-policy prefix-set LOOPBACKS prefix 10.0.0.1/32 mask-length-range exact
set / routing-policy policy EXPORT-BGP statement 10 match prefix-set LOOPBACKS
set / routing-policy policy EXPORT-BGP statement 10 action policy-result accept
set / routing-policy policy EXPORT-BGP default-action policy-result reject
set / network-instance default protocols bgp group ebgp export-policy [EXPORT-BGP]
```

### BGP peer configuration
- eBGP vs iBGP determined AUTOMATICALLY by comparing local-AS and
  peer-as — do NOT set `type external` or `type internal`
- `type external` is NOT valid SRL — omit entirely
- `policy-options` is NOT valid SRL — use `routing-policy`
- Peer-group: `set / network-instance default protocols bgp group <grp> ...`
- Neighbor→group binding: `set / network-instance default protocols bgp neighbor <ip> peer-group <grp>`
- Required minimal per neighbor: peer-group (with peer-as + export-policy)
- Do NOT add `admin-state enable` to the bgp group — not needed
- BGP admin-state at bgp level: `set / network-instance default protocols bgp admin-state enable`
- **⚠️ CRITICAL:** SRL v24.10.1 defaults to
  `ebgp-default-policy import-reject-all true` — received eBGP routes
  are REJECTED unless you add
  `set / network-instance default protocols bgp ebgp-default-policy import-reject-all false`.
  Without this line, received routes show `[Rx/0/Tx]` (0 active) and never install.

---

## Step 5 — Verify (exec_on_node)

Pass the `sr_cli` command directly — the tool auto-wraps with
bash+base64 for reliable stdout capture:

```json
{"lab_name": "r1-r4-ebgp-direct", "node": "r1", "command": "sr_cli 'show network-instance default protocols bgp neighbor'"}
```

```json
{"lab_name": "r1-r4-ebgp-direct", "node": "r1", "command": "sr_cli 'show network-instance default route-table ipv4'"}
```

### Show command — WRONG vs CORRECT

| ❌ WRONG | ✅ CORRECT |
|---|---|
| `show network-instance default route-table ipv4 unicast` | `show network-instance default route-table ipv4` |
| `show route-table` | `show network-instance default route-table ipv4` |

Wait **30 seconds** after deploy_and_push_lab returns before running
show commands (BGP needs time to establish).

BGP ESTABLISHED looks like:
`| default | 10.0.0.2 | ebgp-r4 | S | 65001 | established |`

---

## Step 7 — Destroy Lab (destroy_lab tool)

After outputting the CAB Report, always destroy:

```
destroy_lab(lab_name="r1-r4-ebgp-direct")
```

Expected: `{"status": "ok", "destroyed": true, "lab_name": "r1-r4-ebgp-direct"}`

- ❌ NEVER use `run_python_simulation` with `httpx.delete` — blocked by sandbox
- ❌ NEVER use `run_shell("containerlab destroy ...")` — clab CLI is NOT installed locally
- ✅ ONLY `destroy_lab(lab_name=...)` works

**Do NOT end your response with "Lab ready for further testing" or any
similar phrase without first calling `destroy_lab`.** The CAB gate is a
one-shot validation — deploy, validate, report, destroy.
