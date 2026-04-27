# CAB Implementation Spec — output format

Load when shaping the final report from a routing-change analysis.
The spec describes the change in **production** terms — platform-
specific CLI for each prod device. ops-lab takes this prod spec
and adapts it to the SRL digital twin internally; ops-analyze does
NOT need to write SRL CLI.

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

The spec is **prod-aligned** — exactly the CLI a production
engineer applies to the real R1 (Junos) / R4 (IOS) / etc. ops-lab
reads this spec, queries the prod DB for platform info, and
generates the SRL equivalent on its own (R88-A `generate_clab_topology`
+ R89 `generate_srl_lab_config`). Don't write SRL here.

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
- set protocols bgp group ebgp-r4 family inet unicast
- set interfaces ge-0/0/2 unit 0 family inet address 172.16.99.1/30
**Expected outcome:** BGP session ESTABLISHED with peer 172.16.99.2 AS65001
**Rollback:** delete protocols bgp group ebgp-r4 ; delete interfaces ge-0/0/2 unit 0

### Device: R4 (platform: ios)
**Phase:** 1
**Action:** add
**Protocol:** bgp
**Config:**
- interface Ethernet0/0
-  ip address 172.16.99.2 255.255.255.252
- router bgp 65001
-  address-family ipv4
-   neighbor 172.16.99.1 remote-as 65000
-   neighbor 172.16.99.1 activate
**Expected outcome:** BGP session Established with peer 172.16.99.1 AS65000
**Rollback:** no router bgp 65001 ; no interface Ethernet0/0 (or revert to prior IP)
```

### Required content

The spec must include:

* **Exact** IP addresses and AS numbers (from DB, never generic
  placeholders like `<X>`)
* **Platform-specific** prod CLI for each device, in the device's
  native syntax (Junos `set protocols bgp ...`, IOS
  `router bgp <AS>; neighbor ...`, IOS-XR `router bgp; address-family
  ipv4 unicast; neighbor ...`)
* **Expected convergence outcome** (what "PASS" looks like —
  ESTABLISHED state, FULL adjacency, etc.)
* **Rollback steps** (what to revert on FAIL)

Anything ambiguous here — wrong CLI for the platform, missing IPs,
no rollback — causes ops-lab to FAIL the validation with an
"underspecified plan" error.

### What ops-lab does with this spec

ops-lab takes the prod spec, queries the netops DB for each
device's platform / interfaces / loopback / ASN, and generates
SRL-equivalent CLI for the digital twin internally (R89
`generate_srl_lab_config`, planned). The agent doesn't have to
guess SRL syntax; the generator tool produces it deterministically
from a 23-line per-node template. ops-analyze writes prod CLI
only; lab translates.
