# CAB Report Format

Load when writing the CAB Decision report after `exec_on_node`
verification.  Exact format — ops-lab consumers parse it literally.

## Report template

```markdown
## CAB Report

### Decision: ✅ PASS | ❌ FAIL

### Evidence
| Check | Result | Detail |
|-------|--------|--------|
| Interface UP | ✅/❌ | e.g. "ethernet-1/1: up, 10.0.0.1/30" |
| L3 reachability | ✅/❌ | e.g. "ping 4.4.4.4: 3ms RTT" |
| Protocol convergence | ✅/❌ | e.g. "BGP 10.0.0.2: established, AS65001" |
| Route table | ✅/❌ | e.g. "4.4.4.4/32 via 10.0.0.2 present" |

### Design Commentary
(Always include this section, even on PASS — it helps Sim improve
future plans)

**What the plan got right:**
- ...

**Issues found (classify each):**
- 🔴 BLOCKER — [design error that caused failure, e.g. "Plan uses iBGP
  but no IGP exists between peers"]
- 🟡 PREREQ — [missing prerequisite that plan didn't include, e.g.
  "No route to loopback before BGP session"]
- 🟠 SYNTAX — [platform version constraint, e.g. "SRL v26.3.1:
  ebgp-multihop not valid under peer-group"]
- 🔵 SUGGEST — [improvement even if passing, e.g. "Direct-link eBGP
  simpler than multihop for this topology"]

**Feedback for Sim (concrete revision instructions):**
1. ...
2. ...
```

## Classification rules

- **PASS report**: still include Design Commentary with any 🟠 SYNTAX
  or 🔵 SUGGEST items found.
- **FAIL report**: must include at least one 🔴 BLOCKER or 🟡 PREREQ
  with specific fix instructions.

## Rules on FAIL

- Do NOT modify the plan to make it work — report the exact failure.
- Do NOT hide partial failures ("it mostly works").
- Classify the failure type so Sim knows which layer to fix.
- Destroy lab → output report.

## Why classify?

The classification tells Sim exactly which layer needs revision:

| Class | Meaning | Who fixes |
|---|---|---|
| 🔴 BLOCKER | Design is fundamentally wrong | Sim re-designs |
| 🟡 PREREQ | Missing Phase 0 prerequisite | Sim adds Phase 0 |
| 🟠 SYNTAX | Platform-version mismatch | Sim updates CLI syntax |
| 🔵 SUGGEST | Optional improvement | Sim decides if in scope |
