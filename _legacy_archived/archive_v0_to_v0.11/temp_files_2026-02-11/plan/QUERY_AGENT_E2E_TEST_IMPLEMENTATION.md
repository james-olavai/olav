# Query Agent E2E 测试实施细节

**文档**: Query Agent 能力摸底 - 实施指南  
**日期**: 2026-02-08  
**目标**: 提供完整的测试数据准备、测试脚本和网络运维场景详解  

---

## 📊 测试数据准备

### 必需的表结构和数据量

#### 表 1: devices（设备）
```sql
CREATE TABLE devices (
    device_id INT PRIMARY KEY,
    name VARCHAR(50) UNIQUE,  -- 设备名 (R1, R2, SW1, etc.)
    device_type VARCHAR(20),  -- Router, Switch, Firewall
    mgmt_ip VARCHAR(15),
    location VARCHAR(100),    -- 物理位置
    vendor VARCHAR(30),       -- Cisco, Juniper, Arista
    model VARCHAR(50),
    site_id INT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 推荐数据量: 50-200个设备
-- 设备类型分布:
--   - Routers: 30%
--   - Switches: 50%
--   - Firewalls: 20%
```

#### 表 2: interfaces（接口）
```sql
CREATE TABLE interfaces (
    interface_id INT PRIMARY KEY,
    device_id INT REFERENCES devices(device_id),
    interface_name VARCHAR(30),  -- Gi0/0/0, eth0, etc.
    speed_gbps FLOAT,            -- 接口速率 (1.0 = 1Gbps, 100.0 = 100Gbps)
    speed_bps BIGINT,            -- 速率（比特/秒）
    status VARCHAR(10),          -- up, down, admin-down
    enabled BOOLEAN,
    mtu INT,                     -- MTU大小
    protocol VARCHAR(50),        -- IPv4, IPv6, etc.
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 推荐数据量: 500-2000个接口
-- 接口状态分布:
--   - up: 85%
--   - down: 10%
--   - admin-down: 5%
-- 
-- 速率分布:
--   - 1Gbps: 40%
--   - 10Gbps: 50%
--   - 100Gbps: 10%
```

#### 表 3: interface_stats（接口统计 - 时间序列）
```sql
CREATE TABLE interface_stats (
    stat_id BIGINT PRIMARY KEY,
    interface_id INT REFERENCES interfaces(interface_id),
    device_id INT REFERENCES devices(device_id),
    timestamp TIMESTAMP,        -- 采样时间（5分钟间隔）
    bytes_in BIGINT,           -- 入向字节数
    bytes_out BIGINT,          -- 出向字节数
    packets_in BIGINT,
    packets_out BIGINT,
    errors_in INT,
    errors_out INT,
    dropped_in INT,
    dropped_out INT
);

-- 推荐数据量: 5000-50000条记录
-- 时间范围: 过去30天，5分钟采样间隔
--   = 30天 × 24小时 × 12个样本/小时 = 8640条/接口
--   如果1000个活跃接口 = 8,640,000条记录
--
-- 流量模式:
--   - 业务时段 (08:00-18:00): 正常高流量
--   - 非业务时段: 低流量 (~10%)
--   - 夜间 (22:00-06:00): 备份/同步流量
--   - 周末: 更低的流量
```

#### 表 4: link_relationships（接口邻接关系）
```sql
CREATE TABLE link_relationships (
    relationship_id INT PRIMARY KEY,
    local_interface_id INT REFERENCES interfaces(interface_id),
    remote_interface_id INT REFERENCES interfaces(interface_id),
    remote_device_id INT REFERENCES devices(device_id),
    relationship_type VARCHAR(20),  -- ethernet, bgp, static, mpls
    created_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);

-- 推荐数据量: 100-500条邻接关系
-- 邻接类型分布:
--   - ethernet (L2): 40%
--   - bgp (L3 peering): 50%
--   - static: 5%
--   - mpls: 5%
```

