# Query Agent E2E 能力摸底计划 (Phase 4.1)

**日期**: 2026-02-08  
**目标**: 使用自然语言驱动的E2E测试对Query Agent的理解和执行能力进行全面摸底  
**重点**: 用户说自然语言(中文) → Query Agent理解 → 执行查询 → 生成CSV/MD文件 → 验证结果  

---

## 📋 摸底计划概述

### 核心测试流程
```
用户自然语言需求（中文）
  ↓
Query Agent 理解和解析
  ↓
生成执行计划（可能包括SQL）
  ↓
执行数据库查询
  ↓  
生成 CSV/MD 文件输出
  ↓
验证：
  - 文件是否生成
  - 数据是否准确
  - 格式是否符合预期
```

### 目标
- ✅ 验证Query Agent能否正确理解用户的自然语言需求
- ✅ 验证能否执行正确的数据查询
- ✅ 验证能否正确生成CSV/MD格式的输出文件
- ✅ 摸清当前支持的最复杂自然语言查询类型
- ✅ 识别理解缺陷、执行问题和输出格式问题
- ✅ 为Phase 5优化提供baseline

### 测试范围
- **基础查询**: 简单的列表查询（如"列出所有设备"、"有多少个接口"）
- **中级查询**: 带条件和聚合的查询（如"过去10天流量最高的接口"、"启用但无流量的接口"）
- **高级查询**: 复杂的多维度分析（如"设备类型和协议的流量分布"、"接口的周环比分析"）
- **网络运维场景**: 5个真实的运维问题查询
- **输出格式**: CSV文件、markdown表格、HTML报告

### 测试方法
- **方法**: 生产级E2E测试（零mock）
- **规模**: 100+ 测试用例
- **覆盖**: 3个难度等级（Basic/Intermediate/Advanced）
- **验证维度**: 
  - 理解准确性（Query Agent能否正确理解需求）
  - 执行正确性（查询结果是否准确）
  - 输出完整性（文件是否正确生成）
  - 性能指标（查询时间、内存使用）

---

## 🏗️ 测试架构

### 测试层级

**新的测试方法：自然语言驱动 → 文件输出**

```
┌────────────────────────────────────────────────────┐
│ Phase 4.1 E2E Tests: NL → Query Execution → File  │
├────────────────────────────────────────────────────┤
│ Level 1: Basic NL Queries (20 tests)               │
│ ├─ "列出所有设备"                                  │
│ ├─ "有多少个接口"                                  │
│ ├─ "显示启用的接口"                                │
│ └─ 验证点: CSV生成正确，列名正确，无空行          │
│                                                    │
│ Level 2: Intermediate NL (40 tests)                │
│ ├─ "过去10天流量最高的接口是什么"                │
│ ├─ "哪些接口启用但没有流量"                       │
│ ├─ "每个设备有多少个接口，按数量排序"             │
│ └─ 验证点: 数据准确性，聚合正确，时间过滤有效    │
│                                                    │
│ Level 3: Advanced NL + 5 Real Scenarios (40 tests) │
│ ├─ "分析一下，过去10天哪些接口流量最多"           │
│ ├─ "找出启用但无流量的接口"                       │
│ ├─ "邻接关系中有没有不对称的情况"                 │
│ ├─ "接口流量的周环比变化趋势"                     │
│ └─ "各类型设备的协议使用分布"                     │
│                                                    │
│ Test Execution Flow:                               │
│ NL Input → Agent Understanding → Query Gen         │
│        → DB Execution → CSV/MD Output → Verify    │
└────────────────────────────────────────────────────┘
```

### 关键验证点

每个测试的验证维度：

