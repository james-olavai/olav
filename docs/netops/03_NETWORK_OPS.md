# Network Ops Agent User Guide

**Ops Agent** is a **deep problem-solving tool** designed for network engineers. It's not just a simple data query tool—it's an assistant that can think, analyze, and plan. Use it when you face:
- **Production failures** - Need to find root causes
- **Complex changes** - Need to assess all impacts
- **Network planning** - Need to verify design feasibility

### 🚀 Ops Agent is a Multi-Dimensional Troubleshooting AI

Unlike Quick Agent's "shallow database queries," Ops Agent operates across **multiple dimensions**:

| Dimension | Capability | Example |
|-----------|-----------|---------|
| **Multi-vendor fusion** | Join queries across vendors (Juniper, Cisco, Arista, etc.) | "Where do R1 (Juniper) and R2 (Cisco) routing policies conflict?" |
| **Time-series analysis** | Time-travel through history, compare any two time points | "What's the trend of BGP neighbor changes over 3 days?" |
| **Active probing** | Probe actual network conditions (Ping, Traceroute, port scans) | "What's the actual latency from ops machine to DC?" |
| **CLI execution** | Parallel command execution to collect real-time data | "Query routing table from 5 core routers simultaneously" |
| **Log correlation** | Cross-device log analysis, find time-related events | "What device logs were anomalous when BGP went down?" |
| **Digital twin** | Simulate network behavior (failures, changes), predict impacts | "If I shut down R1-R2 link, which prefixes lose reachability?" |

These dimensions **work together** to enable **deep analysis** that Quick Agent cannot do alone.

---

## 🎯 Why Do You Need Ops Agent?

### When You Face These Problems...

| Problem | Quick Agent | Ops Agent |
|---------|-----------|-----------|
| "Why did BGP go down on R1 again?" | ❌ Only query facts | ✅ **Root cause analysis** |
| "I want to upgrade link R1-R2, what's the impact?" | ❌ Can't simulate | ✅ **Change impact analysis** |
| "Is there a loop in the network? Where? How risky?" | ❌ Only show topology | ✅ **Deep topology analysis** |
| "What happens to our network if a core link fails?" | ❌ Can't model failures | ✅ **Failure scenario simulation** |
| "How did config and routes change in the last 3 days?" | ❌ Query by query | ✅ **Time-series analysis** |

### Quick Agent vs Ops Agent

```
Quick Agent answers "WHAT" and "HOW MANY":
✅ "How many BGP neighbors does R1 have?"        → Returns number immediately
✅ "What's the interface status of S1 ports 1-5?" → Displays list
✅ "How many devices are in the data center?"     → Direct query

Ops Agent answers "WHY" and "WHAT IF":
✅ "Why did BGP go down and how do I fix it?"     → Multi-step reasoning + solution
✅ "How will the network behave if I change one link?" → Full simulation + risk
✅ "I'm redesigning the network, will it break?"  → Verification + benchmarking
```

---

## 🚀 Real Scenario 1: Production BGP Failure Diagnosis

### The Problem
Monday 2 PM, alert fires: **Data center is unreachable**.

Your first instinct: Check core router R1, find the BGP neighbor table all red. Running `olav "Show BGP status on R1"` just tells you the current state—you can't solve the root problem that way.

What you really need to know:
- **Why** did BGP go from stable to down?
- **Did something change yesterday** that caused this?
- **Is the physical link itself okay?**
- **How do I fix it fastest?**

### Using Ops Agent

```bash
$ olav --agent ops \
  "BGP session to data center keeps flapping for 3 hours. \
   Root cause analysis: config change? hardware issue? network problem? \
   How to fix?"
```

### Ops Agent's Analysis Process

1. **Routing check** - Query BGP routes, neighbor status, AS-PATH
2. **Historical comparison** - Compare config and routes from 3 hours ago
3. **Topology verification** - Confirm physical link path is actually reachable
4. **Link probing** - Active Ping and Traceroute to confirm connectivity
5. **Integrated diagnosis** - Correlate all data, find root cause

### Sample Output

