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

```markdown
## CAB Implementation Spec

### Prerequisites (Phase 0)
- [ ] Route to 4.4.4.4/32 exists on R1 via 10.0.0.2 (static or IGP)
- [ ] Route to 1.1.1.1/32 exists on R4 via 10.0.0.1

### Device: R1 (platform: junos | srl | ios)
**Phase:** 1
**Action:** add
**Protocol:** bgp
**Config:**
- neighbor <IP> peer-as <AS>     # exact CLI, platform-specific
- ...
**Expected outcome:** BGP session ESTABLISHED with peer <IP> AS<AS>
**Rollback:** delete neighbor <IP>

### Device: R4 (platform: ios | srl)
**Phase:** 1
**Action:** add
**Protocol:** bgp
**Config:**
- ...
**Expected outcome:** ...
**Rollback:** ...
```

The spec must include:

* **Exact** IP addresses and AS numbers (from DB, never generic
  placeholders like `<X>`)
* **Platform-specific** CLI syntax (Junos `set protocols bgp ...`
  vs. IOS `router bgp <AS>; neighbor ...`)
* **Expected convergence outcome** (what "PASS" looks like —
  ESTABLISHED state, FULL adjacency, etc.)
* **Rollback steps** (what to revert on FAIL)

Anything ambiguous here will cause ops-lab to FAIL the validation
with an "underspecified plan" error.