| 维度 | Level 1 | Level 2 | Level 3 |
|------|---------|---------|---------|
| **理解准确性** | 简单需求 | 复杂条件 | 多维分析 |
| **执行正确性** | 单表 | JOIN | 复杂聚合 |
| **输出格式** | CSV | CSV/MD | HTML报告 |
| **性能** | <100ms | <500ms | <1500ms |
| **数据完整性** | 所有行 | 正确过滤 | 准确聚合 |
│                                             │
│ Level 3: Advanced Queries (40 tests)        │
│ ├─ 网络运维复杂场景 (过去10天流量最多接口)   │
│ ├─ 设备关联性分析 (设备→接口→邻接关系)       │
│ ├─ 异常检测 (开启但无流量的接口)            │
│ ├─ 多维度分析 (设备类型×协议×状态)          │
│ └─ 性能查询 (O(n²)的JOIN优化)               │
│                                             │
│ Integration: Real Orchestrator + Database  │
└─────────────────────────────────────────────┘
```

### 测试数据集

| 表 | 行数 | 用途 |
|---|------|------|
| devices | 50-200 | 设备基础信息 |
| interfaces | 500-2000 | 接口清单 |
| interface_stats | 5000-50000 | 时间序列流量数据 |
| bgp_routes | 500-5000 | BGP路由信息 |
| link_relationships | 100-500 | 接口邻接关系 |
| device_configs | 100-500 | 设备配置历史 |

---

## 📝 测试用例规格

### Level 1: 基础查询 (20 tests)

#### 1.1 简单SELECT查询

```python
@pytest.mark.e2e
@pytest.mark.query_level_1
class TestBasicSelectQueries:
    """基础SELECT查询验证"""
    
    async def test_select_all_devices(self):
        """
        用例: SELECT * FROM devices
        期望: 返回所有设备，含ID、name、type、mgmt_ip等字段
        验证: 
          - 字段完整性
          - 行数符合预期
          - 数据类型正确
        """
        query = "SELECT * FROM devices"
        result = await orchestrate_query(query)
        
        assert result is not None
        assert len(result) >= 10  # 假设至少10个设备
        assert all("device_id" in row for row in result)
        assert all("name" in row for row in result)
    
    async def test_select_specific_columns(self):
        """
        用例: SELECT name, mgmt_ip, device_type FROM devices
        期望: 仅返回指定列
        """
        query = "SELECT name, mgmt_ip, device_type FROM devices"
        result = await orchestrate_query(query)
        
        assert result is not None
        assert set(result[0].keys()) == {"name", "mgmt_ip", "device_type"}
    
    async def test_select_with_where_numeric(self):
        """
        用例: SELECT * FROM devices WHERE device_id > 5
        期望: 过滤条件正确生效
        """
        query = "SELECT * FROM devices WHERE device_id > 5"
        result = await orchestrate_query(query)
        
        assert all(row["device_id"] > 5 for row in result)
    
    async def test_select_with_where_text(self):
        """
        用例: SELECT * FROM devices WHERE device_type = 'Router'
        期望: 文本过滤正确
        """
        query = "SELECT * FROM devices WHERE device_type = 'Router'"
        result = await orchestrate_query(query)
        
        assert all(row["device_type"] == "Router" for row in result)
    
    async def test_select_with_where_like(self):
        """
        用例: SELECT * FROM devices WHERE name LIKE 'R%'
        期望: LIKE模式匹配
        """
        query = "SELECT * FROM devices WHERE name LIKE 'R%'"
        result = await orchestrate_query(query)
        
        assert all(row["name"].startswith("R") for row in result if row["name"])
    
    async def test_select_with_in_clause(self):
        """
        用例: SELECT * FROM devices WHERE device_id IN (1, 2, 3)
        期望: IN子句过滤
        """
        query = "SELECT * FROM devices WHERE device_id IN (1, 2, 3)"
        result = await orchestrate_query(query)
        
        assert all(row["device_id"] in [1, 2, 3] for row in result)
    
    async def test_select_with_order_by(self):
        """
        用例: SELECT * FROM devices ORDER BY name ASC
        期望: 排序正确
        """
        query = "SELECT * FROM devices ORDER BY name ASC"
        result = await orchestrate_query(query)
        
        names = [row["name"] for row in result]
        assert names == sorted(names)
    
    async def test_select_with_limit(self):
        """
        用例: SELECT * FROM devices LIMIT 5
        期望: 返回最多5行
        """
        query = "SELECT * FROM devices LIMIT 5"
        result = await orchestrate_query(query)
        
        assert len(result) <= 5
    
    async def test_select_with_offset(self):
        """
        用例: SELECT * FROM devices LIMIT 5 OFFSET 10
        期望: 跳过前10行，返回后续5行
        """
        query = "SELECT * FROM devices LIMIT 5 OFFSET 10"
        result = await orchestrate_query(query)
        
        assert len(result) <= 5
    
    # ... 更多基础查询测试 (共20个)