```
═══════════════════════════════════════════════════════════════
Root Cause Diagnosis (BGP Flapping Analysis)
═══════════════════════════════════════════════════════════════

Problem first detected: 2026-03-06 14:32 UTC
Duration: 3 hours 15 minutes
Affected neighbor: R1→DC_GW (10.0.1.5)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evidence Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Physical link is healthy:
   - Interface Ge-0/0/1 UP, no errors
   - ICMP to 10.0.1.5 reachable, latency 5ms
   - Optical power normal, no attenuation

❌ BGP configuration changed:
   - 2026-03-06 11:15 UTC modified R1 BGP keepalive
   - Changed from 30s to 10s (too aggressive!)
   - DC_GW still using original 30s config
   → Timer mismatch causes one-directional KEEPALIVE loss

❌ Process logs show anomalies:
   - BGP process first restarted at 11:20
   - Then restarting every 2 minutes (self-healing failure)
   - Logs show "KEEPALIVE timeout" errors

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Root Cause
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ Root Cause: BGP KEEPALIVE timer configuration mismatch causing timeout

BGP RFC requires KEEPALIVE reception within HOLD-TIME.
R1 is waiting for DC_GW's KEEPALIVE but DC_GW sends every 30s while
R1 now expects it every 10s. This causes R1 to reset its timer every
10s while DC_GW only sends every 30s. Eventually R1's timer expires,
thinking the peer is down.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fix Recommendation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔧 Immediate fix (5 mins):
   1. SSH to R1
   2. set protocols bgp group dc-transit keepalive-interval 30
   3. commit
   → BGP should establish immediately

⚠️ Additional verification (after immediate fix):
   1. Verify DC_GW also has keepalive set to 30
   2. Check if other BGP neighbors have been modified too
   3. Find who made this 11:15 change (audit trail)

📋 Long-term improvements:
   1. Establish BGP timer standard (recommend keepalive 30, hold 90)
   2. Enforce consistency in Ansible playbooks
   3. Alert if BGP neighbor flaps 3+ times, notify immediately

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Recovery Verification (expect in ~10 mins)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Verification checklist after fix:
☐ BGP neighbor returns to Established state
☐ Data center routes reappear in routing table
☐ Data center Ping works, latency back to normal (< 10ms)
☐ Traffic resumes (check interface stats)

Next: Share this diagnosis with ops leadership to prevent recurrence
```

### Why Can't Quick Agent Do This?

```bash
$ olav "Show BGP status on R1"

# Returns:
BGP Status on R1:
  Neighbor: 10.0.1.5, State: Down, Last error: KEEPALIVE timeout
  
# That's it. Can't dig deeper. Need manual step-by-step investigation.
```

---

## 🔄 Real Scenario 2: Change Planning & Impact Assessment

### The Problem
You're a network planner. You need to do a **core network upgrade**:

Upgrade the R1-to-data-center link from 1G to 10G. Simple hardware change, right? But what about risks?
- Will the new 10G link change traffic routing?
- If the new link fails, what happens to backup routes?
- Will it create a new congestion point?
- Do I need a rollback plan?

### Using Ops Agent

```bash
$ olav --agent ops \
  "Plan: Upgrade R1-DC_GW link from 1G to 10G. \
   Simulate the change, show routing impact, identify risks, \
   provide rollback plan."
```

### Ops Agent's Simulation Process

1. **Snapshot current state** - Record pre-upgrade network (topology, routes, costs)
2. **Simulate the change** - Virtually modify link bandwidth, recalculate OSPF/BGP
3. **Impact analysis** - Which traffic reroutes? What are new costs/latencies?
4. **Failure scenario simulation** - What if the new link fails?
5. **Benchmark verification** - Does new config meet design standards?

### Sample Output

