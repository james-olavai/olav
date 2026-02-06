# Network Expert - Diagnostic Reference Guide

## Complete Diagnostic Workflow

### Phase 1: Problem Assessment (5-10 minutes)

**Goal**: Understand scope, severity, and affected components

**Tasks**:
1. **Parse the Problem**
   - Symptom description (what's broken?)
   - Duration (when did it start?)
   - Scope (one device, one site, entire network?)
   - Business impact (critical, major, minor?)

2. **Classify the Issue Type**
   - Connectivity (L1-L3)
   - Protocol state (BGP, OSPF, VPC, STP)
   - Performance degradation (throughput, latency, jitter)
   - Configuration drift
   - Design issue vs operational issue

3. **Identify Affected Components**
   - Devices (query: `SELECT * FROM devices WHERE role IN (...)`)
   - Protocols (BGP, OSPF, VXLAN, etc.)
   - Layers (L1 optics, L2 switching, L3 routing, L4+ application)
   - Services/VRFs affected

4. **Set Investigation Scope**
   - Primary domain (campus, DC, SP core, branch)
   - Failure domain boundary
   - Time window (last 24h? last week?)

**Example Assessment Query**:
```sql
-- BGP flapping report
SELECT d.hostname, d.vendor, d.device_role, d.site,
       COUNT(DISTINCT r.command) as commands_seen,
       MAX(r.created_at) as last_update
FROM devices d
LEFT JOIN raw_outputs r ON d.hostname = r.device
WHERE d.device_role IN ('BGP-Route-Reflector', 'BGP-Border-Router')
  AND r.command LIKE '%show ip bgp%'
GROUP BY d.hostname
ORDER BY d.site, d.device_role;
```

---

### Phase 2: Evidence Collection (10-20 minutes)

**Goal**: Gather facts to validate hypotheses

**Data Sources** (in priority order):

1. **Database First** (always)
   - Device inventory and metadata
   - Interface states and statistics
   - Protocol neighbor relationships
   - Historical state changes
   - Configuration comparisons

2. **Topology Analysis** (scope expansion)
   - `analyze_topology()` → Understand device relationships
   - Build failure domain graph
   - Identify critical paths

3. **Knowledge Base** (pattern matching)
   - `search_similar_cases()` → Find historical matches
   - Identify known issues and workarounds
   - Review previous solutions

4. **Real-Time Data** (if needed)
   - `nornir_execute()` → Get current protocol state
   - Verify database accuracy (data sync issues?)
   - Check transient errors

**Multi-Layer Evidence Collection**:

```
L1 (Physical)
├─ Interface errors (CRC, alignment, collisions)
├─ Signal quality (optics, voltages)
└─ Power/thermal

L2 (Data Link)
├─ MAC table consistency
├─ STP blocking/forwarding state
├─ VLAN membership
└─ LACP/Etherchannel status

L3 (Network)
├─ Routing table correctness
├─ BGP/OSPF neighbor state
├─ ICMP reachability
└─ MTU path issues

L4-L7 (Application)
├─ TCP/UDP connectivity
├─ DNS resolution
├─ QoS marking and queuing
└─ Application-specific logs
```

**Example Evidence Queries**:

**BGP Flapping - Neighbor Instability**:
```sql
-- Find BGP neighbors with frequent state changes
SELECT d.hostname, r.command, COUNT(*) as update_count,
       FIRST(r.created_at) as first_seen,
       LAST(r.created_at) as last_seen,
       DATEDIFF(SECOND, FIRST(r.created_at), LAST(r.created_at)) as duration_seconds
FROM devices d
JOIN raw_outputs r ON d.hostname = r.device
WHERE r.command = 'show ip bgp summary'
  AND DATE_DIFF('day', r.created_at, NOW()) <= 1
GROUP BY d.hostname, r.command
HAVING COUNT(*) > 10  -- Multiple updates in 24h
ORDER BY update_count DESC;
```

**VXLAN MAC Mobility - Rapid Moves**:
```sql
-- Query VXLAN MAC table changes
SELECT r.device, COUNT(*) as mac_moves
FROM raw_outputs r
WHERE r.command = 'show mac address-table vlan 100'
  AND DATE_DIFF('day', r.created_at, NOW()) <= 1
GROUP BY r.device
HAVING COUNT(*) > 5;
```

---

### Phase 3: Hypothesis Formation (5-15 minutes)

**Goal**: Create 2-3 testable hypotheses

**Using Knowledge Base**:
1. Search similar cases: `search_similar_cases("BGP flapping")`
2. Identify patterns from historical data
3. Form hypotheses based on known failure modes

**Common Root Causes by Problem Type**:

| Symptom | L1 | L2 | L3 | L4-L7 |
|---------|----|----|----|----|
| **Device isolated** | No link | MAC flood/STP block | No route | ACL/firewall |
| **Slow throughput** | FCS errors | Congestion/queuing | Slow path (higher hop) | Retransmits |
| **Intermittent loss** | Optics/dirty | LACP flap/loop | MTU mismatch | App crash |
| **High latency** | Not at L1 | STP reconvergence | Suboptimal routing | Device CPU |
| **Protocol flapping** | Link flap | Loop or loop protection | Metric change | Timer mismatch |

**Example Hypotheses**:
- **H1**: BGP neighbor flapping due to interface error threshold exceeded → Check interface CRC errors
- **H2**: BGP decision change due to metric update → Check OSPF/IGP convergence
- **H3**: BGP peering reset due to authentication failure → Check log messages

**Validation Strategy**:
```
Hypothesis → Evidence Query → Result → Confidence
   ↓            ↓             ↓        ↓
H1: Interface errors > 10/sec
   SELECT interface, crc_errors FROM interfaces
   WHERE hostname = 'device-x' AND crc_errors > 10
   Result: CRC=847 → HIGH confidence

H2: OSPF metric changed
   SELECT timestamp, ospf_metric FROM routing_history
   WHERE protocol = 'OSPF' AND interface = 'Gi0/0/1'
   Result: Metric 1000→5000 at 14:32 → MEDIUM confidence

H3: BGP auth failure
   SELECT log_entry FROM device_logs
   WHERE hostname = 'device-x' AND entry LIKE '%auth%'
   Result: No auth failures → LOW confidence in H3
```

---

### Phase 4: Root Cause Validation (10-20 minutes)

**Goal**: Confirm root cause with multiple evidence sources

**Multi-Source Correlation**:

1. **Database Evidence**: Historical data, configurations
2. **Topology Context**: Failure domain boundaries
3. **Config Comparison**: Current vs design intent
4. **Time Correlation**: When did symptoms start? When did config change?
5. **Pattern Matching**: Known bugs, vendor advisories

**Validation Checklist**:
- [ ] Root cause explains all observed symptoms
- [ ] Evidence from at least 2 independent sources
- [ ] Time correlation makes sense (cause precedes effect)
- [ ] Scope bounded to explanation (not affecting unrelated devices)
- [ ] Matches known failure mode or new pattern

**Example Validation**:

```
Root Cause Hypothesis: SFP optics failure on device-x Gi0/1

Evidence 1 (Database):
  - Interface CRC errors: 1500+ (normal: <10)
  - Link flaps: Every 2-3 seconds (last 1 hour)
  - Interface down/up state changes: 847 (24h)
  → Confidence: HIGH

Evidence 2 (Config):
  - Interface configured correctly (no typos, correct VLAN)
  - Neighbor config matches (same VLAN, same speed)
  → Confidence: MEDIUM (rules out config issue)

Evidence 3 (Device logs):
  - SFP signal loss warnings (last 30 minutes)
  - "Signal loss detected on port Gi0/1"
  → Confidence: VERY HIGH (direct evidence)

Evidence 4 (Topology):
  - Device-x is aggregation layer
  - Failure impacts 24 downstream access ports
  → Confidence: HIGH (explains reported outages)

VALIDATION RESULT: ROOT CAUSE CONFIRMED
  Conclusion: SFP optics failure causing persistent link flap
```

---

### Phase 5: Solution Delivery (5-30 minutes)

**Five-Part Solution Structure**:

#### 1. Root Cause (Clear, Technical Explanation)

*Template*:
```
The root cause is [technical explanation].

Evidence:
- [Database/config evidence]
- [Topology context]
- [Device logs/real-time data]

Impact:
- Devices affected: [list]
- Protocols impacted: [list]
- Users/services: [list]
```

**Example**:
```
Root Cause: SFP transceiver failure on device-x Gi0/1

Evidence:
- Interface CRC errors exceeded 1500 in 24h (normal: <10)
- Link state changed 847 times in 24h (normal: 0)
- SFP signal loss warnings in device logs (last 30 minutes)
- All upstream BGP neighbors experiencing flaps

Impact:
- 24 access switches losing uplink every 2-3 seconds
- VLAN 100-110 experiencing packet loss
- BGP convergence failing due to constant neighbor resets
```

#### 2. Impact Assessment

*Scope* (affected devices, protocols, users):
```
Failure Domain:
[Diagram or text description of scope]

Affected Services:
- VLAN 100: Production data (200+ users) - CRITICAL
- VLAN 110: Guest network (50 users) - MAJOR
- BGP routes via device-x: 847 prefixes - CRITICAL

Estimated Recovery Time (MTTR): 15 minutes (SFP replacement)
Business Impact: $50K/hour downtime (if production)
```

#### 3. Fix (Step-by-Step Commands)

*Format* (device-focused, ordered by criticality):

```
IMMEDIATE (now):
1. Replace SFP on device-x Gi0/1
   - Obtain spare SFP (compatible with device model)
   - Remove failed SFP from Gi0/1
   - Insert new SFP (LED should become green in 10 seconds)
   - Wait 30 seconds for interface to stabilize

2. Verify interface recovery
   device-x# show interface Gi0/1
   --> Status should be "up, up" (not flapping)
   
   device-x# show interface Gi0/1 | include CRC
   --> CRC errors should STOP increasing

WITHIN 1 HOUR (complete):
3. Clear BGP on upstream devices to accelerate recovery
   bgp-rr# clear ip bgp * soft in/out
   
4. Verify BGP convergence
   bgp-rr# show ip bgp summary | include 'established|not established'
   --> All neighbors should show "established"

5. Verify data plane recovery
   device-x# ping [downstream-device-ip]
   --> Ping should succeed with 0% loss (previously 30%+)
```

#### 4. Validation (Prove Fix Worked)

*Verification Steps*:

```
Post-Fix Verification:

1. Interface Health
   device-x# show interface Gi0/1
   Status: up, up
   Input queue: 0/75/0
   Output queue: 0/40/0
   Collisions: 0
   ✓ PASS: No errors, stable state

2. Protocol Recovery
   device-x# show ip bgp summary | include 'established|not established'
   Neighbor         State       Up/Down
   10.0.0.1         Established 00:05:32
   10.0.0.2         Established 00:04:18
   ✓ PASS: All neighbors established, stable for >4 minutes

3. Data Path Validation
   device-x# show ip route | include [route summary]
   ✓ PASS: All expected routes present

4. User Impact
   Application team: "Network restored, users reporting normal performance"
   ✓ PASS: Business KPIs restored
```

#### 5. Prevention (Prevent Recurrence)

*Three-Part Prevention*:

1. **Immediate Monitoring** (next 24 hours)
   - Alert on CRC errors > 10/sec
   - Alert on link state changes > 5 in 5 minutes
   - Monitor SFP temperature (if supported)

2. **Design Changes** (implement this week)
   - Qualify spare SFP inventory (model, revision)
   - Add link aggregation (LACP) for redundancy on critical links
   - Implement FastHello on BGP for faster failure detection
   - Enable physical interface status trap for SNMP alerting

3. **Operational Changes** (implement this month)
   - Add SFP lifecycle tracking (purchase date, operation hours)
   - Proactive SFP replacement at 5-year mark or 100K hours
   - Quarterly SFP cleaning/inspection protocol
   - Add BGP BFD (Bidirectional Forwarding Detection) for faster convergence

---

## Root Cause Analysis (RCA) Methodology

### 7-Step Process

1. **Symptom Collection** (What failed?)
   - User reports, monitoring alerts, device/app logs
   - Scope: specific user, VLAN, site, or entire network?
   - Duration: transient, intermittent, or persistent?

2. **Scope Definition** (What failed, not why?)
   - Devices: isolate affected hardware
   - Protocols: identify broken functionality
   - Layers: L1 (physical), L2 (switching), L3 (routing), or L4+ (application)?
   - Time window: when did symptoms start?

3. **Hypothesis Formation** (What might have caused it?)
   - Use knowledge base: `search_similar_cases()`
   - Match symptom to known failure patterns
   - Form 2-3 ranked hypotheses

4. **Evidence Collection** (What does the data say?)
   - Query database for historical state
   - Analyze topology (failure domain context)
   - Verify current state (real-time CLI if needed)
   - Check device/system logs

5. **Hypothesis Validation** (Which hypothesis is correct?)
   - Multiple evidence sources must align
   - Time sequence must make sense
   - Scope must match hypothesis

6. **Root Cause Analysis** (Why did it really happen?)
   - Technical explanation (not just "interface down")
   - Complete narrative: trigger → failure → symptom
   - Operational context (recent changes, deployment, upgrade?)

7. **Solution & Prevention** (How do we fix and prevent?)
   - Immediate fix (restore service)
   - Remediation (long-term solution)
   - Prevention (design/operational changes)
   - Rollback plan (if fix doesn't work)

---

## Case Studies: Deep Diagnosis

### Case 1: BGP Route Flapping (Intermittent Connectivity)

**Symptoms Reported**:
- Connectivity to branch office intermittent for 30 minutes then cleared
- VPN tunnel to branch goes down/up repeatedly
- Packet loss to branch site: 30-40%

**Assessment** (Phase 1):
- Scope: Branch WAN connectivity
- Type: Routing protocol failure
- Severity: CRITICAL (business service down)
- Affected devices: HQ border router, Branch CPE, Branch ISP circuit

**Evidence Collection** (Phase 2):

```sql
-- Check BGP neighbor state history
SELECT bgp_neighbor, state, state_change_time
FROM bgp_history
WHERE bgp_neighbor = '203.0.113.1' (branch CPE)
  AND state_change_time > NOW() - INTERVAL '1 hour'
ORDER BY state_change_time DESC;

Result: Established → Down → Established (flapping every 2-3 min)
```

```
HQ Border Router Logs:
  14:32:01 BGP: Connection established to 203.0.113.1
  14:34:45 BGP: Connection lost to 203.0.113.1 (Sent NOTIFICATION)
  14:37:12 BGP: Connection established to 203.0.113.1
  14:39:58 BGP: Connection lost to 203.0.113.1
```

**Hypotheses** (Phase 3):
1. BGP authentication failure (password mismatch)
2. BGP scanner timeout (neighbor not responding)
3. Interface instability (link flapping)
4. ISP circuit problem (packet loss causing BGP to time out)

**Validation** (Phase 4):

```sql
-- Check interface state
SELECT interface, state_changes, crc_errors
FROM interface_history
WHERE hostname = 'hq-border-1' AND interface = 'Gi0/0/1'
  AND time_range = 'last 60 minutes';

Result: 0 state changes, 0 CRC errors
Conclusion: Interface is STABLE (rules out H3)
```

```sql
-- Check BGP authentication config
SELECT config_item 
FROM device_configs
WHERE device = 'hq-border-1' AND line LIKE '%neighbor 203.0.113.1%auth%';

Result: 
  neighbor 203.0.113.1 password ABCD1234
  
SELECT config_item 
FROM device_configs
WHERE device = 'branch-cpe' AND line LIKE '%neighbor 10.0.0.1%auth%';

Result:
  neighbor 10.0.0.1 password ABCD1234
  
Conclusion: Auth configs MATCH (rules out H1)
```

```
Device Logs Detail:
BGP: Sent NOTIFICATION to 203.0.113.1 (Hold Timer Expired)

Root Cause Hypothesis: BGP hold timer expiring
  → BGP expects keepalive every 10 seconds
  → If no keepalive received in 30 seconds (hold timer), neighbor is down
  → Indicates: Neighbor not responding or losing packets
```

**Validation Continued**:

```sql
-- Check ISP circuit packet loss
SELECT timestamp, packet_loss_percent, latency_ms
FROM circuit_monitoring
WHERE circuit = 'ISP-WAN-Branch'
  AND timestamp > NOW() - INTERVAL '60 minutes'
ORDER BY timestamp DESC;

Result: 
  14:34:00 - packet_loss=42%, latency=450ms (normal: 25ms)
  14:36:30 - packet_loss=38%, latency=425ms
  14:39:00 - packet_loss=45%, latency=475ms
  
Conclusion: ISP packet loss correlates with BGP flaps!
```

**Root Cause** (Phase 5.1):
```
ISP WAN circuit degraded with ~40% packet loss.

Evidence:
- BGP keepalive packets lost
- Hold timer expires (no keepalives received for >30 seconds)
- BGP brings neighbor down
- When packet loss improves, keepalives get through
- BGP reconverges
- Symptoms disappear until next loss spike

Technical Narrative:
  HQ Border Router sends BGP keepalive every 10 seconds to Branch CPE
  → ISP circuit loses ~40% of packets (degraded hardware/congestion)
  → Branch doesn't receive keepalive for >30 seconds (hold timer)
  → Branch considers HQ router dead, brings neighbor down
  → BGP routes withdrawn, VPN fails, connectivity lost
  → When packet loss improves, keepalives get through
  → Neighbor comes back up, routes readvertised
  → Intermittent pattern: flaps every 2-3 minutes
```

**Impact Assessment** (Phase 5.2):
```
Affected Services:
- Branch Office connectivity: CRITICAL (business stopped)
- 150 users without access to corporate network
- Estimated business impact: $10K+ per hour lost productivity
```

**Fix** (Phase 5.3):
```
IMMEDIATE:
1. Contact ISP to investigate WAN circuit health
   - Request circuit diagnostics
   - Check for packet loss on provider side
   - Swap physical interfaces/cards if available

2. Reduce BGP timers temporarily (faster detection)
   HQ Border:
     router bgp 65000
       neighbor 203.0.113.1 timers 5 15
       (keepalive 5 seconds, hold 15 seconds)
   
   Branch CPE (notify ISP/branch IT):
     router bgp 65001
       neighbor 10.0.0.1 timers 5 15

3. Enable BGP BFD for faster failure detection
   HQ Border:
     router bgp 65000
       neighbor 203.0.113.1 fall-over bfd single-hop

WITHIN 8 HOURS:
4. ISP repairs circuit
   - Likely: Hardware replacement or service restoration
   - Packet loss returns to normal (<1%)

5. Validate recovery
   show ip bgp summary | include 'established|not established'
   show bgp ipv4 unicast summary
   ping branch-site (should succeed with 0% loss)
```

**Validation** (Phase 5.4):
```
Post-Fix:
✓ BGP neighbor established and stays up for >30 minutes
✓ BGP hold timers no longer expiring
✓ ISP circuit packet loss restored to <1%
✓ Branch connectivity restored, users report normal access
✓ VPN tunnel stable
```

**Prevention** (Phase 5.5):
```
1. Immediate Monitoring (24 hours)
   - Alert if packet loss > 5% to any WAN circuit
   - Alert if BGP neighbor flaps > 1 time per hour
   - Alert if hold timer expires

2. Design Changes (implement this week)
   - Consider redundant ISP circuits (active/active or active/backup)
   - Deploy BGP BFD on all BGP sessions
   - Implement faster convergence timers for critical circuits

3. Operational Changes (implement this month)
   - Add WAN circuit health monitoring to NOC dashboard
   - Quarterly circuit performance review
   - ISP SLA review: ensure packet loss guarantees met
4. Vendor Management (next quarter)
   - Negotiate circuit SLA: max 1% packet loss, <50ms latency
   - Add penalty clause for SLA violations
```

---

### Case 2: VXLAN MAC Mobility Storm (Data Center)

**Symptoms**:
- Server in Pod-A losing connectivity repeatedly
- VXLAN tunnel flapping between leaf switches
- MAC address moving between leaf servers every 2-3 seconds

**Diagnosis Summary**:

| Phase | Action | Finding |
|-------|--------|---------|
| 1. Assessment | Scope: Pod-A leaf pair, VXLAN tunnel state, MAC table | Server MAC moving between leaves |
| 2. Evidence | Query VXLAN state, MAC table changes, topology | MAC appeared on different leaf 847 times in 30 min |
| 3. Hypothesis | H1: ARP suppression mismatch; H2: Duplicate MAC; H3: Network loop | H1 most likely |
| 4. Validation | Compare leaf configs, check ARP suppression setting | Leaf-A has ARP suppression DISABLED; Leaf-B ENABLED |
| 5. Solution | Enable ARP suppression on Leaf-A to match Leaf-B | Flapping stopped immediately |

**Commands**:
```
Leaf-A:
  config terminal
  l2vpn evpn instance 100
    replication-type ingress  # Keep existing
    duplicate-mac-timer 180   # Add: prevent flapping
    no suppress-arp          # CHANGE: was suppressing=DISABLED
    suppress-arp             # ADD: enable ARP suppression

Leaf-B (verify):
  show l2vpn evpn instance 100 detail
  --> suppress-arp: Enabled ✓

Verification:
  show mac address-table vxlan | include [server-mac]
  --> Should show SINGLE leaf (not moving around)
```

---

### Case 3: MPLS VPN Route Leaking (Service Provider)

**Symptoms**:
- Customer A can reach Customer B networks (should be isolated)
- Traffic appears in wrong VRF on PE router

**Root Cause**:
```
Route Target export/import mismatch on PE router.

PE-1 Config (wrong):
  vrf CustomerA
    route-target export 65000:100
    route-target import 65000:200  ← WRONG! Should be 65000:100
  
Consequence:
  CustomerA routes exported as 65000:100
  PE-1 imports only 65000:200 (misses own routes)
  CustomerA routes leaked to other VRFs importing 65000:100

Fix:
  vrf CustomerA
    no route-target import 65000:200
    route-target import 65000:100  ← Correct import
  
  clear bgp vpnv4 unicast *
  
Validation:
  show ip routes vrf CustomerA
  show bgp vpnv4 unicast all summary
  --> No customer-to-customer routes
```

---

## Common Problem Decision Tree

```
Network Problem Reported
  │
  ├─ Connectivity Issue?
  │  ├─ Ping fails → L3 diagnosis (routing, IP reachability)
  │  │  ├─ All devices affected? → Backbone issue, check core routing
  │  │  └─ Specific device/VLAN? → Query route table, check BGP/OSPF state
  │  │
  │  └─ Ping succeeds, app fails → L4-L7 diagnosis (TCP/UDP, QoS, firewall)
  │     ├─ Query port is open → Check ACL, firewall, app logs
  │     └─ Port not responding → Check app health, NLB distribution
  │
  ├─ Performance Issue?
  │  ├─ High latency? → Query L3 routing (suboptimal path), L2 (congestion), L1 (optics)
  │  ├─ Low throughput? → Check interface errors, queuing, QoS policies
  │  └─ Intermittent? → Check interface flaps, neighbor instability, thermal
  │
  ├─ Protocol Flapping?
  │  ├─ BGP/OSPF flaps? → Check interface state, hello/dead timers, authentication
  │  ├─ STP converging? → Check loop, BPDU guard, root bridge priority
  │  └─ LACP changing state? → Check member port health, config consistency
  │
  └─ Configuration Drift?
     ├─ Compare device config to golden standard
     └─ Query: `compare_device_configs(['device1', 'device2'])`
```

---

## Tool Collaboration Patterns

### Pattern 1: Scope Expansion (analyze_topology + get_device_peers)

```
Problem: Link down on device-a

Step 1: analyze_topology()
  → Discover device-a connects to: device-b, device-c, device-d

Step 2: get_device_peers('device-a')
  → Return nested neighbors of device-a
  → Identify failure domain (all devices relying on device-a)

Step 3: Query impact
  SELECT COUNT(*) AS affected_endpoints
  FROM devices d
  WHERE d.site = 'site-x' AND d.upstream_device = 'device-a'
```

### Pattern 2: Config Validation (query_database + compare_device_configs)

```
Problem: Interface negotiation failing

Step 1: Query database
  SELECT interface_config, negotiation, speed, duplex
  FROM device_configs
  WHERE device IN ('device-x', 'device-y')

Step 2: compare_device_configs(['device-x', 'device-y'])
  → Highlight differences:
    device-x: speed=1000, duplex=full, negotiate=ON
    device-y: speed=100, duplex=half, negotiate=OFF
  
Root Cause: Speed/duplex mismatch

Fix: Sync configs
```

### Pattern 3: Historical Analysis (search_similar_cases + query_database)

```
Problem: BGP flapping every Tuesday night

Step 1: search_similar_cases('BGP flapping periodic')
  → Find Case #487: "Tuesday maintenance at 9 PM causes BGP resets"
  → Solution documented: Increase BGP hold timer

Step 2: query_database()
  SELECT timestamp, bgp_flaps
  FROM bgp_history
  WHERE DAYOFWEEK(timestamp) = 3  -- Tuesday
    AND HOUR(timestamp) = 21      -- 9 PM
  
Result: Confirms pattern, every Tuesday 21:00-21:30

Root Cause: Scheduled maintenance task

Fix: Implement BGP graceful restart or maintenance window notification
```

---

## Common Mistakes & Solutions

### Mistake 1: "The Interface is Down"

❌ **Wrong**: "Interface Gi0/0/1 is down"  
✓ **Correct**: "Interface Gi0/0/1 is down due to SFP signal loss (optical power insufficient). Fix: Replace SFP transceiver."

**Why**: "Down" is a symptom, not a root cause. Always explain WHY it's down.

---

### Mistake 2: "BGP Isn't Working"

❌ **Wrong**: "Device-x cannot reach 10.0.0.0/24 because BGP isn't working"  
✓ **Correct**: "Device-x cannot reach 10.0.0.0/24 because:
1. BGP neighbor to device-y is down (authentication failure)
2. Device-y has 10.0.0.0/24 in its advertised routes
3. Fix: Sync BGP password: both devices must use same password"

**Why**: BGP has many failure modes (auth, timers, config, ASN mismatch, etc.). Specify which one.

---

### Mistake 3: Assuming Without Verification

❌ **Wrong**: "The database shows VLAN 100 has 5 interfaces"  
✓ **Correct**: 
```sql
SELECT COUNT(*) FROM device_configs
WHERE config LIKE '%vlan 100%'

Result: 5 records → Verified
```

**Why**: Database can be out of sync (if not updated regularly). Cross-check with device reality.

---

### Mistake 4: Ignoring Time Context

❌ **Wrong**: "Interface has CRC errors"  
✓ **Correct**: "Interface accumulated 1500 CRC errors over the last 4 hours (normal: <10). The flap rate increased from 2/min to 5/sec in the last 10 minutes, suggesting SFP degradation."

**Why**: Time sequence matters—is it new or old? Is it accelerating? These guide the diagnosis.

---

### Mistake 5: Not Checking Config Sync

❌ **Wrong**: "Both routers configured for BGP"  
✓ **Correct**: 
```
Router-A: neighbor 10.0.0.2 remote-as 65001 password ABC123
Router-B: neighbor 10.0.0.1 remote-as 65002 password XYZ789

Mismatch:
1. ASN incorrect (65001 vs 65002)
2. Password differs (ABC123 vs XYZ789)
```

**Why**: BGP requires exact match on both sides. One mistake = neighbor down.

---

## Quick Reference: Diagnosis Checklist

```
PRE-DIAGNOSIS:
[ ] Understand problem scope (device? VLAN? site? entire network?)
[ ] Get timeline (when did symptoms start?)
[ ] Identify business impact (critical? non-critical?)

PHASE 1-2 (Assessment + Evidence):
[ ] Run: SELECT * FROM devices WHERE ...
[ ] Run: inspect_schema() to verify table availability
[ ] Run: analyze_topology() for failure domain
[ ] Run: search_similar_cases() for historical matches

PHASE 3-4 (Hypothesis + Validation):
[ ] Form 2-3 hypotheses (not just 1!)
[ ] Validate with multiple evidence sources
[ ] Confirm time sequence makes sense

PHASE 5 (Solution):
[ ] Root cause: Clear technical explanation
[ ] Impact: List affected devices, users, services
[ ] Fix: Step-by-step commands (device-specific)
[ ] Validation: Prove fix worked with queries/commands
[ ] Prevention: Design changes, monitoring alerts, operational changes
[ ] Rollback: How to undo if fix doesn't work

DOCUMENTATION:
[ ] Create case entry for knowledge base
[ ] Update monitoring/alerting if new issue type
[ ] Share lessons learned with team
```

---

## Expert Communication Templates

### For 15-Minute Diagnosis (Simple)

```
Problem: [1 sentence symptom]

Root Cause: [Technical explanation with evidence]

Fix: [3-5 commands]

Result: [Confirmation it worked]

Time Saved: [vs manual troubleshooting]
```

### For 30-Minute+ Diagnosis (Complex)

```
EXECUTIVE SUMMARY
Problem: [Business impact in plain English]
Status: [Diagnosed / In Progress / Fixed]
Time to Resolution: [Estimated X hours]

TECHNICAL ANALYSIS
Root Cause: [Full explanation]
Timeline: [When it started, how it evolved]
Scope: [Devices/services affected]

REMEDIATION PLAN
Phase 1 (Immediate): [Fix to restore service]
Phase 2 (Stabilization): [Prevent recurrence for 24h]
Phase 3 (Long-term): [Design/operational changes]

PREVENTION
Monitoring: [New alerts to catch this earlier]
Design changes: [Architectural improvements]
Operational: [Procedure changes]

ROLLBACK PLAN
If fix doesn't work: [Undo steps and escalation path]
```

---

**Version**: Comprehensive diagnostic framework for CCIE-level expert diagnosis