```

#### 1.2 聚合函数

```python
    async def test_count_all_devices(self):
        """
        用例: SELECT COUNT(*) as total FROM devices
        期望: 返回设备总数
        """
        query = "SELECT COUNT(*) as total FROM devices"
        result = await orchestrate_query(query)
        
        assert result[0]["total"] > 0
    
    async def test_group_by_device_type(self):
        """
        用例: SELECT device_type, COUNT(*) as count FROM devices GROUP BY device_type
        期望: 按设备类型分组统计
        """
        query = "SELECT device_type, COUNT(*) as count FROM devices GROUP BY device_type"
        result = await orchestrate_query(query)
        
        assert len(result) > 0
        assert all("device_type" in row and "count" in row for row in result)
    
    async def test_having_clause(self):
        """
        用例: SELECT device_type, COUNT(*) as count FROM devices 
              GROUP BY device_type HAVING COUNT(*) > 5
        期望: HAVING过滤聚合结果
        """
        query = """SELECT device_type, COUNT(*) as count FROM devices 
                   GROUP BY device_type HAVING COUNT(*) > 5"""
        result = await orchestrate_query(query)
        
        assert all(row["count"] > 5 for row in result)
    
    # ... 更多聚合函数测试
```

---

### Level 2: 中级查询 (40 tests)

#### 2.1 JOIN查询

```python
@pytest.mark.e2e
@pytest.mark.query_level_2
class TestIntermediateJoinQueries:
    """JOIN查询验证"""
    
    async def test_inner_join_devices_interfaces(self):
        """
        用例: SELECT d.name, i.interface_name, i.status
              FROM devices d
              INNER JOIN interfaces i ON d.device_id = i.device_id
        期望: 返回设备和接口的配对关系
        """
        query = """
            SELECT d.name as device_name, i.interface_name, i.status
            FROM devices d
            INNER JOIN interfaces i ON d.device_id = i.device_id
            LIMIT 20
        """
        result = await orchestrate_query(query)
        
        assert len(result) > 0
        assert all("device_name" in row for row in result)
        assert all("interface_name" in row for row in result)
    
    async def test_left_join_devices_stats(self):
        """
        用例: SELECT d.name, COUNT(s.stat_id) as stat_count
              FROM devices d
              LEFT JOIN interface_stats s ON d.device_id = s.device_id
              GROUP BY d.device_id, d.name
        期望: 返回所有设备及其统计数据（可能为0）
        """
        query = """
            SELECT d.name, COUNT(s.stat_id) as stat_count
            FROM devices d
            LEFT JOIN interface_stats s ON d.device_id = s.device_id
            GROUP BY d.device_id, d.name
        """
        result = await orchestrate_query(query)
        
        assert len(result) > 0
        assert all("stat_count" in row for row in result)
    
    async def test_three_table_join(self):
        """
        用例: SELECT d.name, i.interface_name, s.bytes_in, s.timestamp
              FROM devices d
              INNER JOIN interfaces i ON d.device_id = i.device_id
              INNER JOIN interface_stats s ON i.interface_id = s.interface_id
              WHERE s.timestamp >= DATE '2026-01-29'
        期望: 三表JOIN查询
        """
        query = """
            SELECT d.name, i.interface_name, s.bytes_in, s.timestamp
            FROM devices d
            INNER JOIN interfaces i ON d.device_id = i.device_id
            INNER JOIN interface_stats s ON i.interface_id = s.interface_id
            WHERE s.timestamp >= DATE '2026-01-29'
            LIMIT 50
        """
        result = await orchestrate_query(query)
        
        assert len(result) > 0
        assert all("bytes_in" in row for row in result)
