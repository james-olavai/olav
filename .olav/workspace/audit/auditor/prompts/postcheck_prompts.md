# Post-Check Prompt Templates

## Purpose
This file defines the `olav -a ops` prompt templates used to generate
the Closed-Loop Post-Check Playbook at the bottom of every audit report.
Templates are populated deterministically from incident cluster and findings data —
no additional LLM call is required.

Operators copy-paste the generated prompts into their terminal to invoke
the Ops Agent's networkx topology simulation and device-level verification.

---

## Template: Incident Cluster (top priority — topology root-cause confirmed)

```
olav -a ops "Cluster analysis: {cascade_summary}. Use networkx to simulate removal
of root device {root_device} and identify topology impact:
1. Identify all downstream devices losing primary paths
2. Verify redundant path coverage (secondary path analysis)
3. Calculate impact radius (affected device count / link count)
4. If redundant paths exist, suggest recovery sequence; else suggest isolation plan"
```

## Template: BGP_Not_Established / BGP_Drift

```
olav -a ops "{device} BGP neighbor {neighbor_ip} state anomaly (current: {state}):
1. SSH login to {device}, run 'show bgp neighbor {neighbor_ip}', confirm Hold Timer / Reset reason
2. Use networkx to simulate BGP session down and analyze route propagation impact
3. Verify peer {neighbor_ip} interface status and AS number match"
```

## Template: Interface_Down / Interface_State_Drift

```
olav -a ops "{device} interface {interface} state drift:
1. SSH login to {device}, run 'show interfaces {interface}', confirm line protocol and CRC / input errors
2. Use networkx to check both sides of this link, determine if backup paths exist
3. If physical layer issue suspected, run optical power check: 'show interfaces {interface} transceiver'"
```

## Template: OSPF_Not_Full / OSPF_Drift

```
olav -a ops "{device} OSPF neighbor not in FULL state:
1. SSH login to {device}, run 'show ip ospf neighbor detail', confirm Dead Timer and State
2. Verify MTU match and Hello/Dead interval configuration on both sides
3. Use networkx to analyze OSPF area route connectivity impact"
```

## Template: CPU_Anomaly / Memory_Anomaly (Welford baseline)

```
olav -a ops "{device} CPU/Memory statistical anomaly (z_score={z_score}, mean={mean}, current={value}):
1. SSH login to {device}, run 'show processes cpu sorted | head 20'
2. Correlate with logs: 'show logging | include CPU' or 'show logging | include memory'
3. Check for concurrent BGP route churn or high ACL hit counts at this timestamp"
```

## Template: Config_Drift / STP_Drift

```
olav -a ops "{device} configuration changed (diff: {delta_lines} lines):
1. Read raw_diffs for {device} latest diff_content
2. Determine if this is planned maintenance (within scheduled window) or unauthorized change
3. If STP/VLAN change detected, use networkx to simulate spanning tree topology and verify convergence"
```

## Template: Fallback (no structured data available)

```
olav -a ops "General health check on {device}:
run 'show version', 'show logging last 50', 'show interfaces summary', 'show processes cpu sorted | head 10'.
Compare against DuckDB historical snapshots and confirm state stable within inspection window"
```
