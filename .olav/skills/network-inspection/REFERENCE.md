# Network Health Inspection - Advanced Reference

## Health Scoring Algorithm

### Core Formula

```
Device Health Score = 100 - (critical_violations × 20 + warning_violations × 5)

Capped to: 0-100 range
```

### Layer Thresholds (Configurable)

**Critical Violations** (-20 points each):
- L1: Device down, no uptime
- L2: All interfaces down, network isolated
- L3: No routing protocol neighbors, isolated from network
- L4: CPU >95% or memory >95% (system critical)

**Warning Violations** (-5 points each):
- L1: Device uptime <24 hours, outdated version
- L2: Interface down, high CRC errors (>100/hour), frequent flaps (>10/hour)
- L2: Neighbor count decreased by >20%
- L3: Routing protocol flapping, suboptimal metrics
- L3: Missing expected routes, incomplete table
- L4: CPU 80-95%, memory 85-95%

### Example Scoring

```
Device R1:
- L1: OK (device up, good uptime)
- L2: Interface Gi0/0/1 down (-20 critical)
- L3: BGP neighbors established, all routes present
- L4: CPU 35%, memory 42%

Score: 100 - (1 × 20 + 0 × 5) = 80 (WARNING)
```

### Overall Network Score

```
Network Health = Average of all device scores

Score Range:
- 90-100: ✅ Healthy
- 70-89: ⚠️ Warning
- 0-69: 🔴 Critical
```

---

## Layer-by-Layer Analysis

### Layer 1: Physical Layer (Device Status)

**What to Check**:
- Device up/down status
- System uptime
- OS version (recent vs outdated)
- Power supply status (if available)
- Thermal status (if available)

**Health Queries**:

```sql
-- Device inventory health
SELECT hostname, is_active, version, 
       DATEDIFF(day, last_reboot, NOW()) as uptime_days
FROM devices
ORDER BY is_active DESC, uptime_days;

-- Devices down longer than baseline
SELECT hostname, is_active
FROM devices
WHERE is_active = FALSE
  AND last_status_change < NOW() - INTERVAL '4 hours';
```

**Scoring**:
- ✅ Device active: +0 (baseline)
- ⚠️ Uptime <24h: -5 (warning)
- 🔴 Device inactive >1h: -20 (critical)
- ⚠️ Version outdated (>2 major releases): -5

---

### Layer 2: Data Link Layer

#### Interfaces

**What to Check**:
- Interface up/down state
- Error counters (CRC, align, collisions)
- Link flap frequency
- Bandwidth utilization
- Frame size (MTU)

**Health Queries**:

```sql
-- Interface error summary
SELECT d.hostname, i.interface, i.state, 
       SUM(r.crc_errors) as crc_total,
       COUNT(DISTINCT r.timestamp) as change_count
FROM devices d
JOIN interfaces i ON d.hostname = i.device
LEFT JOIN raw_outputs r ON d.hostname = r.device 
  AND r.command LIKE '%show interface%'
WHERE r.timestamp > NOW() - INTERVAL '1 hour'
GROUP BY d.hostname, i.interface
HAVING crc_total > 100 OR change_count > 10;

-- Interfaces down (critical)
SELECT hostname, interface, state
FROM interfaces
WHERE state = 'down'
  AND is_critical = TRUE;
```

**Scoring**:
- ✅ Interface up, no errors: +0
- ⚠️ CRC errors 10-100/hour: -5
- 🔴 CRC errors >100/hour or interface down: -20
- ⚠️ Link flaps >5/hour: -5
- 🔴 Link flaps >10/hour: -20

#### Neighbors (CDP/LLDP)

**What to Check**:
- Neighbor count (stable vs changed)
- Neighbor discovery protocol responsiveness
- Topology consistency

**Health Queries**:

```sql
-- Neighbor count tracking
SELECT d.hostname, COUNT(DISTINCT neighbor) as neighbor_count
FROM devices d
LEFT JOIN neighbors n ON d.hostname = n.device
GROUP BY d.hostname;

-- Neighbor count change detection
SELECT hostname, 
       LAG(neighbor_count) OVER (PARTITION BY hostname ORDER BY timestamp) as prev_count,
       neighbor_count,
       neighbor_count - LAG(neighbor_count) OVER (PARTITION BY hostname ORDER BY timestamp) as diff
FROM neighbor_history
WHERE timestamp > NOW() - INTERVAL '24 hours';
```