```

#### 2.2 时间序列查询

```python
    async def test_last_10_days_traffic(self):
        """
        用例: 过去10天接口流量统计
        """ 
        query = """
            SELECT 
                d.name as device_name,
                i.interface_name,
                DATE(s.timestamp) as date,
                SUM(s.bytes_in) as total_bytes_in,
                SUM(s.bytes_out) as total_bytes_out,
                AVG(s.bytes_in + s.bytes_out) as avg_traffic
            FROM devices d
            INNER JOIN interfaces i ON d.device_id = i.device_id
            INNER JOIN interface_stats s ON i.interface_id = s.interface_id
            WHERE s.timestamp >= CURRENT_DATE - INTERVAL '10 days'
            GROUP BY d.device_id, d.name, i.interface_id, i.interface_name, DATE(s.timestamp)
            ORDER BY total_bytes_in DESC
            LIMIT 50
        """
        result = await orchestrate_query(query)
        
        assert len(result) > 0
        assert all("device_name" in row for row in result)
        assert all("total_bytes_in" in row for row in result)
    
    async def test_interface_utilization_percent(self):
        """
        用例: 计算接口利用率（过去7天平均）
        """
        query = """
            SELECT 
                d.name as device_name,
                i.interface_name,
                i.speed_bps,
                AVG(s.bytes_in + s.bytes_out) * 8 / i.speed_bps * 100 as avg_utilization_percent
            FROM devices d
            INNER JOIN interfaces i ON d.device_id = i.device_id
            INNER JOIN interface_stats s ON i.interface_id = s.interface_id
            WHERE s.timestamp >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY d.device_id, d.name, i.interface_id, i.interface_name, i.speed_bps
            HAVING AVG(s.bytes_in + s.bytes_out) * 8 / i.speed_bps * 100 > 50
            ORDER BY avg_utilization_percent DESC
        """
        result = await orchestrate_query(query)
        
        assert all("avg_utilization_percent" in row for row in result)
        print(f"✅ Found {len(result)} interfaces with >50% utilization")
```

---

### Level 3: 高级查询 (40 tests) - 真实运维场景

#### 3.1 **场景1: 过去10天流量最多的接口**

```python
@pytest.mark.e2e
@pytest.mark.query_level_3
@pytest.mark.network_ops
class TestNetworkOpsAdvancedQueries:
    """真实网络运维场景的复杂查询"""
    
    async def test_top_10_busiest_interfaces_last_10_days(self):
        """
        📊 运维需求: 让我了解过去10天哪些接口流量最多
        
        Background:
        - 找出带宽压力最大的接口
        - 辅助容量规划决策
        - 识别热点链路
        
        Query Complexity:
        - 多表JOIN (device, interface, interface_stats)
        - 时间过滤 (过去10天)
        - 聚合函数 (SUM, AVG)
        - 排序和TopN (LIMIT 10)
        """
        query = """
            SELECT 
                d.device_id,
                d.name as device_name,
                d.location,
                i.interface_id,
                i.interface_name,
                i.speed_gbps,
                i.status,
                SUM(s.bytes_in + s.bytes_out) as total_bytes,
                SUM(s.bytes_in) as total_bytes_in,
                SUM(s.bytes_out) as total_bytes_out,
                AVG(s.bytes_in + s.bytes_out) as avg_bytes_per_sample,
                COUNT(DISTINCT DATE(s.timestamp)) as active_days,
                MAX(s.timestamp) as last_sample_time,
                ROUND(SUM(s.bytes_in + s.bytes_out) * 8.0 / (10 * 24 * 3600 * 1000000000), 2) as avg_gbps
            FROM devices d
            INNER JOIN interfaces i ON d.device_id = i.device_id
            INNER JOIN interface_stats s ON i.interface_id = s.interface_id
            WHERE 
                s.timestamp >= CURRENT_TIMESTAMP - INTERVAL '10 days'
                AND i.status = 'up'
            GROUP BY 
                d.device_id, d.name, d.location,
                i.interface_id, i.interface_name, i.speed_gbps, i.status
            ORDER BY total_bytes DESC
            LIMIT 10
        """
        
        result = await orchestrate_query(query)
        
        # 验证结果
        assert len(result) > 0, "应该找到活跃接口"
        assert len(result) <= 10, "最多返回10个"
        
        for row in result:
            assert "device_name" in row
            assert "interface_name" in row
            assert "total_bytes" in row
            assert "avg_gbps" in row
            assert row["total_bytes"] > 0, "流量统计应该>0"
            assert row["active_days"] > 0, "应该有活跃天数"
        
        # 验证排序
        byte_counts = [row["total_bytes"] for row in result]
        assert byte_counts == sorted(byte_counts, reverse=True), "应该按流量降序"
        
        # 打印输出
        print(f"\n📊 Top 10 Busiest Interfaces (Last 10 Days):")
        print(f"{'Device':<12} {'Interface':<10} {'Total GB':<12} {'Avg Gbps':<10}")
        print("-" * 44)
        for row in result:
            total_gb = row["total_bytes"] / (1024**3)
            print(f"{row['device_name']:<12} {row['interface_name']:<10} {total_gb:<12.2f} {row['avg_gbps']:<10}")
        
        return result