```
═══════════════════════════════════════════════════════════════
Change Impact Assessment Report
═══════════════════════════════════════════════════════════════

Change Summary: Upgrade R1-DC_GW link 1G → 10G
Planned Execution: 2026-03-15, Window 23:00-01:00 (2 hours)
Risk Level: 🟢 Low (hardware only, no config changes)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before vs After
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current topology (1G):
   R1 --[1G]-- DC_GW
   ↑
   DC traffic flows through this link

New topology (10G):
   R1 --[10G]-- DC_GW
   ↑
   Same logic, but 10x capacity

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Routing Change Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Prefix: 10.0.0.0/16 (data center)

❌ Before upgrade (1G link):
   Primary route: R1 → R2 → DC_GW (OSPF cost 200)
   Backup route: R1 → R3 → DC_GW (OSPF cost 250, longer AS-PATH)
   
   Current traffic split:
   - 70% via R2 route (preferred)
   - 30% via R3 route (backup)

✅ After upgrade (10G link):
   Primary route: R1 → DC_GW direct (OSPF cost 1, direct!)
   Backup route: R1 → R2 → DC_GW (now backup, cost 200)
   
   New traffic split:
   - 99% via direct link (optimal, latency < 1ms)
   - 1% via R2 backup (link failure only)

🎯 Benefits:
   ✅ DC traffic latency drops ~8ms → ~1ms (8x performance improvement)
   ✅ Reduces R2-DC_GW link pressure (70% → 1%)
   ✅ Overall network congestion relief

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Failure Scenario Simulation (if new link fails?)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Scenario: R1-DC_GW new link fails (< 3 mins to recover)

Degradation sequence:
  1️⃣ BGP neighbor goes down, R1 removes direct route
  2️⃣ Traffic auto-fails over to backup: R1 → R2 → DC_GW
  3️⃣ Forwarding latency increases: ~1ms → ~8ms (back to old level)
  4️⃣ R2-DC_GW link traffic spikes (1% → 100%)

⚠️ Risk assessment:
   - Is R2-DC_GW link 10G or 1G?
     → If 1G, can handle it, but becomes bottleneck (100% utilization)
   - Does R2 have other traffic?
     → Recommend checking R2's current utilization
   
🛡️ Mitigation options:
   If R2-DC_GW is 1G and already has 60%+ traffic, consider:
   ✅ Upgrade R2-DC_GW to 10G (or at least 5G)
   ✅ Or establish third backup route R1 → R4 → DC_GW
   ✅ Otherwise, new link failure reduces DC availability

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Execution Plan
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⏰ 2026-03-15 23:00 Maintenance window opens

📋 Execution steps:
  1. Notify DC team, enter maintenance mode
  2. Verify old 1G link is stable, backup route reachable
  3. Power down old module, install new 10G module
  4. Bring up new link, verify neighbor
  5. Monitor 5 mins, confirm traffic auto-shifts
  6. Test backup route (temporarily down new link)
  7. Restore new link, declare change complete

⏱️ Expected duration: 45-60 minutes

🔄 Rollback plan:
  If new link is unstable (neighbor keeps flapping):
  → Immediately power down new link, restore old 1G module
  → Network auto-reverts to old state, no manual intervention needed
  → Estimated recovery time < 3 minutes

✅ Completion criteria:
  □ BGP neighbor established, status Established
  □ Data center Ping works, latency < 5ms
  □ DC traffic confirmed on new link (check interface stats)
  □ Backup route works (traffic survives new link down)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Overall Assessment
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Advantages:
   - Major performance gain (8x latency improvement)
   - Better backup routing (reduces R2 load)
   - Low risk (hardware change, logic self-adapts)

⚠️ Recommendations:
   - Verify R2-DC_GW link capacity first
   - If insufficient, plan follow-up upgrade

✨ Recommended decision:
   🟢 GO AHEAD (contingent on R2 capacity being sufficient)
```

---

## 🛡️ Real Scenario 3: Network Resilience Assessment & Planning

### The Problem
You're the ops director. Your boss asks:

> "How stable is our network? What happens if a core link fails?"

This isn't a quick query. You need:
- **Comprehensive assessment** of single points of failure
- **Risk identification** - where are the vulnerabilities?
- **Improvement planning** - how to increase redundancy?

### Using Ops Agent

```bash
$ olav --agent ops \
  "Network resilience assessment: \
   1. Identify single points of failure \
   2. Simulate each critical link/device failure \
   3. Show impact on data center connectivity \
   4. Recommend improvements"
```

### Sample Output (Excerpt)

