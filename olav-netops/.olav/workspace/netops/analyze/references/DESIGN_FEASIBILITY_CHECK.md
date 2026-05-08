# Mandatory design feasibility check (BGP / routing changes)

Load and run this BEFORE writing any change plan that involves a
new BGP session, routing protocol, or peer relationship.  A plan
without this check is **incomplete**.

For the table of which conditions are BLOCKER vs WARN, see
`DESIGN_BLOCKERS.md` in the same directory.  This file is the
runnable Python implementation.

## BGP prerequisite checklist (run inside `run_python_simulation`)

```python
# Run this for every proposed BGP change.
# Query ACTUAL values from DB — never assume or hardcode AS numbers,
# IPs, or interface names.

issues = []
r1 = "R1"   # local device, replace with real
r4 = "R4"   # peer device,  replace with real

# 0. AS numbers — flag BLOCKER if unknown.
local_bgp = db.query("""
    SELECT DISTINCT neighbor_as AS local_as, device
    FROM netops.v_bgp_neighbors_auto WHERE device = ?
""", [r1])
peer_bgp = db.query("""
    SELECT DISTINCT neighbor_as AS peer_as, device
    FROM netops.v_bgp_neighbors_auto WHERE device = ?
""", [r4])

# Try the inverse: if R4 reports R1 as a neighbor, infer R1's AS from
# its IP showing up in some interface.  No `v_interfaces_auto` view
# exists — extract from parsed_outputs JSON instead.
r1_as_from_peer = db.query("""
    SELECT b.neighbor_as
    FROM netops.v_bgp_neighbors_auto b
    WHERE b.device = ?
      AND b.neighbor_ip IN (
        SELECT json_extract(parsed_data, '$[*].IP_ADDRESS')
        FROM netops.parsed_outputs
        WHERE device_name = ? AND command LIKE '%ip interface%'
      )
""", [r4, r1])

if not local_bgp and not r1_as_from_peer:
    issues.append(f"BLOCKER: {r1} AS unknown.  Cannot design BGP session.")
    issues.append(f"  Fix: collect BGP config from {r1} before designing.")

if not peer_bgp:
    issues.append(f"BLOCKER: {r4} AS unknown.  Cannot design eBGP session.")
    issues.append(f"  Fix: collect BGP config from {r4} before designing.")
    issues.append(f"  Note: if {r4} has no BGP yet, AS must be assigned — "
                  "include it as Phase 0 in the plan.")

# 1. Determine session type (only if both AS known).
if local_bgp and peer_bgp:
    local_as = local_bgp[0]["local_as"]
    peer_as  = peer_bgp[0]["peer_as"]
    bgp_type = "iBGP" if local_as == peer_as else "eBGP"
else:
    bgp_type = "unknown"

# 2. iBGP requires IGP between the peers.
if bgp_type == "iBGP":
    igp = db.query("""
        SELECT COUNT(*) AS cnt FROM netops.v_ospf_neighbors_auto
        WHERE device IN (?, ?)
    """, [r1, r4])
    if not igp or igp[0]["cnt"] == 0:
        issues.append("BLOCKER: iBGP requires IGP (OSPF/IS-IS) between peers — "
                      "none found in DB.")
        issues.append("  Fix: add OSPF between peers BEFORE designing iBGP.")

# 3. BGP link IP — JSON-extract because no v_interfaces_auto view exists.
direct_link = db.query("""
    SELECT * FROM netops.v_l2_links_auto
    WHERE source_device = ? AND destination_device = ?
""", [r1, r4])
if not direct_link:
    issues.append(f"BLOCKER: No direct physical link between {r1} and {r4} "
                  "in topology DB.")
    issues.append(f"  Verify intermediate hops required.")
elif bgp_type == "eBGP":
    issues.append("SUGGEST: direct physical link exists — direct-link eBGP is "
                  "simpler than multihop.")

_result["feasibility_issues"] = issues
```

## Dependency ordering

If any BLOCKER is found, the change plan **must** include the
prerequisite fix as Phase 0, or explicitly state it as an
out-of-scope dependency:

```
Phase 0 — Prerequisites: IGP, static routes, loopbacks
Phase 1 — Protocol changes: BGP sessions
Phase 2 — Policy: route-maps, filters
Phase 3 — Cutover: remove old paths
```

Never write Phase 1 without first verifying Phase 0 is in place or
included in the plan.