```

#### 3.2 **场景2: 开启但无流量的接口（异常检测）**

```python
    async def test_enabled_but_idle_interfaces(self):
        """
        🚨 运维需求: 找出过去10天开启但实际没有流量的接口
        
        Background:
        - 识别未被使用的链路
        - 检查是否有配置错误
        - 清理不必要的接口配置
        - 优化成本
        
        Query Complexity:
        - 子查询: 过去10天有数据的接口
        - NOT IN: 反向过滤（开启但不在活跃列表）
        - CASE表达式: 条件判断
        - 多表LEFT JOIN: 获取统计数据
        """
        query = """
            -- 第一步: 找出过去10天有流量的接口
            WITH active_interfaces AS (
                SELECT DISTINCT i.interface_id
                FROM interfaces i
                INNER JOIN interface_stats s ON i.interface_id = s.interface_id
                WHERE s.timestamp >= CURRENT_TIMESTAMP - INTERVAL '10 days'
                AND (s.bytes_in > 0 OR s.bytes_out > 0)
            ),
            
            -- 第二步: 找出开启但没有流量的接口
            enabled_without_traffic AS (
                SELECT 
                    d.device_id,
                    d.name as device_name,
                    i.interface_id,
                    i.interface_name,
                    i.speed_gbps,
                    i.enabled,
                    i.mtu,
                    i.created_at,
                    DATEDIFF(DAY, i.created_at, CURRENT_DATE) as days_since_created,
                    NULL as last_traffic_time,
                    'No Traffic' as status_note
                FROM devices d
                INNER JOIN interfaces i ON d.device_id = i.device_id
                LEFT JOIN interface_stats s ON i.interface_id = s.interface_id
                    AND s.timestamp >= CURRENT_TIMESTAMP - INTERVAL '10 days'
                WHERE 
                    i.enabled = true
                    AND i.interface_id NOT IN (SELECT interface_id FROM active_interfaces)
                    AND DATEDIFF(DAY, i.created_at, CURRENT_DATE) > 1  -- 排除新建接口
            )
            
            SELECT 
                device_id, device_name, interface_id, interface_name, 
                speed_gbps, enabled, mtu, created_at, days_since_created, 
                last_traffic_time, status_note
            FROM enabled_without_traffic
            ORDER BY days_since_created DESC
            LIMIT 50
        """
        
        result = await orchestrate_query(query)
        
        # 验证结果
        assert result is not None, "应该返回查询结果"
        
        # 检查所有开启的接口都没有流量
        for row in result:
            assert row["enabled"] == True or row["enabled"] == 1
            assert row["status_note"] == "No Traffic"
        
        print(f"\n🚨 Enabled But Idle Interfaces (Past 10 Days):")
        print(f"Found {len(result)} interfaces with no traffic")
        print(f"{'Device':<12} {'Interface':<10} {'Days':<6} {'Speed':<10} {'Status':<15}")
        print("-" * 53)
        for row in result[:20]:
            print(f"{row['device_name']:<12} {row['interface_name']:<10} "
                  f"{row['days_since_created']:<6} {row['speed_gbps']:<10.1f} "
                  f"{row['status_note']:<15}")
        
        return result