```
═══════════════════════════════════════════════════════════════
Network Resilience Report
═══════════════════════════════════════════════════════════════

Assessment Scope: Entire core network (8 routers, 15 links)
Assessment Method: Simulate each single-point failure, observe impact
Report Time: 2026-03-06

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Key Findings
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 High Risk (3 single points of failure):

1. R1-DC_GW direct link
   └─ Impact: DC latency increases 8x (~1ms → ~8ms)
   └─ Solution: Upgrade R2-DC_GW to 10G for shared load

2. R1 as local user gateway to core
   └─ Impact: Entire X building users lose core access
   └─ Solution: Deploy redundant R1 link or migrate to R2

3. ISP_GW as internet egress
   └─ Impact: All internet services go down
   └─ Solution: Deploy redundant ISP link

🟡 Medium Risk (5 points):
   [Detailed list...]

🟢 Low Risk (7 points):
   [Auto-reroute on failure, minimal impact]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Improvement Recommendations (Priority Order)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🥇 Priority 1 (Do immediately):
   ☐ Deploy second ISP link (backup internet egress)
     Estimated cost: $30K + 30 days
     Benefit: Internet stability 100% → 99.9%
   
   ☐ Redundancy for R1 local user link
     Estimated cost: $50K + 20 days
     Benefit: Prevent entire building outage

🥈 Priority 2 (Within 3 months):
   ☐ Optimize R1-DC_GW backup routing
   ☐ Multi-link DC access
   
🥉 Priority 3 (Annual plan):
   ☐ Core network redesign, achieve 2+ path redundancy

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROI Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If implementing only "Priority 1" improvements:
  ✅ Current failure rate: 10 incidents/year
  ✅ Post-improvement: 1 incident/year
  ✅ Annual downtime cost savings: $500K+
  ✅ Investment payback period: 2 months
  ✅ Recommendation: Worth immediate investment

[Full financial model...]
```

---

## ⚡ Quick Start

### Basic Usage

```bash
# Command line
cd /home/yhvh/Olav
olav --agent ops "Your question"

# Examples
olav --agent ops "Why did BGP go down on R1?"
olav --agent ops "Analyze network resilience, find all single points of failure"
olav --agent ops "Simulate upgrading R1-R2 link, predict impact"
```

### Python Code

```python
from olav.agents.ops import OpsAgent

agent = OpsAgent()

# Troubleshooting
result = agent.run("Why did BGP on R1 go down?")
print(result)

# Change planning
simulation = agent.run("Simulate R1-R2 link upgrade from 1G to 10G, predict impact")
print(simulation)
```

---

## 💡 Best Practices

### 1. Provide sufficient context
**Good:**
```
"BGP session to DC went down 3 hours ago and keeps flapping. 
 The link is 1G, connect to DC_GW. We depend on this for DC traffic.
 Root cause + fix recommendation?"
```

**Poor:**
```
"Why is BGP down?"
# System doesn't know which BGP session you mean
```

### 2. Specify time range clearly
**Good:**
```
"R1-R2 link was stable yesterday but started having issues 
 since this morning. What changed?"
```

**Poor:**
```
"What changed on R1?"
# Too broad, can't scope analysis properly
```

### 3. State your objective
**Good:**
```
"I want to upgrade our DC link from 1G to 10G. 
 Show me the routing impact, failure scenarios, and migration plan."
```

**Poor:**
```
"Upgrade DC link"
# System doesn't know what to analyze
```

### 4. For change planning, specify affected services
**Good:**
```
"Plan: enable OSPF graceful restart on all core routers. 
 Impact on: DC connectivity, internet egress, local site traffic?"
```

**Poor:**
```
"Change OSPF settings"
# System might miss critical services
```

---

## 🎬 When to Use Ops Agent?

| Scenario | Assessment | Action |
|----------|-----------|--------|
| "What's the BGP status on R1 right now?" | Quick query | → Quick Agent |
| "Why did BGP on R1 go down?" | Needs analysis | → **Ops Agent** |
| "How many routes are there?" | Statistics query | → Quick Agent |
| "If I remove link R1-R2, how does traffic reroute?" | Needs simulation | → **Ops Agent** |
| "Are there interface errors?" | Fact check | → Quick Agent |
| "Why do interfaces keep flapping?"  | Root cause needed | → **Ops Agent** |

---

## 🔧 Configuration & Optimization

### Adjust simulation depth (api.json)