#### 表 5: bgp_routes（BGP路由）
```sql
CREATE TABLE bgp_routes (
    route_id INT PRIMARY KEY,
    device_id INT REFERENCES devices(device_id),
    prefix VARCHAR(20),           -- CIDR格式: 10.0.0.0/8
    next_hop VARCHAR(15),         -- 下一跳IP
    asn INT,                      -- AS号
    path_length INT,              -- AS路径长度
    weight INT,
    local_pref INT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    last_update TIMESTAMP
);

-- 推荐数据量: 500-5000条路由
```

#### 表 6: device_configs（设备配置历史）
```sql
CREATE TABLE device_configs (
    config_id INT PRIMARY KEY,
    device_id INT REFERENCES devices(device_id),
    config_text TEXT,            -- 配置文本
    config_hash VARCHAR(64),     -- MD5校验和
    snapshot_time TIMESTAMP,
    created_by VARCHAR(50),
    change_description VARCHAR(255)
);

-- 推荐数据量: 100-500条配置快照
```

### 数据生成脚本

```python
"""Generate test data for Query Agent assessment"""
import random
from datetime import datetime, timedelta

def generate_devices(count=100):
    """生成设备数据"""
    devices = []
    device_types = ["Router", "Switch", "Firewall"]
    vendors = ["Cisco", "Juniper", "Arista", "Huawei"]
    locations = ["Beijing DC", "Shanghai DC", "Shenzhen DC", "Regional Office"]
    
    for i in range(count):
        devices.append({
            "device_id": i + 1,
            "name": f"{'R' if random.random() < 0.3 else 'SW'}{i//10}{i%10}",
            "device_type": random.choice(device_types),
            "mgmt_ip": f"10.0.{i//256}.{i%256}",
            "location": random.choice(locations),
            "vendor": random.choice(vendors),
            "created_at": datetime.now() - timedelta(days=random.randint(30, 365))
        })
    return devices

def generate_interfaces(device_count=100, per_device=10):
    """生成接口数据"""
    interfaces = []
    interface_id = 1
    speeds = [1.0, 10.0, 100.0]  # Gbps
    speed_weights = [0.4, 0.5, 0.1]
    statuses = ["up"] * 85 + ["down"] * 10 + ["admin-down"] * 5
    
    for device_id in range(1, device_count + 1):
        for iface in range(per_device):
            interfaces.append({
                "interface_id": interface_id,
                "device_id": device_id,
                "interface_name": f"Gi{iface//10}/{iface%10}",
                "speed_gbps": random.choices(speeds, speed_weights)[0],
                "status": random.choice(statuses),
                "enabled": random.random() > 0.05,  # 95%开启
                "created_at": datetime.now() - timedelta(days=random.randint(1, 180))
            })
            interface_id += 1
    
    return interfaces

def generate_interface_stats(interface_count=1000, days=10, samples_per_day=288):
    """生成接口流量统计数据（5分钟采样）"""
    stats = []
    stat_id = 1
    
    for interface_id in range(1, interface_count + 1):
        for day_offset in range(days):
            for sample in range(samples_per_day):
                timestamp = datetime.now() - timedelta(
                    days=days - day_offset - 1,
                    minutes=sample * 5
                )
                
                # 根据时间生成流量模式
                hour = timestamp.hour
                if 8 <= hour <= 18:  # 业务时段
                    bytes_in = random.randint(1000000, 10000000)
                    bytes_out = random.randint(1000000, 10000000)
                elif 22 <= hour or hour <= 6:  # 夜间备份
                    bytes_in = random.randint(5000000, 50000000)
                    bytes_out = random.randint(5000000, 50000000)
                else:  # 低活动期
                    bytes_in = random.randint(100000, 1000000)
                    bytes_out = random.randint(100000, 1000000)
                
                stats.append({
                    "stat_id": stat_id,
                    "interface_id": interface_id,
                    "timestamp": timestamp,
                    "bytes_in": bytes_in,
                    "bytes_out": bytes_out,
                    "packets_in": random.randint(10000, 100000),
                    "packets_out": random.randint(10000, 100000)
                })
                stat_id += 1
    
    return stats
```

---

## 🎯 网络运维核心场景详解

### 场景1: 容量规划 - TOP 10 流量接口

**运维背景**:
网络工程师需要了解过去10天哪些接口流量最多，来决定是否需要升级链路。