```

#### 3.3 **场景3: 设备接口关联性分析**

```python
    async def test_device_interface_relationship_analysis(self):
        """
        🔗 运维需求: 了解设备的接口关联关系（接口→邻接关系）
        
        Background:
        - 验证接口邻接关系配置
        - 识别未配置邻接的接口
        - 检查对称性（A→B应该有B→A）
        - 拓扑故障分析
        
        Query Complexity:
        - 自连接 (interface_id vs. remote_interface_id)
        - 全外连接 (FULL OUTER JOIN)
        - 条件判断 (CASE WHEN)
        - 聚合后再聚合
        """
        query = """
            WITH interface_details AS (
                SELECT 
                    i.interface_id,
                    d.device_id,
                    d.name as device_name,
                    i.interface_name,
                    i.status as interface_status,
                    COALESCE(
                        (SELECT COUNT(*) FROM link_relationships 
                         WHERE local_interface_id = i.interface_id),
                        0
                    ) as neighbor_count
                FROM devices d
                INNER JOIN interfaces i ON d.device_id = i.device_id
            ),
            
            relationship_details AS (
                SELECT 
                    lr.local_interface_id,
                    local.device_name as local_device,
                    local.interface_name as local_interface,
                    local.interface_status as local_status,
                    lr.remote_interface_id,
                    remote.device_name as remote_device,
                    remote.interface_name as remote_interface,
                    remote.interface_status as remote_status,
                    CASE 
                        WHEN lr.relationship_type = 'ethernet' THEN 'Direct'
                        WHEN lr.relationship_type = 'bgp' THEN 'BGP'
                        WHEN lr.relationship_type = 'static' THEN 'Static'
                        ELSE lr.relationship_type 
                    END as link_type,
                    CASE
                        WHEN local.interface_status = 'up' AND remote.interface_status = 'up' THEN 'Healthy'
                        WHEN local.interface_status = 'down' OR remote.interface_status = 'down' THEN 'Degraded'
                        ELSE 'Unknown'
                    END as link_health
                FROM link_relationships lr
                INNER JOIN interface_details local ON lr.local_interface_id = local.interface_id
                INNER JOIN interface_details remote ON lr.remote_interface_id = remote.interface_id
            )
            
            SELECT 
                local_device, local_interface, local_status,
                remote_device, remote_interface, remote_status,
                link_type, link_health
            FROM relationship_details
            ORDER BY local_device, local_interface
            LIMIT 100
        """
        
        result = await orchestrate_query(query)
        
        assert len(result) > 0, "应该找到接口关系"
        
        # 统计分析
        healthy_links = sum(1 for row in result if row.get("link_health") == "Healthy")
        degraded_links = sum(1 for row in result if row.get("link_health") == "Degraded")
        
        print(f"\n🔗 Interface Relationships Analysis:")
        print(f"Total Links: {len(result)}")
        print(f"Healthy: {healthy_links} | Degraded: {degraded_links}")
        print(f"\n{'Local Device':<12} {'→':<2} {'Remote Device':<12} {'Status':<15}")
        print("-" * 41)
        for row in result[:30]:
            print(f"{row['local_device']:<12} {'↔':<2} {row['remote_device']:<12} "
                  f"{row['link_health']:<15}")
        
        return result
```

#### 3.4 **场景4: 设备协议分布与流量分析**

```python
    async def test_protocol_distribution_by_device_type(self):
        """
        📈 运维需求: 分析不同设备类型的协议分布和流量特征
        
        Background:
        - 了解设备协议使用情况
        - 识别异常流量特征
        - 支持网络规划
        
        Query Complexity:
        - 多表JOIN (4表)
        - GROUP BY多个字段
        - 子查询排名
        - WINDOW函数 (可选)
        """
        query = """
            WITH device_stats AS (
                SELECT 
                    d.device_id,
                    d.name as device_name,
                    d.device_type,
                    i.interface_id,
                    i.interface_name,
                    s.protocol,
                    SUM(s.bytes_in + s.bytes_out) as total_bytes,
                    COUNT(DISTINCT DATE(s.timestamp)) as active_days,
                    AVG(s.bytes_in + s.bytes_out) as avg_bytes
                FROM devices d
                INNER JOIN interfaces i ON d.device_id = i.device_id
                INNER JOIN interface_stats s ON i.interface_id = s.interface_id
                WHERE s.timestamp >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                GROUP BY d.device_id, d.name, d.device_type, i.interface_id, 
                         i.interface_name, s.protocol
            )
            
            SELECT 
                device_type,
                protocol,
                COUNT(DISTINCT device_id) as device_count,
                COUNT(DISTINCT interface_id) as interface_count,
                SUM(total_bytes) as total_bytes,
                ROUND(SUM(total_bytes) / SUM(SUM(total_bytes)) OVER (PARTITION BY device_type) * 100, 2) as percent_of_device_type,
                AVG(active_days) as avg_active_days,
                AVG(avg_bytes) as avg_bytes_per_sample
            FROM device_stats
            GROUP BY device_type, protocol
            ORDER BY device_type, total_bytes DESC
        """
        
        result = await orchestrate_query(query)
        
        assert len(result) > 0, "应该找到协议分布"
        
        print(f"\n📈 Protocol Distribution by Device Type:")
        print(f"{'Device Type':<12} {'Protocol':<10} {'Devices':<8} {'Interfaces':<12} {'Traffic %':<10}")
        print("-" * 52)
        for row in result:
            print(f"{row['device_type']:<12} {row['protocol']:<10} {row['device_count']:<8} "
                  f"{row['interface_count']:<12} {row['percent_of_device_type']:<10}%")
        
        return result