**Scoring**:
- ✅ Neighbors stable: +0
- ⚠️ Neighbor count decreased by 10-20%: -5
- 🔴 Neighbor count decreased >20% or neighbors missing: -20

---

### Layer 3: Network Layer

#### Routing Protocols (OSPF, BGP, EIGRP)

**What to Check**:
- Neighbor state (established vs down)
- Neighbor transitions (flapping)
- Protocol metrics stability

**Health Queries**:

```sql
-- BGP neighbor state summary
SELECT d.hostname, r.peer_asn, count(*) as state_changes, 
       FIRST(state) as current_state,
       DATEDIFF(minute, MAX(timestamp), NOW()) as last_update_minutes_ago
FROM devices d
JOIN bgp_neighbors bn ON d.hostname = bn.device
LEFT JOIN raw_outputs r ON d.hostname = r.device 
  AND r.command = 'show ip bgp summary'
WHERE r.timestamp > NOW() - INTERVAL '24 hours'
GROUP BY d.hostname, r.peer_asn
HAVING state_changes > 10;

-- OSPF neighbor state
SELECT hostname, neighbor_id, state, 
       DATEDIFF(second, last_state_change, NOW()) as stable_seconds
FROM ospf_neighbors
WHERE last_state_change > NOW() - INTERVAL '1 hour';
```

**Scoring**:
- ✅ All neighbors established, no changes: +0
- ⚠️ Neighbor flapping 2-5 times/hour: -5
- 🔴 Neighbor down or flapping >5 times/hour: -20

#### Routing Tables

**What to Check**:
- Route count (all expected routes present)
- Route stability (no withdrawals/readvertisements)
- Suboptimal routing (inconsistent metrics)

**Health Queries**:

```sql
-- Route count by protocol
SELECT hostname, protocol, COUNT(*) as route_count
FROM routes
GROUP BY hostname, protocol;

-- Route completeness (expected vs actual)
SELECT hostname, 
       (SELECT COUNT(*) FROM routes WHERE hostname = d.hostname) as current_routes,
       expected_routes,
       expected_routes - current_routes as missing_routes
FROM device_baselines d
WHERE expected_routes > 0;

-- Route flapping detection
SELECT ip_prefix, COUNT(*) as changes_in_1h
FROM route_history
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY ip_prefix
HAVING changes_in_1h > 5;
```

**Scoring**:
- ✅ All expected routes, stable: +0
- ⚠️ Missing <10% routes or high flap rate: -5
- 🔴 Missing >10% routes or critical routes down: -20

---

### Layer 4: Application/Performance Layer

**What to Check**:
- CPU utilization
- Memory utilization
- Logging rate
- BGP route processor load

**Health Queries**:

```sql
-- CPU and memory utilization
SELECT d.hostname, MAX(cpu_percent) as max_cpu, MAX(memory_percent) as max_memory
FROM devices d
JOIN system_metrics m ON d.hostname = m.device
WHERE m.timestamp > NOW() - INTERVAL '1 hour'
GROUP BY d.hostname
HAVING max_cpu > 80 OR max_memory > 85;

-- Process accounting (high CPU processes)
SELECT hostname, process_name, cpu_percent
FROM process_stats
WHERE cpu_percent > 50
  AND timestamp > NOW() - INTERVAL '10 minutes'
ORDER BY cpu_percent DESC;
```

**Scoring**:
- ✅ CPU <60%, memory <70%: +0
- ⚠️ CPU 60-80% or memory 70-85%: -5
- 🔴 CPU >80% or memory >85%: -20

---

## Markdown Report Template

Generate a production-grade markdown report with this template:

```markdown
# 🔍 Network Inspection Report

**Inspection Time**: {{ timestamp }}  
**Generated**: OLAV v0.9.8  
**Report Location**: {{ config.paths.REPORTS_DIR }}

---

## 📊 Executive Summary

**Overall Network Health**: {{ overall_score }}/100 {{ health_emoji }}

| Metric | Value | Status |
|--------|-------|--------|
| Total Devices | {{ total_devices }} | - |
| Healthy | {{ healthy_devices }} | ✅ |
| Warning | {{ warning_devices }} | ⚠️ |
| Critical | {{ critical_devices }} | 🔴 |
| Network Availability | {{ availability_percent }}% | {{ availability_status }} |

---

## 📈 Device Health Matrix

| Device | L1 | L2 | L3 | L4 | Score | Status |
|--------|----|----|----|----|-------|--------|
{% for device in devices -%}
| {{ device.hostname }} | {{ device.l1_status }} | {{ device.l2_status }} | {{ device.l3_status }} | {{ device.l4_status }} | {{ device.score }}/100 | {{ device.status_emoji }} |
{% endfor %}

---

## 🔴 Critical Issues ({{ critical_issues|length }})

{% if critical_issues %}
Critical issues require immediate attention:

{% for issue in critical_issues -%}
### {{ issue.device }} - {{ issue.category }}

**Layer**: {{ issue.layer }}  
**Current Value**: {{ issue.value }}  
**Threshold**: {{ issue.threshold }}  
**Impact**: {{ issue.impact }}

**Recommended Action**:
{{ issue.recommendation }}

---

{% endfor %}
{% else %}
No critical issues detected. ✅

{% endif %}

## ⚠️ Warning Issues ({{ warning_issues|length }})

{% if warning_issues %}
Warning issues should be monitored and addressed within 24-48 hours:

{% for issue in warning_issues -%}
### {{ issue.device }} - {{ issue.category }}

**Layer**: {{ issue.layer }}  
**Current Value**: {{ issue.value }}  
**Threshold**: {{ issue.threshold }}  
**Status**: {{ issue.status }}

**Suggested Fix**:
{{ issue.suggestion }}

---

{% endfor %}
{% else %}
No warning issues detected. ✅

{% endif %}

## 💡 Recommendations

### 🚨 Immediate Actions Required (Next 1-4 hours)
{% for action in immediate_actions -%}
- {{ action }}
{% else -%}
- No immediate actions required
{% endfor %}

### 📅 Short-Term Improvements (Next 1-2 weeks)
{% for action in short_term_actions -%}
- {{ action }}
{% else -%}
- No short-term improvements recommended
{% endfor %}

### 🔧 Long-Term Optimization (Next 1-3 months)
{% for suggestion in long_term_suggestions -%}
- {{ suggestion }}
{% else -%}
- No long-term optimizations recommended
{% endfor %}

---

## 📋 Layer Summary

### L1: Physical Layer
- **Status**: {{ l1_overall_status }}
- **Devices Up**: {{ l1_up }}/{{ total_devices }}
- **Issues**: {{ l1_issues_count }}

### L2: Data Link Layer
- **Status**: {{ l2_overall_status }}
- **Interfaces Up**: {{ l2_interface_up }}/{{ l2_interface_total }}
- **Neighbor Count**: {{ l2_neighbor_total }}
- **Issues**: {{ l2_issues_count }}

### L3: Network Layer
- **Status**: {{ l3_overall_status }}
- **Protocol Neighbors**: {{ l3_neighbor_count }}
- **Routes Expected**: {{ l3_route_count_expected }}
- **Routes Actual**: {{ l3_route_count_actual }}
- **Issues**: {{ l3_issues_count }}

### L4: Performance Layer
- **Status**: {{ l4_overall_status }}
- **Max CPU**: {{ l4_cpu_max }}%
- **Max Memory**: {{ l4_memory_max }}%
- **Issues**: {{ l4_issues_count }}

---

## 🔍 Detailed Findings

### Changed Devices (Last 24 hours)
- Devices with config changes: {{ config_changes_count }}
- Devices with state transitions: {{ state_changes_count }}
- New failures: {{ new_failures_count }}
- Recovered devices: {{ recovered_count }}

### Trends
- **Trending Up** (worsening): {{ trending_up_count }} devices
- **Trending Stable**: {{ trending_stable_count }} devices
- **Trending Down** (improving): {{ trending_down_count }} devices

---

## 📞 Next Steps

**If OK**: Schedule routine review in 7 days.

**If Warnings**: 
1. Review specific warnings above
2. Schedule remediation within 48 hours
3. Update baseline thresholds if needed

**If Critical**:
1. **Page on-call engineer** for immediate investigation
2. Review critical issues and recommended actions above
3. Target resolution: 4 hours
4. Post-incident review after fix

---

**Configuration Used**:
- Health Thresholds: `config/settings.py` + `.olav/config/health_thresholds.yaml`
- Scoring Weights: critical=-20pts, warning=-5pts
- Report Template: `.olav/skills/network-inspection/REFERENCE.md`

**Generated by**: OLAV Inspection Skill v2.2  
**Architecture**: Skill-Centric Agentic Design
```

---

## Anomaly Detection Strategies

### Strategy 1: Baseline Comparison

