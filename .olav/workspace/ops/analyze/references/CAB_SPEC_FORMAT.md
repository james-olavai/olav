# CAB Implementation Spec — output format

Load when shaping the final report from a routing-change analysis.
ops-lab implements this section literally, so format must be exact.

## Required report sections

A complete simulation report exports via `format_and_export` with:

1. **Current State** — relevant routing / topology data
2. **Simulation Scope** — tables cloned, mutations applied
3. **Feasibility Check Results** — output of
   `DESIGN_FEASIBILITY_CHECK.md` (blockers, warnings, recommendations)
4. **Impact Analysis** — blast radius, affected protocols
5. **Change Plan** — phased actions (Phase 0 prerequisites → Phase 1+)
   with rollback steps
6. **CAB Implementation Spec** — machine-readable, format below
7. **Verification Commands** — CLI commands to verify each phase
8. **Risk Classification** — LOW / MEDIUM / HIGH with justification

## CAB Implementation Spec format (exact)

The spec has TWO mandatory sub-sections:

1. **Prod implementation** — platform-specific CLI for each prod
   device (Junos / IOS / IOS-XR), what production engineers apply.
2. **SRL Lab Substitution** — a self-contained mapping plus SRL CLI
   commands so ops-lab can deploy and validate verbatim. **Always
   include this section, even if the user prompt didn't mention
   SRL or lab — ops-lab is the validation gate by convention.**

### Section 1 — Prod implementation

```markdown
## CAB Implementation Spec

### Prerequisites (Phase 0)
- [ ] Route to 4.4.4.4/32 exists on R1 via 10.0.0.2 (static or IGP)
- [ ] Route to 1.1.1.1/32 exists on R4 via 10.0.0.1

### Device: R1 (platform: junos)
**Phase:** 1
**Action:** add
**Protocol:** bgp
**Config:**
- set protocols bgp group ebgp-r4 type external
- set protocols bgp group ebgp-r4 neighbor 172.16.99.2 peer-as 65001
- ...
**Expected outcome:** BGP session ESTABLISHED with peer 172.16.99.2 AS65001
**Rollback:** delete protocols bgp group ebgp-r4

### Device: R4 (platform: ios)
**Phase:** 1
**Action:** add
**Protocol:** bgp
**Config:**
- router bgp 65001
- neighbor 172.16.99.1 remote-as 65000
- ...
**Expected outcome:** ...
**Rollback:** ...
```

### Section 2 — SRL Lab Substitution (always include)

```markdown
## SRL Lab Substitution Table

| Prod Device | Prod Intf      | Prod Lo0   | Lab Node | Lab Link Intf  | Lab Lo0  | Lab Link IPs   |
|-------------|----------------|------------|----------|----------------|----------|----------------|
| R1          | ge-0/0/2       | 1.1.1.1/32 | r1       | ethernet-1/1   | system0  | 172.16.99.1/30 |
| R4          | Ethernet0/0    | 4.4.4.4/32 | r4       | ethernet-1/1   | system0  | 172.16.99.2/30 |

## Config Lines — node r1 (SRL CLI)

set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 address 172.16.99.1/30
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
set / network-instance default protocols bgp group ebgp-r4 export-policy [ export-bgp ]
set / network-instance default protocols bgp neighbor 172.16.99.2 peer-group ebgp-r4

## Config Lines — node r4 (SRL CLI)

set / interface ethernet-1/1 admin-state enable
... (same shape, swap IPs / AS / loopback / group name)
```

### Lab node naming + interface conventions

* Lab node names ALWAYS lowercase (CLAB convention; matches
  `generate_clab_topology` output)
* Lab interfaces ALWAYS sequential `ethernet-1/1`, `ethernet-1/2`
  starting at 1 (NOT preserving prod port numbers)
* Lab loopback ALWAYS `system0` (SRL convention)
* Lab link IPs from a NEW /30 reserved for the lab (not prod IPs)

### Required content overall

The spec must include:

* **Exact** IP addresses and AS numbers (from DB, never generic
  placeholders like `<X>`)
* **Platform-specific** prod CLI syntax (Junos `set protocols bgp ...`
  vs. IOS `router bgp <AS>; neighbor ...`)
* **SRL Lab Substitution Table + SRL CLI for r1/r4** — required even
  when prompt doesn't mention lab. ops-lab validates this section
  verbatim. SRL syntax reference: the shared:ops expert
  `srl_spec_generation_rules` (will surface in your recall block).
* **Expected convergence outcome** (what "PASS" looks like —
  ESTABLISHED state, FULL adjacency, etc.)
* **Rollback steps** (what to revert on FAIL)

Anything ambiguous here — and especially a missing SRL section —
will cause ops-lab to FAIL the validation with an
"underspecified plan" error or worse, trip on YANG-rejection
during translation.
