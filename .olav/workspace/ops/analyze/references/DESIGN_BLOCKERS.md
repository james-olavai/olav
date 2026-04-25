# Design Feasibility — common BLOCKER patterns

Load this when the user asks to design a change (BGP session, OSPF
adjacency, IGP migration, etc.). Always query these from the DB — never
assume or invent values.

## BLOCKER / WARN table

| Required info | DB source | Severity |
|---|---|---|
| Peer AS number | `netops.v_bgp_neighbors_auto.neighbor_as` | 🔴 BLOCKER — cannot design session type |
| BGP link IP | JSON-extract from `netops.parsed_outputs` where `command LIKE 'show%ip interface%'`; fallback `netops.v_l2_links_auto` for the physical link | 🔴 BLOCKER — Phase 0 must assign IPs |
| Direct physical link | `netops.v_l2_links_auto WHERE source_device=X AND destination_device=Y` | 🟡 WARN — not a blocker when intermediate hops route |
| IGP between peers | `netops.v_ospf_neighbors_auto` | 🔴 BLOCKER for iBGP |
| Route to loopback | JSON-extract from `parsed_outputs` where `command='show ip route'` — no materialised view yet | 🔴 BLOCKER for multihop eBGP |
| MTU matching at L3 links | JSON-extract `parsed_outputs` where `command='show interfaces'` — no dedicated view | 🟡 WARN — OSPF / BGP TCP MSS problems |
| Loopback IPs distinct per device | JSON-extract `parsed_outputs` interfaces rows where interface name LIKE `'%oopback%'` or `'lo0%'` | 🟡 WARN — router-id collisions |
| Neighbor reachability (any route) | JSON-extract from `parsed_outputs` where `command LIKE 'show%ip route%'` searching `next_hop` | 🔴 BLOCKER — no IP forwarding |

## Rules

1. If ANY BLOCKER is found → state it as **Phase 0 prerequisite** in the
   change plan. Do NOT assume or invent values.
2. WARN items → list in Design Commentary (🟡 PREREQ in CAB flow).
3. All DB queries use existing tables / views — never modify schema during
   feasibility check.
