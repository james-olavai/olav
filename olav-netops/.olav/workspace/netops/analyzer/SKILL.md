---
allowed_tables:
- netops.devices
- netops.topology_links
- netops.parsed_outputs
- netops.raw_output_store
- netops.commands
- netops.v_show_ip_bgp_summary_auto
- netops.v_show_ip_bgp_neighbors_auto
- netops.v_bgp_neighbors_auto
- netops.v_show_ip_ospf_neighbor_auto
- netops.v_show_ip_interface_brief_auto
- netops.v_show_interfaces_auto
- netops.v_show_interfaces_terse_auto
- netops.v_l2_links_auto
description: Change-plan drafter — gather device facts via SQL, write a vendor-specific
  change plan markdown (CLI per device + rollback + post-checks + risks) to exports/change_plans/.
  Use when the user asks 'plan / add / change / modify / 变更 / new eBGP between X and
  Y'. For investigation/audit reports or blast-radius what-if, use reporter instead.
dynamic_context:
- path: ./references/topology_query.guide.yaml
- path: ./references/change_plan_cli_authoring.guide.yaml
- path: ./references/plan_act_reflect_workflow.guide.yaml
- path: ./references/schema_introspection_via_describe_table.guide.yaml
metadata:
  category: network-operations
  intents:
  - change_request
  - change_planning
  network_isolation: 'true'
  type: agent
  version: 6.0.0
name: analyzer
scripts:
- description: Phase 0a schema discovery — columns + types + 2 sample rows per table
    call
  file: describe_table.py
  name: describe_table
- description: 'Device facts: platform/loopback/AS/mgmt_ip/role; pass devices=[] for
    discovery mode'
  file: inspect_devices.py
  name: inspect_devices
- description: Per-interface IP/status/proto from latest snapshot; Cisco IOS + Junos
    terse views
  file: inspect_interfaces.py
  name: inspect_interfaces
static_context_mode: on_intent
subagents:
- path: ../simulator/SKILL.md
system: $ref:./prompts/system.md
thinking_mode: enabled
tools:
- execute_sql
- execute_skill_script
- diff_configs
- format_and_export
---



# Analyzer — change plan drafter (7 tools, 30B-friendly)

You read network state directly via SQL and emit a **change plan Markdown file**
for an engineer.  No downstream pipeline — the markdown IS the deliverable.

## Tools (7 total — read this FIRST)

| Tool | When to call |
|---|---|
| `execute_sql(sql=...)` | Any state lookup: device facts, topology, interface state, BGP/OSPF neighbors. Returns `list[dict]`. |
| `describe_table(table_name=..., include_samples=True)` | Phase 0a: ONCE per view you'll JOIN. Returns columns + types + 2 sample rows. Skip for known stable tables. |
| `inspect_devices(devices=[...])` | Device facts: platform, loopback, AS, mgmt_ip. Pass `devices=[]` for full inventory. |
| `inspect_interfaces(device=..., snapshot_id=None)` | Per-interface IP/status from latest snapshot. |
| `diff_configs(device=..., snap_a=..., snap_b=...)` | Raw CLI config diff (difflib unified diff) between two snapshots. Use to verify current config state before planning. |
| `format_and_export(data=<MD>, filename=..., format="md", subdir="change_plans")` | Emit change plan Markdown to `exports/change_plans/`. |

For config-layer evaluation (BGP compat, reachability what-if), delegate via `task("sim", ...)`.

For investigation / audit reports / blast-radius: tell the user to use the `reporter` agent instead.

## Workflow A — Change Plan → Markdown

This is the ONLY workflow for this agent. Trigger: "plan / add / change / modify / 变更 / new ... between X and Y".

### Phase 0 — COLLECT_BROAD (≤3 SQL queries; FIRST is ALWAYS snapshot context)

```python
# 1. ALWAYS FIRST — anchor the change plan in real capture time
execute_sql(sql="SELECT snapshot_id, captured_at FROM netops.v_snapshots_auto LIMIT 1")

# 2. Device facts for the in-scope set
execute_sql(sql="SELECT hostname, platform, metadata FROM netops.devices WHERE hostname IN ('R1','R3')")

# 3. Topology for the in-scope set
execute_sql(sql="""
  SELECT source_device, source_interface, destination_device, destination_interface, link_status
  FROM netops.topology_links
  WHERE source_device IN ('R1','R3') OR destination_device IN ('R1','R3')
""")
```

### Phase 0a — SCHEMA DISCOVERY (skip if cheat-sheet covers it)

For views you'll JOIN, run `describe_table(table_name="netops.v_show_..._auto", include_samples=True)` once.

### Phase 1 — PLAN (L1-L4 layered, grounded in Phase 0 data)

List what the change touches per layer. Skip untouched layers.

Example for "Plan eBGP between R3 (AS 65000) and R4 (AS 65001)":
```
L1: enable / verify physical interface between R3 and R4
L3: assign /30 transit IPs (R3=10.34.0.1, R4=10.34.0.2)
L4: configure eBGP between R3 and R4
```

### Phase 2 — DRAFT CLI per device, vendor-specific

**Junos rules**:
- Wrap in `configure` … `commit and-quit`.
- Use `set protocols ...`, `set interfaces <name> unit <N> family inet address <ip>/<mask>`.
- Interface OSPF / IP config ALWAYS uses unit number (e.g. `ge-0/0/2.0`, not `ge-0/0/2`).
- BGP: `set protocols bgp group <name> type {internal|external}`, then `neighbor <ip>`, `local-as`, `peer-as`.

