# Raw Fallback Policy (R72)

When a user asks about device data, **try all three tiers** before giving up.

## Tier 1: Semantic views (structured, fastest)

Built by the view_builder at `/netops_init` time from `view_recipes`.
Schemas are canonical — field names and value formats are stable.

| View | Concept | When to use |
|---|---|---|
| `netops.v_bgp_neighbors_auto` | BGP sessions | "show me BGP neighbors", "who's not Established" |
| `netops.v_ospf_neighbors_auto` | OSPF adjacencies | "OSPF state", "which interfaces carry OSPF" |
| `netops.v_l2_links_auto` | CDP/LLDP links | "topology", "what's connected to R1" |
| `netops.devices` | Inventory | "all devices", "list platforms" |

**If the view returns 0 rows**, that does NOT mean the data doesn't exist —
it may mean the parser for that command didn't run (or ran but couldn't
parse the user's specific device model). Go to Tier 2.

## Tier 2: `parsed_outputs` JSON (structured, per-command)

```sql
SELECT device_name, command, parsed_data
  FROM netops.parsed_outputs
 WHERE command = 'show ip route'
   AND snapshot_id = (SELECT MAX(snapshot_id) FROM netops.parsed_outputs);
```

`parsed_data` is a JSON array of dicts like:

```json
[
  {"protocol": "B", "prefix": "10.1.0.0/24", "next_hop": "10.0.0.1", "metric": 20},
  {"protocol": "O", "prefix": "10.2.0.0/24", "next_hop": "10.0.0.2", "metric": 110}
]
```

Field names come from the parser that generated it; they follow
ntc-templates conventions (lowercase). **As of R72, interface names,
IPs, ASNs, and MACs are auto-canonicalised at ingest time** — you'll
see `GigabitEthernet0/0` not `Gi0/0`.

**If `parsed_data` is NULL**, the parser couldn't handle that device's
output. Go to Tier 3.

## Tier 3: Raw output (last resort — read the text yourself)

```sql
SELECT raw_output
  FROM netops.raw_output_store
 WHERE device_name = 'R1'
   AND command = 'show running-config';
```

You get the exact CLI text the device emitted. **Read it and extract
the answer by reasoning.**

### Example: user asks "what's R1's BGP router-id?"

1. Tier 1: `SELECT router_id FROM netops.v_bgp_neighbors_auto WHERE device='R1'`
2. If empty → Tier 2: `SELECT parsed_data FROM netops.parsed_outputs WHERE command='show bgp summary' AND device_name='R1'`
3. If `parsed_data` NULL → Tier 3: `SELECT raw_output FROM netops.raw_output_store WHERE command='show bgp summary' AND device_name='R1'`, then locate the `"BGP router identifier 2.2.2.2"` line and extract `2.2.2.2`

### Example: user asks about VLANs (no view exists)

Skip Tier 1 (no `v_vlans_auto` view). Try Tier 2 directly:
`SELECT parsed_data FROM netops.parsed_outputs WHERE command='show vlan brief'`.
If NULL → Tier 3: read raw text, parse the VLAN table yourself.

## When to suggest `/learn_cmd`

If you find yourself frequently hitting Tier 3 for the same `(platform,
command)` pair AND the user is doing **aggregate** queries
("count BGP Established across all devices"), suggest:

```
olav --agent netops_ops '/learn_cmd "show bgp summary" --device R2'
```

This will persist a parser so future queries get Tier-1 / Tier-2 speed.
Don't suggest it for ad-hoc one-off questions — Tier 3 is fine for those.