```json
{
  "agents": {
    "ops": {
      "max_reasoning_steps": 5,          // Max 5 reasoning steps
      "simulation_iterations": 1000,     // Simulation iterations
      "include_failure_scenarios": true  // Simulate failures?
    }
  }
}
```

### View analysis process

```bash
# Enable detailed logging
export OLAV_DEBUG=1
olav --agent ops "Your question"

# View logs
tail -f .olav/logs/users/$(whoami).log | grep ops
```

---

## 🚫 Capability Boundaries

### ✅ What Ops Agent Can Do

- ✅ **Root cause analysis** - Config, topology, state changes
- ✅ **Change impact assessment** - Simulate routing, traffic, failover
- ✅ **Network resilience assessment** - Single-point failure analysis
- ✅ **Design recommendations** - Simulation-based optimization
- ✅ **Performance prediction** - Latency, throughput, convergence time

### ❌ What Ops Agent Cannot Do

- ❌ **Push configuration** - Only plans and analyzes, doesn't execute
- ❌ **Packet capture analysis** - No pcap data collection
- ❌ **Security auditing** - Not security-focused (use Quick Agent for config)
- ❌ **Real-time monitoring** - Snapshot-based analysis, not real-time

---

## 🆘 FAQ

### Q: Ops Agent results don't match reality?

**A:**
1. Check data freshness: `olav "When was the last snapshot?"`
2. Data collection might be incomplete (e.g., missing BGP neighbors)
3. Trigger fresh snapshot: `olav snapshot now`
4. Re-run Ops Agent

### Q: How to use with large networks (> 500 devices)?

**A:**
- Segment simulations: `"Simulate failures in northeast region only"`
- Lower complexity: Adjust `api.json` `simulation_iterations`
- Cache topology offline

### Q: Simulation takes 30 seconds with no result?

**A:**
Normal. Ops Agent is doing deep analysis:
- Multi-path calculations
- Multiple failure scenarios
- Historical data correlation

If it takes > 2 mins, `Ctrl-C` and retry with lower complexity.

---

## 📞 Feedback & Help

```bash
# View complete logs
cat .olav/logs/users/$(whoami).log

# Submit diagnostics to ops team
olav --agent ops "..." --export-debug diagnostic.zip
```

---

**Last Updated: March 6, 2026**
```
- "What is the best BGP path from R1 to the core?"
- "If link R2-R4 fails, which routes will be affected?"
- "Find all blackholed routes in the network"
- "Calculate OSPF cost for each link to R1"
- "Show ECMP multi-path choices for prefix 10.0.0.0/8"
```

**Capabilities:**
- ✅ BGP AS-PATH analysis (best-path selection)
- ✅ OSPF cost calculation and path analysis
- ✅ Routing table queries and blackhole detection
- ✅ Link/device failure simulation (What-If)
- ✅ ECMP multi-path selection (partial support)
- ✅ Generate structured change planning reports

**Limitations:**
- ❌ STP topology change simulation (no spanning_tree data collection)
- ❌ VLAN isolation simulation (no vlan/mac_table collection)
- ❌ ACL packet filtering simulation (no acl collection)

**Performance:** 🚀 Simulation < 5 seconds (depends on network size)

---

### 2️⃣ **Topology Analysis (Topology Expert)**
L2/L3 topology analysis, pathfinding, loop detection, topology export.

**Examples:**
```
- "Show me the physical topology from R1 to the core"
- "Is there a loop in the L2 topology?"
- "Find the shortest path between R1 and R4"
- "Which devices are connected to SW1?"
- "Generate a network diagram"
```

**Capabilities:**
- ✅ L2 analysis (physical links, CDP/LLDP)
- ✅ L3 logical topology (BGP/OSPF adjacencies)
- ✅ Path calculation (with cost weights)
- ✅ Loop detection (STP blocked port identification)
- ✅ Export topology diagrams (Mermaid .mmd format)
- ✅ Multi-layer topology analysis (L2 + L3 fusion)

**Performance:** 🕐 Topology analysis < 3 seconds | Path calculation < 5 seconds | Export < 2 seconds

---

### 3️⃣ **Active Probing (Probe Expert)**
Liveness detection, latency measurement, path tracing, port scanning, network segment discovery.

