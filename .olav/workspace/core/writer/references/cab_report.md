# Report Type: cab_report

## When to use
Tag: `report_type: cab_report`
Input: CAB validation evidence from ops-lab (show command outputs, BGP state, interface status)

## Format Rules

### Evidence Table (mandatory, exactly 4 columns)

| Check | Result | Detail | Evidence |
|---|---|---|---|
| Interface UP | PASS/FAIL | e1-1 admin/oper up | `show interface brief` output |
| L3 Reachability | PASS/FAIL | ping X.X.X.X success | `ping` output |
| BGP Convergence | PASS/FAIL | Established, N prefixes | `show bgp summary` output |
| Route Installed | PASS/FAIL | X.X.X.X/Y via Z.Z.Z.Z | `show route` output |

### Design Commentary (mandatory, even for PASS)

Classify each finding with emoji:
- 🔴 **BLOCKER** — must fix before approval
- 🟡 **PREREQ** — prerequisite not met
- 🟠 **SYNTAX** — config syntax issue
- 🔵 **SUGGEST** — optional improvement

### CAB Decision

```
CAB Decision: ✅ PASS / ❌ FAIL
Evidence: N/N checks passed
Recommendation: [Approve / Block with findings]
```

## Example Output

```markdown
## CAB Validation Report: r1-r4-ebgp-direct

### Evidence Table

| Check | Result | Detail | Evidence |
|---|---|---|---|
| R1 e1-1 UP | ✅ PASS | admin up, oper up | `A:R1# show interface brief` |
| R4 e1-1 UP | ✅ PASS | admin up, oper up | `A:R4# show interface brief` |
| BGP R1→R4 | ✅ PASS | Established, 2 prefixes | `A:R1# show bgp summary` |
| Route 4.4.4.4/32 | ✅ PASS | via 10.0.14.4 | `A:R1# show route` |

### Design Commentary

🔵 **SUGGEST:** Consider adding BFD for faster failover detection on the eBGP session.

### CAB Decision

CAB Decision: ✅ PASS
Evidence: 4/4 checks passed
Recommendation: Approve for production deployment
```

## Export
Call `format_and_export(data=<report_md>, format="md", subdir="reports", filename="cab_report_<scenario>")`.
