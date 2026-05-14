---
name: bgp_session_health
version: '4.0'
persist_findings_to_db: false
max_findings_per_job: 50
jobs:
- name: BGP_NON_ESTABLISHED_SESSIONS
  type: sql
  severity: Warning
  section_prompt: Identify all BGP sessions that are not in 'Established' state. For
    each, note the device, neighbor IP, AS, and state. Highlight flapping or long-down
    sessions based on created_at or snapshot_id. Suggest root causes like config mismatch,
    ACL blocks, or peer issues.
  query: SELECT device_name, neighbor_ip, neighbor_as, state, snapshot_id, created_at
    FROM main.v_bgp_neighbors_auto WHERE state != 'Established' OR state IS NULL ORDER
    BY created_at DESC LIMIT 100
---

# BGP Session Health Check Profile\n\nThis profile monitors BGP neighbor session states across all devices.\n\n## Purpose\nDetect down or unstable BGP sessions that could impact routing.\n\n## Coverage\n- Queries latest BGP neighbor data from `v_bgp_neighbors_auto` view.\n- Flags non-Established sessions (Idle, Connect, Active, OpenSent, OpenConfirm).\n\n## Usage\nRun with `olav --agent audit-auditor bgp_session_health` for report.\n\n**Note:** Ignores nonexistent_table_xyz_abc as no such table exists; uses real BGP data from production schema.