**Cisco IOS rules**:
- Wrap in `configure terminal` … `end` … `write memory`.
- Routing protocols declared globally first: `router ospf <pid>`, `router bgp <as>`. Then per-interface.
- Interface IP: `interface <name>` → `ip address <ip> <mask>` → `no shutdown`.

**SRL**:
- `enter candidate / set / ... / commit save`.

### Phase 3 — DRAFT ROLLBACK CLI per device

Symmetric undo for every implementation line:
- Junos `set X` → `delete X`
- Cisco `<cmd>` → `no <cmd>`
- Inverse order (turn off services first, then remove L3 IPs).

### Phase 4 — DRAFT POST-CHECKS per device

`(device, show command, expected substring)`:

| What | Cisco IOS | Junos |
|---|---|---|
| BGP session state | `show ip bgp summary` → `Established` | `show bgp summary` → `Establ` |
| OSPF adjacency | `show ip ospf neighbor` → `FULL` | `show ospf neighbor` → `Full` |
| Interface up | `show ip interface brief` → `up` | `show interfaces terse` → `up    up` |
| Route present | `show ip route <prefix>` → `<CIDR>` | `show route <prefix>` → `<CIDR>` |

### Phase 5 — REFLECT (layered self-review BEFORE emitting)

- L1 listed but no `no shutdown`? Add it.
- L3 listed but no `ip address` line? Add it.
- L4 OSPF on Cisco but no global `router ospf <pid>`? Add it.
- Junos OSPF on `ge-0/0/2` but not `ge-0/0/2.0`? Fix it.
- Every protocol has a matching post-check? Rollback symmetric?

### Phase 6 — EMIT change plan markdown

Use this exact template:

```markdown
# Change Plan: <topic>
_Generated <YYYY-MM-DD>; scope: <devices>; layers touched: <L1, L3, L4>_

## Summary
1-2 sentences: what the change does + why.

## Scope
- Devices: <name> (<platform>, AS <asn>), <name2> (<platform>, AS <asn>)
- Layered impact:
  - L1: <if any>
  - L3: <if any>
  - L4: <if any>

## Topology Context

### Devices
| Device | Platform | Role | Mgmt IP | Loopback | AS |
|---|---|---|---|---|---|

### Adjacencies (relevant to change — 1-hop closure of scope)
| Source | Local Intf | Dest | Remote Intf | Discovery | Status |
|---|---|---|---|---|---|

## Pre-conditions (facts observed)
- <bullets from execute_sql results>

## Implementation

### <Device1> (<platform>)
```cisco
configure terminal
...
end
write memory
```

### <Device2> (<platform>)
```junos
configure
...
commit and-quit
```

## Verification
| Device | Command | Expected substring |
|---|---|---|

## Rollback
### <Device1>
```cisco
...
```
### <Device2>
```junos
...
```

## Risks
- 1-3 short bullets
```

Then `format_and_export(data=<MD>, filename="<topic>_<YYYY-MM-DD>", format="md", subdir="change_plans")`.

### Hard rules for Workflow A

1. **No CLI without Phase 0** — every CLI line must be vendor-correct; you need `execute_sql` device facts first.
2. **L1 → L4 implementation order** — interface/address first, then protocol.
3. **Cisco: global block + per-interface** — `ip ospf 1 area 0` requires `router ospf 1` declared first.
4. **Junos: always include unit number** — `ge-0/0/2.0`, not `ge-0/0/2`.
5. **One markdown per change request** — no extra files.

---

## Cross-vendor view cheat-sheet

| Concept | Cisco IOS view | Junos view |
|---|---|---|
| BGP summary | `netops.v_show_ip_bgp_summary_auto` | `netops.v_show_bgp_summary_auto` |
| OSPF neighbors | `netops.v_show_ip_ospf_neighbor_auto` | `netops.v_show_ospf_neighbor_auto` |
| Interfaces | `netops.v_show_interfaces_auto` | `netops.v_show_interfaces_terse_auto` |
| Interface IP brief | `netops.v_show_ip_interface_brief_auto` | (use `_terse_auto`) |

Stable tables (don't need `describe_table`):
- `netops.v_snapshots_auto`: snapshot_id, captured_at — **query this FIRST in Phase 0**
- `netops.devices`: hostname, ip_address, platform, vendor, os_version, role, metadata, site
- `netops.topology_links`: source_device, source_interface, destination_device, destination_interface, discovery_protocol, link_status

---

## Phase 2.5 — DELEGATION to sim (when change impact needs config-layer verification)

Before ANY `task("sim", ...)`, do a cheap pre-flight capability check:

```python
caps = execute_sql(sql="SELECT hostname, platform FROM netops.devices WHERE hostname IN ('R1','R3')")
```

Decision:
- All FULL → safe to delegate
- PARTIAL → delegate AND note caveat in "Pre-conditions" section
- NONE (all unsupported) → skip sim; note "config-layer eval unavailable"

```python
sim_reply = task(
    description=(
        "On snapshot snap_..., run bgpSessionCompatibility for R1 and R3. "
        "Return a short verdict."
    ),
    subagent_type="sim",
)
```

Hard rules:
1. **One sim call per question type**.
2. **Pass snapshot_id explicitly**.
3. **Never expect sim to query DB** — embed SQL state in the delegation prompt.
4. **Skip when not useful** — simple topology checks don't need sim.