**Examples:**
```
- "Ping R1 management IP and show latency"
- "Trace the path from my PC to the DNS server"
- "Scan for open ports on R1 Telnet service"
- "Test connectivity to 10.0.0.0/8 subnet"
- "Discover devices in the 172.16.0.0/16 segment"
```

**Capabilities:**
- ✅ Ping (ICMP reachability, latency)
- ✅ Traceroute (path tracing)
- ✅ Port scanning (open service discovery)
- ✅ Parallel CLI execution (simultaneous multi-device testing)
- ✅ Network segment discovery (CIDR subnet probing)

**Performance:** 🌐 Ping < 2 seconds | Traceroute < 10 seconds | Port scan < 15 seconds

---

### 4️⃣ **Time-Series Drift Detection (Diff Agent)**
Configuration and state comparison between snapshots, change detection, drift analysis.

**Examples:**
```
- "What changed on R1 between 2026-03-01 and 2026-03-05?"
- "Show me the interface status changes in the last 3 days"
- "Which routes were added/removed since yesterday?"
- "Has the BGP configuration drifted from baseline?"
```

**Capabilities:**
- ✅ Configuration comparison (running vs saved state)
- ✅ State drift detection (interfaces, adjacencies, routes)
- ✅ Time-series analysis (multi-snapshot comparison)
- ✅ Change audit (who changed what, when)

**Performance:** ⏱️ Comparison < 5 seconds | Time-series analysis < 10 seconds

---

## 🚀 Use Cases and Examples

### Case 1: BGP Fault Deep Dive Analysis
```bash
$ olav --agent ops "BGP routes on R1 keep flapping. Root cause analysis"

# Ops Agent's analysis workflow:
1. [Routing Simulator] Query BGP adjacencies and routing table
2. [Topology Expert] Analyze connectivity issues in topology
3. [Probe Expert] Ping R1's BGP peer IPs to confirm connectivity
4. [Diff Agent] Compare configuration changes in last 24 hours
5. Synthesize analysis → Generate root cause report
```

**Example Output:**
```
Root Cause: BGP process crash due to memory leak on R1
Evidence:
- BGP session to R2 flapped 47 times in 24 hours
- Configuration unchanged (no manual changes detected)
- Physical link stable (no packet loss detected via probe)
- Process restart happened at 2026-03-05 14:32 UTC

Recommendation:
1. Upgrade BGP process to latest patch
2. Enable BGP graceful restart for stability
3. Increase memory limit to prevent OOM
```

---

### Case 2: Change Planning & Impact Analysis
```bash
$ olav --agent ops "Plan: Upgrade link R1-R2 from 1G to 10G. Show network impact"

# Ops Agent's simulation workflow:
1. [Routing Simulator] Simulate new link bandwidth changes
2. Recalculate OSPF costs (based on new BW)
3. Predict ECMP load balancing shifts
4. Simulate failure scenarios (new link down)
5. Generate detailed change planning report

# Output:
- Before: R1→R4 via R2 (1G link, OSPF cost 100)
- After: R1→R4 via R2 (10G link, OSPF cost 10)
- Impact: Traffic will shift to R2 path, 90% less latency
- Risk: If R2 link fails, R1→R4 will reroute via R3 (higher latency)
- Mitigation: Enable OSPF graceful restart
```

---

### Case 3: Topology Loop Detection
```bash
$ olav --agent ops "Is there a layer 2 loop in the network? Show loop path"

# Output:
Found L2 Loop:
SW1 (Port 1) ←→ SW2 (Port 2) ←→ SW3 (Port 3) ←→ SW1 (Port 4)

Current Status:
- STP has blocked SW3 Port 3 to prevent loop
- All other ports forwarding normally
- Network is stable, no storm detected

Recommendation:
1. Verify STP is running on all switches
2. Consider using RSTP for faster convergence
3. Implement BPDU guard on access ports
```

---