```sql
-- Current vs 7-day baseline
SELECT d.hostname,
       CURRENT.metric_value as now,
       BASELINE.metric_value as week_ago,
       ABS(CURRENT.metric_value - BASELINE.metric_value) as delta,
       ABS((CURRENT.metric_value - BASELINE.metric_value) / BASELINE.metric_value) as pct_change
FROM device_metrics CURRENT
JOIN device_metrics BASELINE
  ON CURRENT.device = BASELINE.device
  AND CURRENT.metric = BASELINE.metric
  AND BASELINE.timestamp = NOW() - INTERVAL '7 days'
WHERE pct_change > 0.25;  -- >25% change is anomalous
```

### Strategy 2: Time-Series Trending

```sql
-- Detect worsening trend (3-point moving average)
SELECT device, 
       LAG(metric, 2) OVER (PARTITION BY device ORDER BY timestamp) as m_minus_2,
       LAG(metric, 1) OVER (PARTITION BY device ORDER BY timestamp) as m_minus_1,
       metric as m_current
FROM metric_history
WHERE m_minus_2 < m_minus_1 AND m_minus_1 < m_current
  -- Consistently worsening over 3 measurements
```

### Strategy 3: Threshold Crossing

```sql
-- Alert on condition transitions
SELECT device, metric, threshold,
       LAG(value < threshold) OVER (PARTITION BY device ORDER BY timestamp) as was_ok,
       value < threshold as is_now_bad
FROM metric_threshold_log
WHERE was_ok = TRUE AND is_now_bad = TRUE;
       -- Crossed from OK to BAD
```

---

## Customizing Health Thresholds

Override default thresholds in `.olav/config/health_thresholds.yaml`:

```yaml
layer_l1:
  critical:
    - device_down: true
  warning:
    - uptime_days_min: 1
    - version_lag_major: 2

layer_l2:
  critical:
    - interface_critical_down: true
    - crc_errors_per_hour: 200
    - flap_rate_per_hour: 20
  warning:
    - crc_errors_per_hour: 50
    - flap_rate_per_hour: 5
    - neighbor_change_pct: 20

layer_l3:
  critical:
    - routing_neighbor_down: true
    - route_loss_pct: 10
  warning:
    - routing_flap_per_hour: 5
    - route_loss_pct: 5

layer_l4:
  critical:
    - cpu_percent: 95
    - memory_percent: 95
  warning:
    - cpu_percent: 80
    - memory_percent: 85
```

---

## Example Reports

### Example 1: Healthy Network

```
Network Score: 98/100 ✅ HEALTHY

All devices up, all interfaces active, protocols stable, performance optimal.

Recommendations: None. Continue routine monitoring.
```

### Example 2: Network with Warnings

```
Network Score: 75/100 ⚠️ WARNING

Critical Issues: 1 (interface down on R1)
Warning Issues: 3 (high CPU on core, neighbor count decreased on R2)

Recommendations:
- IMMEDIATE: Investigate R1 Gi0/0/1 down (potentially affecting 12 downstream devices)
- SHORT-TERM: Reduce CPU load on core switch (currently 82%)
- SHORT-TERM: Investigate BGP neighbor loss on R2 (lost 2 neighbors in 4 hours)
```

### Example 3: Critical Network State

```
Network Score: 32/100 🔴 CRITICAL

Critical Issues: 
- Core switch down (3 hours)
- Multiple device isolation detected
- BGP convergence failing

ACTION REQUIRED: 
1. Page on-call (critical outage)
2. Check core switch power/connectivity
3. Initiate incidents on dependent services
```

---

## Troubleshooting Low Health Scores

### Score Dropped Suddenly

1. Check what changed: `compare_device_configs(['device1', 'device2'])`
2. Review device logs for errors
3. Check for maintenance windows or deployments
4. Check for external network issues (ISP outages)

### Chronic Warning State

1. Analyze trend over 7 days: Which metrics are consistently degrading?
2. Check for resource exhaustion (CPU, memory scaling with network size)
3. Review threshold configuration — are thresholds realistic for this network?
4. Consider design changes (scaling, load distribution)

### Intermittent Issues

1. Correlate with time of day (business hours congestion?)
2. Correlate with user activity or backup windows
3. Check for seasonal patterns (Mondays, month-end, etc.)
4. Adjust thresholds if pattern is expected and acceptable

---

**Version**: Advanced inspection reference guide for OLAV v0.9.8
