---
name: bgp_health_comprehensive
version: '4.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_DOWN_SESSIONS
  type: sql
  severity: Critical
  section_prompt: List all BGP neighbors not in 'Established' state or NULL. Identify
    flapping by checking multiple snapshots. Suggest checking interface status and
    underlying connectivity.
  query: SELECT device_name as device, neighbor_ip, neighbor_as, state, snapshot_id,
    created_at FROM v_bgp_neighbors_auto WHERE (state != 'Established' OR state IS
    NULL) AND created_at >= NOW() - INTERVAL :window ORDER BY device_name, created_at
    DESC
- name: BGP_TOTAL_PEERS
  type: sql
  severity: Info
  section_prompt: Summarize BGP peer counts per device. Flag anomalies like sudden
    drops or unexpected zeros compared to historical data.
  query: SELECT device_name as device, COUNT(*) as num_peers, COUNT(CASE WHEN state
    = 'Established' THEN 1 END) as established_peers FROM v_bgp_neighbors_auto WHERE
    created_at >= NOW() - INTERVAL :window GROUP BY device_name ORDER BY num_peers
    DESC
- name: NO_BGP_ACTIVITY
  type: sql
  severity: Warning
  section_prompt: Identify network devices (Cisco/Juniper) with no BGP neighbors detected
    recently. These may be routers missing BGP config or data collection issues.
  query: SELECT d.hostname as device, d.platform FROM netops.devices d WHERE d.platform
    IN ('cisco_ios', 'juniper_junos') AND NOT EXISTS (SELECT 1 FROM v_bgp_neighbors_auto
    b WHERE b.device_name = d.hostname AND b.created_at >= NOW() - INTERVAL :window)
---

# BGP Health Comprehensive Profile\n\nThis profile monitors BGP session health across the network:\n- **Critical**: Down or flapping BGP sessions\n- **Warning**: Routers with no BGP peers (potential config/missing data)\n- **Info**: Peer counts and established summary\n\nUses v_bgp_neighbors_auto view and recent snapshots (:window=24h default).\n\nExpected outcomes:\n- All production BGP sessions Established\n- Peer counts stable vs. topology