### Case 4: Path Discovery & Latency Measurement
```bash
$ olav --agent ops "Measure end-to-end latency from R1 to 8.8.8.8 and show path"

# Output includes:
Traceroute path: R1 → ISP_GW → ISP_CORE → Google_GW → 8.8.8.8

Hop-by-hop latency:
1. R1 → ISP_GW: 5ms (local)
2. ISP_GW → ISP_CORE: 12ms (backbone)
3. ISP_CORE → Google_GW: 35ms (internet)
4. Google_GW → 8.8.8.8: 1ms (destination)

Total: 53ms (good for internet traffic)

Recommendation:
- Latency is acceptable for most applications
- Consider BGP prepending if you want failover to another ISP
```

---

## ⚙️ Configuration and Customization

### Modify Simulation Parameters
Edit `api.json`:

```json
{
  "agents": {
    "ops": {
      "simulator": {
        "max_simulation_iterations": 1000,
        "topology_edge_limit": 10000
      },
      "probe": {
        "ping_timeout": 5,
        "traceroute_max_hops": 30,
        "port_scan_timeout": 10
      }
    }
  }
}
```

### Enable Detailed Logging
```bash
# View Ops Agent execution logs and simulation process
tail -f .olav/logs/users/$(whoami).log | grep ops

# Expert debugging: view simulation code
.olav/logs/experiment_sandbox_*.log
```

### Export Simulation Reports
```bash
# Auto-export as Markdown report
olav --agent ops \
  "Simulate link failure on R1-R2, export detailed report" \
  --output-format markdown \
  --output-path ./change_plan.md
```

---

## 🛑 Capabilities and Limitations

### ✅ What Ops Agent Can Do

| Capability | Description |
|------------|-------------|
| **Routing Analysis** | ✅ BGP/OSPF paths, costs, best-path |
| **What-If Simulation** | ✅ Link/device failure scenarios |
| **Topology Analysis** | ✅ Loop detection, path calculation |
| **Active Probing** | ✅ Ping, Traceroute, port scanning |
| **Change Planning** | ✅ Generate detailed planning reports |
| **Time-Series Analysis** | ✅ Configuration and state comparison |
| **Root Cause Analysis** | ✅ Multi-layer fault diagnosis |
| **Report Export** | ✅ Markdown/CSV/JSON |

### ❌ What Ops Agent Cannot Do

| Capability | Limitation |
|------------|-----------|
| **Configuration Push** | Does not execute; only plans and analyzes |
| **STP Simulation** | No spanning_tree data collection |
| **VLAN Simulation** | No vlan and mac_table collection |
| **ACL Filtering Simulation** | No acl and rule collection |
| **Performance Prediction** | No precise QoS models |
| **Actual Execution** | Simulates but doesn't execute changes |

### ⏱️ Performance Metrics

| Operation Type | Typical Time | Max Recommended Scale |
|------------|------------|---------------------|
| Routing analysis | < 3 seconds | 100K+ route entries |
| Small simulation (< 50 devices) | < 5 seconds | 50 devices |
| Large simulation (> 50 devices) | 10-30 seconds | 500 devices |
| Topology analysis | < 3 seconds | 1000+ links |
| Ping probe | < 2 seconds | 10 parallel targets |
| Traceroute | < 10 seconds | 1 target |
| Time-series comparison | < 5 seconds | 100+ snapshots |

---

## 🔄 Difference from Quick Agent

| Metric | Quick Agent | Ops Agent |
|--------|-----------|-----------|
| **Query Method** | Direct query | Multi-step hypothesis testing |
| **Iterations** | Max 1 | Max 10 |
| **Response Time** | < 5 seconds | 10-30 seconds |
| **Capabilities** | Fast query/simple diagnosis | Deep analysis/simulation/planning |
| **Complexity** | Low (single or dual table JOIN) | High (multi-table, sub-query, simulation) |
| **Recommended For** | Daily ops, quick queries | Fault diagnosis, change planning |

---

## 💡 Usage Tips

### 1. Ask "Why" Not "What"
**Good:**
```
"Why is BGP not converging after config change?"
"What caused the routing loop?"
```

**Poor:**
```
"Show BGP status"  # Quick Agent is better for this
"List all routes"  # This is a query, not analysis
```

### 2. Provide Time Context
```
"R1 interface went down 2 hours ago. What happened since then?"
# System will auto-query that time window for all changes
```

### 3. Specify Simulation Scope
```
"Simulate: R2 down. Impact on traffic from R1 to data center?"
# More specific than "R2 down"
```

