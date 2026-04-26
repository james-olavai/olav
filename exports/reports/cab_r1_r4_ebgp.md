# CAB Implementation Spec — Direct eBGP between R1 and R4

**Spec ID:** cab_r1_r4_ebgp_20260427
**Source:** ops-analyze Design Feasibility Check
**Status:** PASSED feasibility (`feasible: true`, `cab_ready: true`)

---

## Change Description

Add direct eBGP peering between R1 (AS 65000) and R4 (AS 65001) over
existing L2 link.

## Current State

| Device | Platform | Local AS | Loopback | Adjacent (R1↔R4 link) |
|---|---|---|---|---|
| R1 | juniper_junos | 65000 | 1.1.1.1/32 | ge-0/0/2 (no IP currently) |
| R4 | cisco_ios | 65001 | 4.4.4.4/32 | Ethernet0/0 (10.1.24.4 — OSPF active) |

Direct L2 link confirmed via LLDP (R1 ge-0/0/2 ↔ R4 Ethernet0/0).
No existing direct R1↔R4 eBGP session (current path is via R2).

## Feasibility Results

* `feasible: true`
* `required_as_r1`: 65000
* `required_as_r4`: 65001
* Lab subnet: 172.16.14.0/30
* `peer_addr_r1`: 172.16.14.1/30 (assign to R1 ge-0/0/2)
* `peer_addr_r4`: 172.16.14.2/30 (assign to R4 Ethernet0/0 secondary)
* Loopbacks unchanged.

## Risks

* Adding IP to currently-unnumbered R1 ge-0/0/2.
* Adding secondary IP to R4 Ethernet0/0 (different subnet from OSPF
  primary, OK).
* Best-path may shift to direct path; AS-prepend on R4 if migration
  needs to be gradual.
* Minor OSPF flap risk during IP add — maintenance window
  recommended.

---

## SRL Lab Substitution

Production interfaces map to SRL containers:

| Prod Device | Prod Interface | SRL Lab Node | SRL Interface |
|---|---|---|---|
| R1 | ge-0/0/2 | r1 | ethernet-1/1 |
| R4 | Ethernet0/0 secondary | r4 | ethernet-1/1 |

## Config Lines — node `r1` (SRL CLI)

```
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 address 172.16.14.1/30
set / interface system0 admin-state enable
set / interface system0 subinterface 0 admin-state enable
set / interface system0 subinterface 0 ipv4 admin-state enable
set / interface system0 subinterface 0 ipv4 address 1.1.1.1/32
set / network-instance default interface ethernet-1/1.0
set / network-instance default interface system0.0
set / routing-policy prefix-set loopbacks prefix 1.1.1.1/32 mask-length-range exact
set / routing-policy policy export-bgp statement 10 match prefix-set loopbacks
set / routing-policy policy export-bgp statement 10 action policy-result accept
set / routing-policy policy export-bgp default-action policy-result reject
set / network-instance default protocols bgp admin-state enable
set / network-instance default protocols bgp autonomous-system 65000
set / network-instance default protocols bgp router-id 1.1.1.1
set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable
set / network-instance default protocols bgp ebgp-default-policy import-reject-all false
set / network-instance default protocols bgp group ebgp-r4 peer-as 65001
set / network-instance default protocols bgp group ebgp-r4 export-policy [export-bgp]
set / network-instance default protocols bgp neighbor 172.16.14.2 peer-group ebgp-r4
```

## Config Lines — node `r4` (SRL CLI)

```
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 address 172.16.14.2/30
set / interface system0 admin-state enable
set / interface system0 subinterface 0 admin-state enable
set / interface system0 subinterface 0 ipv4 admin-state enable
set / interface system0 subinterface 0 ipv4 address 4.4.4.4/32
set / network-instance default interface ethernet-1/1.0
set / network-instance default interface system0.0
set / routing-policy prefix-set loopbacks prefix 4.4.4.4/32 mask-length-range exact
set / routing-policy policy export-bgp statement 10 match prefix-set loopbacks
set / routing-policy policy export-bgp statement 10 action policy-result accept
set / routing-policy policy export-bgp default-action policy-result reject
set / network-instance default protocols bgp admin-state enable
set / network-instance default protocols bgp autonomous-system 65001
set / network-instance default protocols bgp router-id 4.4.4.4
set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable
set / network-instance default protocols bgp ebgp-default-policy import-reject-all false
set / network-instance default protocols bgp group ebgp-r1 peer-as 65000
set / network-instance default protocols bgp group ebgp-r1 export-policy [export-bgp]
set / network-instance default protocols bgp neighbor 172.16.14.1 peer-group ebgp-r1
```

## Verification Commands

Run via `exec_on_node` on each lab container:

* `bash -c 'sr_cli show network-instance default protocols bgp neighbor 2>&1'`
  — confirm Established + AS numbers correct on both sides.
* `bash -c 'sr_cli show network-instance default protocols bgp routes ipv4-unicast summary 2>&1'`
  — confirm prefix exchange (each side learns the other's loopback /32).
* `bash -c 'sr_cli show interface ethernet-1/1 2>&1'`
  — confirm interface up, IP correctly assigned.

## CAB Pass Criteria

* `bgp neighbor` on r1 shows 172.16.14.2 in state Established with
  peer-as 65001.
* `bgp neighbor` on r4 shows 172.16.14.1 in state Established with
  peer-as 65000.
* Each side has at least 1 received route (peer's loopback prefix).
* No `dry_run_failures` on the SRL config push.

If any criterion fails: report **CAB FAIL** with the offending
output as evidence; destroy_lab; do NOT iterate-and-fix.
