---
name: Network Health Inspection
id: network-inspection
description: 生产级网络健康巡检 - 多层级自适应检测（L1-L4）
version: 2.1.0
intent: inspection

tools:
  - name: find_ip_location
    script: scripts/find_ip_location.py
    description: "Find which device/interface an IP address is located on."

# 巡检层级定义
inspection:
  layers:
    # L1: 物理层
    - name: L1_Physical
      description: "设备基础健康检查"
      sql: |
        SELECT device, version, uptime, hostname
        FROM v_device_status
      
    # L2: 数据链路层 - 接口
    - name: L2_DataLink
      description: "接口状态和错误检查"
      sql: |
        SELECT device, interface, status, protocol_status, in_errors, out_errors, crc_errors
        FROM v_interfaces
      
    # L2: 数据链路层 - 邻居
    - name: L2_Neighbors
      description: "邻居发现协议检查"
      sql: |
        SELECT device, local_interface, neighbor_name, neighbor_interface, platform
        FROM v_cdp_neighbors
      
    # L3: 网络层 - OSPF
    - name: L3_OSPF
      description: "OSPF 邻居状态检查"
      sql: |
        SELECT device, neighbor_id, state as ospf_state, ip_address, dead_time
        FROM v_ospf_neighbors
      
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
        SELECT device, cpu_5sec as cpu_utilization, cpu_1min as cpu_1min, cpu_5min as cpu_5min
        FROM v_cpu_utilization
      
    # L4: 应用层 - 内存
    - name: L4_Memory
      description: "内存使用率检查"
      sql: |
        SELECT device, memory_used_percent as memory_utilization, memory_total, memory_free
        FROM v_memory_utilization

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