### 4. Combine Multiple Questions
```bash
# Ops Agent supports complex multi-step analysis
olav --agent ops \
  "BGP flapping on R1. Root cause + impact analysis + fix recommendation"
```

### 5. Export Planning Reports
```bash
$ olav --agent ops \
  "Plan core network redesign: migrate from R1 to R2 as route reflector" \
  --output-format markdown > redesign_plan.md

# Report includes:
# - Topology changes
# - Risk assessment
# - Rollback plan
# - Validation steps
```

---

## 🆘 Frequently Asked Questions (FAQ)

### Q: When to use Ops Agent vs Quick Agent?

**A:**
- **Quick Agent**: "What is?" or "Show me ..."（query）
- **Ops Agent**: "Why?" or "What if?" （analysis）

```bash
# Quick Agent
olav "Show BGP status on R1"
olav "List all routes"

# Ops Agent
olav --agent ops "Why is BGP down and how to fix it?"
olav --agent ops "If link R1-R2 fails, what happens?"
```

### Q: Simulation results not accurate?

**A:**
1. Ensure data is fresh: `olav "When was the last snapshot?"`
2. Check topology completeness: `olav --agent ops "Show network topology"`
3. Verify configuration: `olav "Show device R1 config"`

If issues persist, data collection may be incomplete. Contact your network administrator.

### Q: How to run simulation on large networks (> 1000 devices)?

**A:**
1. Segment simulation: `"Simulate failure on region 'east' routers only"`
2. Adjust parameters: Edit `api.json` to increase `max_simulation_iterations`
3. Pre-compute topology: `olav --agent ops "Cache network topology for offline simulation"`

### Q: Can Ops Agent auto-execute the configuration push from change planning?

**A:**
No. Ops Agent only plans and analyzes, does not execute changes. Reasons:
- Changes require manual approval and risk confirmation
- Configuration varies greatly across environments

Recommended workflow:
1. Use Ops Agent to generate planning report
2. Manual review and approval
3. Use Nornir or Ansible to execute changes
4. Verify changes (use Ops Agent again)

### Q: Can sub-agents be used independently?

**A:**
Yes. If you only need one sub-agent's functionality:

```bash
# Topology analysis only
olav --agent ops --subagent topology "Show network topology"

# Probing only
olav --agent ops --subagent probe "Ping 10.0.0.1 and measure latency"

# Time-series comparison only
olav --agent ops --subagent diff "Compare config between 2026-03-01 and 2026-03-05"
```

### Q: How to debug simulation code?

**A:**
Ops Agent uses LLMExperimentSandbox to run Python simulation code. Debugging steps:

```bash
# 1. Enable detailed logging
export OLAV_DEBUG=1

# 2. Run simulation
olav --agent ops "Simulate ..."

# 3. View generated Python code and output
cat .olav/logs/experiment_sandbox_latest.log

# 4. Copy code to local test
python3 -c "$(cat .olav/logs/experiment_sandbox_latest.py)"
```

---

## 📞 Getting Help

### Online Resources
- 📖 Quick Agent Comparison: `docs/02_QUICK_QUERY.md`
- 🔧 Configuration Reference: `docs/05_SYSTEM_CONFIG.md`
- 📊 Database Schema: `.olav/workspace/ops/[simulator|topology|probe|diff]/SKILL.md`

### Troubleshooting
1. View full logs: `.olav/logs/users/<username>.log`
2. Check data freshness: `olav "Snapshot status"`
3. Test individual sub-agent: `olav --agent ops --subagent <name>`

### Feedback and Suggestions
```bash
# Report an issue
echo "Problem: Ops Agent not simulating correctly" > .olav/feedback.txt

# List all available sub-agents
olav --agent ops --list-subagents
```

---

## 📝 Changelog

**v2.0.0** (Current)
- ✅ 4 major sub-agents (Simulator/Topology/Probe/Diff)
- ✅ Network simulation (networkx + netutils)
- ✅ What-If scenario analysis
- ✅ Structured planning reports

**v1.0.0**
- ✅ Routing analysis
- ✅ Topology discovery
- ✅ Basic probing

---

**Last Updated: March 6, 2026**
