---
name: bgp_session_health_valid
version: '4.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_SESSIONS_STATUS
  type: sql
  severity: Critical
  section_prompt: Analyze BGP neighbor states from recent snapshots. Flag devices
    with any non-Established sessions (Idle, Connect, Active, etc.). Include neighbor_ip,
    uptime if available, and suggest checks (e.g., ping neighbor, check logs).
  query: SELECT device_name, neighbor_ip, neighbor_as, state, prefixes_received, created_at
    FROM main.bgp_neighbors WHERE (state != 'Established' OR state IS NULL) AND created_at
    >= NOW() - INTERVAL '24' HOURS ORDER BY device_name, created_at DESC
- name: BGP_TOTAL_DOWN_RATIO
  type: sql
  severity: Warning
  section_prompt: 'Compute down session ratio per device. Warn if >10% sessions unhealthy.
    Use: SELECT device_name, unhealthy_sessions, total_sessions, (unhealthy_sessions
    * 100.0 / total_sessions) AS down_pct FROM (SELECT device_name, COUNT(*) FILTER
    (WHERE state != ''Established'' OR state IS NULL) as unhealthy_sessions, COUNT(*)
    as total_sessions FROM main.bgp_neighbors WHERE created_at >= NOW() - INTERVAL
    ''24'' HOURS GROUP BY device_name) WHERE unhealthy_sessions > 0'
  query: WITH session_stats AS (SELECT device_name, COUNT(*) FILTER (WHERE state !=
    'Established' OR state IS NULL) as unhealthy_sessions, COUNT(*) as total_sessions
    FROM main.bgp_neighbors WHERE created_at >= NOW() - INTERVAL '24' HOURS GROUP
    BY device_name) SELECT device_name, unhealthy_sessions, total_sessions, (unhealthy_sessions
    * 100.0 / total_sessions) AS down_pct FROM session_stats WHERE unhealthy_sessions
    > 0 ORDER BY down_pct DESC
---

# BGP Session Health Check (Valid)\n\nComprehensive health check for BGP peering status using `main.bgp_neighbors`.\n\n## Purpose\n- Detect flapping or down BGP sessions\n- Quantify impact (down ratio per device)\n- Recent data only (24h window)\n\n## Jobs\n1. **BGP_SESSIONS_STATUS** (Critical): Lists individual down sessions\n2. **BGP_TOTAL_DOWN_RATIO** (Warning): Per-device down %\n\n## Remediation\n- Ping neighbor_ip\n- Check device logs for BGP events\n- Verify ACLs/firewalls\n- Review config changes (use ops agent)
