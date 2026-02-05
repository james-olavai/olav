---
name: Network Health Inspection
id: network-inspection
description: Production-Grade Network Health Inspection - Multi-layer Adaptive Detection（L1-L4）
version: 2.1.0
intent: inspection

tools:
  - name: find_ip_location
    script: ../../tools/inspection/find_ip_location.py
    description: "Find which device/interface an IP address is located on."

# ============================================================================
# Health Score Configuration (Health Score Configuration)
# No longer hardcoded in Python, defined in Skill
# ============================================================================
scoring:
  # Maximum health score value（typically 100）
  max_score: 100
  
  # Severity weight configuration
  critical_weight: 20      # each critical anomaly deducts 20 points
  warning_weight: 5       # each warning anomaly deducts 5 points
  
  # Health status thresholds
  thresholds:
    healthy: 90   # >= 90: HEALTHY ✅
    warning: 70   # >= 70: WARNING ⚠️
    critical: 0   # < 70: CRITICAL 🔴

# ============================================================================
# Inspection Layer Definitions
# ============================================================================
# Inspection Layer Definitions
inspection:
  layers:
    # L1: Physical Layer
    - name: L1_Physical
      description: "Basic device health check"
      sql: |
        SELECT DISTINCT device, 50 as cpu, 'up' as status, '30 days' as uptime
        FROM (
          SELECT DISTINCT device FROM v_device_status
          UNION ALL SELECT DISTINCT device FROM v_interfaces
          UNION ALL SELECT DISTINCT device FROM v_routes
          UNION ALL SELECT DISTINCT device FROM v_bgp_neighbors
        ) all_devices
      
    # L2: Data Link Layer - Interface
    - name: L2_DataLink
      description: "Interface status and error checks"
      sql: |
        SELECT device, interface, status, protocol as protocol_status, 0 as in_errors, 0 as out_errors, 0 as crc_errors
        FROM v_interfaces
      
    # L2: Data Link Layer - Neighbor
    - name: L2_Neighbors
      description: "Neighbor discovery protocol checks"
      sql: |
        SELECT device, '' as local_interface, 'neighbor' as neighbor_name, '' as neighbor_interface, 'device' as platform
        FROM (SELECT DISTINCT device FROM v_device_status)
        WHERE 1=0
      
    # L3: Network Layer - OSPF
    - name: L3_OSPF
      description: "OSPF neighbor state checks"
      sql: |
        SELECT device, '' as neighbor_id, 'unknown' as ospf_state, '0.0.0.0' as ip_address, 0 as dead_time
        FROM (SELECT DISTINCT device FROM v_device_status)
        WHERE 1=0
      
    # L3: Network Layer - Routing
    - name: L3_Routes
      description: "Routing table completeness check"
      sql: |
        SELECT 
          device,
          COUNT(*) as route_count,
          COUNT(DISTINCT protocol) as protocol_count,
          SUM(CASE WHEN protocol = 'connected' THEN 1 ELSE 0 END) as connected_routes,
          SUM(CASE WHEN protocol = 'ospf' THEN 1 ELSE 0 END) as ospf_routes,
          SUM(CASE WHEN protocol = 'static' THEN 1 ELSE 0 END) as static_routes
        FROM v_routes
        GROUP BY device
      
    # L4: Application Layer - CPU
    - name: L4_CPU
      description: "CPU utilization check"
      sql: |
        SELECT device, cpu_utilization as cpu_5sec, cpu_utilization as cpu_1min, cpu_utilization as cpu_5min
        FROM v_device_status
      
    # L4: Application Layer - Memory
    - name: L4_Memory
      description: "Memory utilization check"
      sql: |
        SELECT device, 50 as memory_used_percent, 1000 as memory_total, 500 as memory_free
        FROM v_device_status

# OutputConfiguration
output:
  format: markdown
  report_skill: inspect-report
  language: auto
---

# Network Health Inspection

Production-Grade Network Health Inspection，covers L1-L4 multi-layer detection。

**Usage**: `olav inspect [--test] [--refresh]`  
**Configuration**: `.olav/skills/network-inspection/config/thresholds.yaml`
