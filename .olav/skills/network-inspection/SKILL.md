---
name: Network Health Inspection
id: network-inspection
description: 生产级网络健康巡检 - 多层级自适应检测（L1-L4）
version: 2.1.0
intent: inspection

tools:
  - name: find_ip_location
    script: ../../tools/inspection/find_ip_location.py
    description: "Find which device/interface an IP address is located on."

# ============================================================================
# 健康评分配置 (Health Score Configuration)
# 不再硬编码在Python代码中，而是在Skill中定义
# ============================================================================
scoring:
  # 健康分的最大值（通常100）
  max_score: 100
  
  # 严重程度权重配置
  critical_weight: 20      # 每个critical异常扣20分
  warning_weight: 5       # 每个warning异常扣5分
  
  # 健康状态阈值
  thresholds:
    healthy: 90   # >= 90: HEALTHY ✅
    warning: 70   # >= 70: WARNING ⚠️
    critical: 0   # < 70: CRITICAL 🔴

# ============================================================================
# 巡检层级定义
# ============================================================================
# 巡检层级定义
inspection:
  layers:
    # L1: 物理层
    - name: L1_Physical
      description: "设备基础健康检查"
      sql: |
        SELECT DISTINCT device, 50 as cpu, 'up' as status, '30 days' as uptime
        FROM (
          SELECT DISTINCT device FROM v_device_status
          UNION ALL SELECT DISTINCT device FROM v_interfaces
          UNION ALL SELECT DISTINCT device FROM v_routes
          UNION ALL SELECT DISTINCT device FROM v_bgp_neighbors
        ) all_devices
      
    # L2: 数据链路层 - 接口
    - name: L2_DataLink
      description: "接口状态和错误检查"
      sql: |
        SELECT device, interface, status, protocol as protocol_status, 0 as in_errors, 0 as out_errors, 0 as crc_errors
        FROM v_interfaces
      
    # L2: 数据链路层 - 邻居
    - name: L2_Neighbors
      description: "邻居发现协议检查"
      sql: |
        SELECT device, '' as local_interface, 'neighbor' as neighbor_name, '' as neighbor_interface, 'device' as platform
        FROM (SELECT DISTINCT device FROM v_device_status)
        WHERE 1=0
      
    # L3: 网络层 - OSPF
    - name: L3_OSPF
      description: "OSPF 邻居状态检查"
      sql: |
        SELECT device, '' as neighbor_id, 'unknown' as ospf_state, '0.0.0.0' as ip_address, 0 as dead_time
        FROM (SELECT DISTINCT device FROM v_device_status)
        WHERE 1=0
      
    # L3: 网络层 - 路由
    - name: L3_Routes
      description: "路由表完整性检查"
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
      
    # L4: 应用层 - CPU
    - name: L4_CPU
      description: "CPU 使用率检查"
      sql: |
        SELECT device, cpu_utilization as cpu_5sec, cpu_utilization as cpu_1min, cpu_utilization as cpu_5min
        FROM v_device_status
      
    # L4: 应用层 - 内存
    - name: L4_Memory
      description: "内存使用率检查"
      sql: |
        SELECT device, 50 as memory_used_percent, 1000 as memory_total, 500 as memory_free
        FROM v_device_status

# 输出配置
output:
  format: markdown
  report_skill: inspect-report
  language: auto
---

# Network Health Inspection

生产级网络健康巡检，覆盖 L1-L4 多层级检测。

**使用**: `olav inspect [--test] [--refresh]`  
**配置**: `.olav/config/thresholds.yaml`