**关键指标**:
- 总流量（字节）
- 平均流量（Gbps）
- 峰值流量
- 活跃天数
- 趋势（上升/下降）

**复杂度分析**:
- ✅ SELECT: 基础
- ✅ FROM: 3表JOIN
- ✅ WHERE: 时间范围过滤
- ✅ GROUP BY: 多维度分组
- ✅ ORDER BY + LIMIT: TopN
- ⚠️ 数学表达式: 将字节转换为Gbps

**预期结果样本**:
```
设备          接口              速率     总流量(GB)  平均Gbps  活跃天  状态
R1            Gi0/0/0          100Gbps   2500      25.5      10    up
R2            Gi0/0/1          100Gbps   2100      21.6      10    up
SW1           Gi0/48           10Gbps     850       8.7       10    up
R3            Gi0/0/2          10Gbps     720       7.4       10    up
```

**优化建议**:
- 为timestamp + interface_id创建复合索引
- 预先计算每日统计（物化视图）
- 缓存最近7/30天的TOP接口列表

---

### 场景2: 异常检测 - 开启但无流量接口

**运维背景**:
运维想找出哪些接口配置为开启（enabled=true），但在过去10天没有任何流量经过。这可能意味着：
- 配置错误
- 物理链路故障（对方没接线）
- 规划中的链路还未投产
- 需要清理的废弃接口

**关键指标**:
- 接口状态（enabled）
- 流量存在/不存在
- 接口创建时间（排除新接口）
- 对端设备（如果有邻接关系）

**复杂度分析**:
- ✅ WITH/CTE: 两层子查询
- ✅ NOT IN: 反向过滤
- ✅ LEFT JOIN: 可选关系
- ✅ DISTINCT: 去重
- ⚠️ 子查询嵌套: 需要优化

**关键查询技巧**:
```sql
-- 错误做法: 低效、易超时
SELECT * FROM interfaces 
WHERE enabled = true 
AND interface_id NOT IN (
  WITH 10 days of data involved
)

-- 正确做法: 使用LEFT JOIN/NOT EXISTS
SELECT i.* FROM interfaces i
LEFT JOIN (
  SELECT DISTINCT interface_id 
  FROM interface_stats 
  WHERE timestamp >= DATE_SUB(CURRENT_DATE, INTERVAL 10 DAY)
) s ON i.interface_id = s.interface_id
WHERE i.enabled = true AND s.interface_id IS NULL
```

**预期结果样本**:
```
设备    接口       状态    创建时间         天数  对端设备  原因推测
R1     Gi0/0/2    up     2025-12-01      69    (null)   故障/未接线
SW1    Gi0/47     up     2025-11-15      85    (null)   废弃接口
R2     Gi0/0/3    up     2026-01-20      19    R3       新链路在测试
```

---

### 场景3: 接口关系验证 - 对称性检查

**运维背景**:
BGP或OSPF邻接时，需要确保邻接关系配置的对称性。如果A→B有邻接，B→A也应该有邻接。

**复杂度分析**:
- ✅ 自连接 (自引用)
- ✅ 全外连接 (FULL OUTER JOIN)
- ✅ 条件表达式 (CASE WHEN)
- ⚠️ 复杂逻辑（对称性验证）

**核心查询**:
```sql
-- 检测对称性问题
SELECT 
  COALESCE(a.local_iface, b.remote_iface) as iface_a,
  COALESCE(a.remote_iface, b.local_iface) as iface_b,
  CASE
    WHEN a.local_iface IS NOT NULL AND b.local_iface IS NOT NULL THEN 'Symmetric'
    WHEN a.local_iface IS NOT NULL AND b.local_iface IS NULL THEN 'A→B Missing Return'
    WHEN a.local_iface IS NULL AND b.local_iface IS NOT NULL THEN 'B→A Missing Return'
  END as status
FROM link_relationships a
FULL OUTER JOIN link_relationships b
  ON a.local_iface = b.remote_iface
  AND a.remote_iface = b.local_iface
WHERE a.local_iface IS NULL OR b.local_iface IS NULL
```

---

### 场景4: 流量趋势分析 - 周环比