```

#### 3.5 **场景5: 异常检测 - 流量突变**

```python
    async def test_traffic_anomaly_detection(self):
        """
        🔴 运维需求: 检测过去24小时是否有异常流量突变
        
        Background:
        - 及时发现网络故障
        - 检测DDoS或异常流量
        - 支持告警系统
        
        Query Complexity:
        - 窗口函数 (LAG, ROW_NUMBER)
        - 环比计算
        - 多重过滤条件
        """
        query = """
            WITH hourly_stats AS (
                SELECT 
                    d.name as device_name,
                    i.interface_name,
                    DATE_TRUNC('hour', s.timestamp) as hour,
                    SUM(s.bytes_in + s.bytes_out) as hourly_bytes,
                    ROW_NUMBER() OVER (PARTITION BY i.interface_id ORDER BY DATE_TRUNC('hour', s.timestamp)) as hour_rank
                FROM devices d
                INNER JOIN interfaces i ON d.device_id = i.device_id
                INNER JOIN interface_stats s ON i.interface_id = s.interface_id
                WHERE s.timestamp >= CURRENT_TIMESTAMP - INTERVAL '2 days'
                GROUP BY d.name, i.interface_name, DATE_TRUNC('hour', s.timestamp)
            ),
            
            traffic_changes AS (
                SELECT 
                    device_name,
                    interface_name,
                    hour,
                    hourly_bytes,
                    LAG(hourly_bytes) OVER (PARTITION BY interface_name ORDER BY hour) as prev_hour_bytes,
                    CASE 
                        WHEN LAG(hourly_bytes) OVER (PARTITION BY interface_name ORDER BY hour) > 0
                        THEN ROUND((hourly_bytes - LAG(hourly_bytes) OVER (PARTITION BY interface_name ORDER BY hour))
                                   / LAG(hourly_bytes) OVER (PARTITION BY interface_name ORDER BY hour) * 100, 2)
                        ELSE 0
                    END as percent_change
                FROM hourly_stats
                WHERE hour_rank > 1  -- 排除第一个数据点
            )
            
            SELECT 
                device_name, interface_name, hour,
                hourly_bytes, prev_hour_bytes, percent_change,
                CASE
                    WHEN percent_change > 200 THEN 'Critical Increase'
                    WHEN percent_change > 100 THEN 'High Increase'
                    WHEN percent_change < -90 THEN 'Complete Drop'
                    WHEN percent_change < -50 THEN 'Significant Drop'
                    ELSE 'Normal'
                END as anomaly_type
            FROM traffic_changes
            WHERE ABS(percent_change) > 50
            ORDER BY hour DESC, ABS(percent_change) DESC
            LIMIT 50
        """
        
        result = await orchestrate_query(query)
        
        if len(result) > 0:
            print(f"\n🔴 Traffic Anomalies Detected:")
            print(f"Found {len(result)} suspicious traffic changes")
            print(f"{'Device':<12} {'Interface':<10} {'Change %':<10} {'Type':<18}")
            print("-" * 50)
            for row in result[:15]:
                print(f"{row['device_name']:<12} {row['interface_name']:<10} "
                      f"{row['percent_change']:<10}% {row['anomaly_type']:<18}")
        else:
            print(f"\n✅ No traffic anomalies detected")
        
        return result