**运维背景**:
了解本周流量与上周同期的对比，判断流量是否异常增长或下降。

**复杂度分析**:
- ✅ Window函数 (LAG, LEAD)
- ✅ 日期函数 (DATE_TRUNC, DATE_FORMAT)
- ✅ 百分比计算
- ✅ 多维度对比

**核心查询**:
```sql
WITH daily_traffic AS (
  SELECT 
    interface_id,
    CAST(timestamp AS DATE) as traffic_date,
    WEEK(timestamp) as week_num,
    DAYNAME(timestamp) as day_name,
    SUM(bytes_in + bytes_out) as daily_bytes
  FROM interface_stats
  WHERE timestamp >= DATE_SUB(CURRENT_DATE, INTERVAL 21 DAY)  -- 3周数据
  GROUP BY interface_id, CAST(timestamp AS DATE), WEEK(timestamp), DAYNAME(timestamp)
),

week_comparison AS (
  SELECT 
    interface_id,
    day_name,
    MAX(CASE WHEN week_num = WEEK(CURRENT_DATE) THEN daily_bytes END) as this_week,
    MAX(CASE WHEN week_num = WEEK(CURRENT_DATE) - 1 THEN daily_bytes END) as last_week,
    MAX(CASE WHEN week_num = WEEK(CURRENT_DATE) - 2 THEN daily_bytes END) as two_weeks_ago
  FROM daily_traffic
  GROUP BY interface_id, day_name
)

SELECT 
  interface_id,
  day_name,
  this_week,
  last_week,
  ROUND((this_week - last_week) / last_week * 100, 2) as week_on_week_percent,
  CASE
    WHEN (this_week - last_week) / last_week > 0.3 THEN 'Significant Increase'
    WHEN (this_week - last_week) / last_week > 0.1 THEN 'Moderate Increase'
    WHEN (this_week - last_week) / last_week < -0.3 THEN 'Significant Decrease'
    ELSE 'Normal'
  END as trend
FROM week_comparison
WHERE last_week > 0
ORDER BY ABS((this_week - last_week) / last_week) DESC
```

---

### 场景5: 多维度分析 - 设备类型×协议×流量

**运维背景**:
某些设备类型的特定协议可能有异常流量特征。例如，Firewall的BGP流量不应该很大。

**复杂度分析**:
- ✅ 多表JOIN (4+表)
- ✅ GROUP BY多个维度
- ✅ 百分比计算（窗口函数）
- ✅ HAVING过滤

**预期分析**:
```
设备类型   协议     接口数  设备数  总流量    占比    平均流量  异常性
Router    BGP       20     10     1500GB   45%     750MB    正常
Router    OSPF      15     8      1200GB   35%     800MB    正常  
Router    Data      25     10      600GB   20%     240MB    正常

Switch    BGP        2      2       50GB    8%      25GB     异常⚠️
Switch    Data     150     20     600GB    92%      4GB     正常
```

**异常检测逻辑**:
- BGP流量占比不应超过总流量的10%
- 数据中心内Switch的BGP流量应远小于核心Router
- Firewall的某些协议流量过高表示可能有安全问题

---

## 🔧 测试框架基础代码

### conftest.py - 共享fixtures

```python
"""E2E测试共享配置和fixtures"""
import pytest
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import random

@pytest.fixture(scope="session")
def db_connection():
    """获取数据库连接"""
    engine = create_engine("duckdb:///:memory:")
    # 或: engine = create_engine("duckdb:///test_network.db")
    
    with engine.connect() as conn:
        yield conn
    
    engine.dispose()

@pytest.fixture(scope="function")
def network_test_data(db_connection):
    """为每个测试加载网络数据"""
    
    # 生成测试数据
    devices = generate_devices(count=50)
    interfaces = generate_interfaces(device_count=50, per_device=15)
    stats = generate_interface_stats(interface_count=750, days=10)
    
    # 插入到数据库
    for device in devices:
        db_connection.execute(text("""
            INSERT INTO devices VALUES (:id, :name, :type, :mgmt_ip, :loc, :vendor)
        """), device)
    
    yield db_connection
    
    # Cleanup
    db_connection.execute("DELETE FROM interface_stats")
    db_connection.execute("DELETE FROM interfaces")
    db_connection.execute("DELETE FROM devices")
    db_connection.commit()

@pytest.fixture
def orchestrator_query():
    """获取orchestrator.orchestrate_query函数"""
    from olav.agents.orchestrator import orchestrate_query
    return orchestrate_query
```

### 通用验证函数

```python
"""通用的查询结果验证函数"""

def verify_result_structure(result, expected_columns):
    """验证结果具有正确的列结构"""
    assert result is not None
    assert len(result) > 0
    
    actual_columns = set(result[0].keys())
    expected_set = set(expected_columns)
    
    assert actual_columns == expected_set, \
        f"Missing columns: {expected_set - actual_columns}"

def verify_numeric_column(rows, column, min_val=None, max_val=None):
    """验证数值列的有效范围"""
    for row in rows:
        val = row[column]
        if min_val is not None:
            assert val >= min_val
        if max_val is not None:
            assert val <= max_val

def verify_sorted_by(rows, column, ascending=True):
    """验证结果按指定列排序"""
    values = [row[column] for row in rows]
    
    if ascending:
        assert values == sorted(values), f"Not sorted ascending by {column}"
    else:
        assert values == sorted(values, reverse=True), f"Not sorted descending by {column}"

def track_query_performance(query, result, threshold_ms=1000):
    """记录查询性能"""
    import time
    elapsed_ms = time.time() * 1000
    
    print(f"\n⏱️  Query Performance:")
    print(f"   Query: {query[:100]}...")
    print(f"   Time: {elapsed_ms:.2f}ms")
    print(f"   Rows: {len(result)}")
    
    if elapsed_ms > threshold_ms:
        print(f"   ⚠️  SLOW: Exceeded {threshold_ms}ms threshold")
```

---

## 📈 结果分析和报告

### 测试结果汇总格式

```python
"""在测试完成后生成摸底报告"""

class QueryAgentAssessmentReport:
    def __init__(self):
        self.results = {
            "level_1": {"passed": 0, "failed": 0, "avg_time_ms": 0},
            "level_2": {"passed": 0, "failed": 0, "avg_time_ms": 0},
            "level_3": {"passed": 0, "failed": 0, "avg_time_ms": 0},
            "scenarios": {}
        }
    
    def add_result(self, test_name, level, passed, duration_ms):
        """添加测试结果"""
        if passed:
            self.results[level]["passed"] += 1
        else:
            self.results[level]["failed"] += 1
        # 计算平均时间...
    
    def generate_markdown(self):
        """生成Markdown格式报告"""
        report = f"""
# Query Agent 能力摸底报告
生成时间: {datetime.now().isoformat()}

## 执行摘要
- 总测试数: {sum(r['passed'] + r['failed'] for r in self.results.values())}
- 通过率: {self._pass_rate()}%
- 平均查询时间: {self._avg_time()}ms

## 分级结果
| 等级 | 通过 | 失败 | 通过率 | 平均时间 |
|------|------|------|--------|---------|
| Level 1 | {self.results['level_1']['passed']} | {self.results['level_1']['failed']} | XX% | XXms |
| Level 2 | {self.results['level_2']['passed']} | {self.results['level_2']['failed']} | XX% | XXms |
| Level 3 | {self.results['level_3']['passed']} | {self.results['level_3']['failed']} | XX% | XXms |
"""
        return report
```

---

## ✅ 验收清单

- [ ] 测试数据已准备（至少50个设备，750个接口，10天数据）
- [ ] Level 1-3 测试框架已创建
- [ ] 所有网络运维场景测试已编写
- [ ] 性能基线已建立
- [ ] 缺陷已识别和分类
- [ ] 优化建议已列出
- [ ] 最终报告已生成

---

**Next Steps**:
1. 准备测试数据库和test fixtures
2. 实现Level 1基础查询测试 (预期: 1-2小时)
3. 实现Level 2中级查询测试 (预期: 2-3小时)  
4. 实现Level 3高级查询测试 (预期: 3-4小时)
5. 执行完整测试套件和分析 (预期: 1-2小时)

**总预期工期**: 1-2周 (每天2-3小时投入)