```

---

## 📊 验证指标

### 性能指标

| 指标 | Target | 验收标准 |
|------|--------|---------|
| 基础查询 (SELECT *) | <100ms | ✅ <200ms |
| 2表JOIN | <500ms | ⚠️ <1s |
| 3表JOIN | <1s | ⚠️ <2s |
| 大结果集 (>10K行) | <2s | ⚠️ <5s |
| 复杂聚合 | <2s | ⚠️ <5s |

### 功能验证

| 功能 | 基础 | 中级 | 高级 |
|------|------|------|------|
| SELECT | ✅ | ✅ | ✅ |
| WHERE (AND/OR/LIKE) | ✅ | ✅ | ✅ |
| GROUP BY / HAVING | ✅ | ✅ | ✅ |
| ORDER BY / LIMIT | ✅ | ✅ | ✅ |
| INNER JOIN | ⚠️ | ✅ | ✅ |
| LEFT/RIGHT JOIN | ⚠️ | ✅ | ✅ |
| 3+ table JOIN | ❌ | ⚠️ | ✅ |
| Subquery | ❌ | ⚠️ | ✅ |
| CTE (WITH) | ❌ | ⚠️ | ✅ |
| Window Functions | ❌ | ❌ | ✅ |
| Case Expressions | ❌ | ✅ | ✅ |

---

## 🎯 执行计划

### Phase 4.1 Timeline

**Week 1 (Feb 8-14)**
- Day 1: 创建测试框架和Level 1基础测试 (✅ Done)
- Day 2: 实现Level 2中级测试和JOIN查询
- Day 3-4: 实现Level 3高级测试（网络运维场景）
- Day 5: 运行完整测试套件和收集结果

**Week 2 (Feb 15-21)**
- Day 1-2: 分析测试结果，识别瓶颈
- Day 3-4: 性能优化和缺陷修复
- Day 5: 生成最终摸底报告

### 测试执行

```bash
# 运行完整E2E测试套件
uv run pytest tests/e2e/ -v -s --tb=short \
    -m "query_agent" \
    --durations=10

# 只运行Level 1
uv run pytest tests/e2e/ -v -m "query_level_1"

# 只运行网络运维场景
uv run pytest tests/e2e/ -v -m "network_ops"

# 生成报告
uv run pytest tests/e2e/ --html=report.html
```

---

## 📋 期望输出

### 摸底报告 (docs/QUERY_AGENT_CAPABILITY_ASSESSMENT.md)

```
# Query Agent 能力摸底报告

## 执行摘要
- 测试用例总数: 100+
- 通过率: X%
- 最复杂支持的查询: [描述]

## 详细结果
### Level 1: 基础查询
- 通过: 20/20 ✅
- 平均耗时: XXms
- 发现问题: [列表]

### Level 2: 中级查询
- 通过: 35/40 ⚠️
- 平均耗时: XXms
- 失败用例: [描述]
- 性能瓶颈: [描述]

### Level 3: 高级查询
- 通过: 28/40 ⚠️
- 最复杂查询: [大查询描述]
- 性能瓶颈: [分析]
- 改进建议: [列表]

## 网络运维场景支持度
| 场景 | 支持 | 耗时 | 限制 |
|------|------|------|------|
| 过去N天流量TOP接口 | ✅ | XXms | 最多N个结果 |
| 开启但无流量接口 | ⚠️ | XXms | 需要子查询优化 |
| 接口关系分析 | ✅ | XXms | [限制] |
| ...| ...| ...| ...|

## 改进建议（优先级）
1. [优化索引] - 预期提升XX%
2. [优化查询] - 支持Window函数
3. [缓存策略] - 常用查询缓存
```

---

## 📂 文件结构

```
tests/e2e/
├── test_query_agent_level_1_basic.py      # 基础查询 (20 tests)
├── test_query_agent_level_2_intermediate.py # 中级查询 (40 tests)
├── test_query_agent_level_3_advanced.py    # 高级查询 (40 tests)
├── conftest.py                            # 共享fixtures
└── README.md                              # 测试说明

docs/
├── QUERY_AGENT_CAPABILITY_ASSESSMENT.md   # 最终摸底报告
└── QUERY_AGENT_OPTIMIZATION_ROADMAP.md    # 优化路线图
```

---

## ✅ 成功标准

- ✅ 100+ 真实场景E2E测试
- ✅ 覆盖3个难度等级
- ✅ 包含5个网络运维核心场景
- ✅ 完整的性能基线
- ✅ 清晰的改进建议
- ✅ 为Phase 5优化提供direction

---

**下一步**: 开始实现Level 1基础查询测试 (tests/e2e/test_query_agent_level_1_basic.py)
