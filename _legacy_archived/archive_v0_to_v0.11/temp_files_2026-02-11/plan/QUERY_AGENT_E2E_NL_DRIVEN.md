# Query Agent E2E 能力摸底 - 自然语言驱动版 

**日期**: 2026-02-08  
**核心概念**: 用户用**自然语言**说出需求 → Query Agent理解并执行 → 生成**CSV/MD文件** → 验证结果  
**目标**: 摸清Query Agent在复杂自然语言查询上的能力、缺陷和性能瓶颈

---

## 🎯 测试方法论

### 真实的E2E测试流程

```
┌─────────────────────────────────────────────────────────┐
│ 用户输入: "过去10天流量最高的10个接口是什么?"          │
├─────────────────────────────────────────────────────────┤
│ Step 1: Query Agent 理解需求                           │
│         ✓ 检测时间范围: 过去10天                       │
│         ✓ 检测对象: 接口                               │
│         ✓ 排序维度: 流量（最高）                       │
│         ✓ 数量限制: 10个                               │
├─────────────────────────────────────────────────────────┤
│ Step 2: 生成执行计划                                    │
│         · 可能生成SQL: SELECT语句，JOIN，聚合等         │
│         · 可能调用多个子查询                           │
│         · 可能使用缓存或预计算                        │
├─────────────────────────────────────────────────────────┤
│ Step 3: 执行查询并获得结果                              │
│         · 从数据库检索数据                             │
│         · 进行必要的聚合和排序                        │
│         · 验证结果的准确性                            │
├─────────────────────────────────────────────────────────┤
│ Step 4: 生成输出文件                                    │
│         ✓ 格式: CSV (top_interfaces_10d.csv)           │
│         ✓ 列: 设备、接口、速率、总流量、平均速率      │
│         ✓ 存储位置: exports/top_interfaces_10d.csv    │
├─────────────────────────────────────────────────────────┤
│ Step 5: 验证输出                                        │
│         ✓ 文件存在且非空                              │
│         ✓ 列名正确（device, interface, speed...）      │
│         ✓ 数据准确（值在合理范围内）                  │
│         ✓ 行数等于预期（10行）                        │
│         ✓ 排序正确（流量从高到低）                    │
└─────────────────────────────────────────────────────────┘
```

### 与传统SQLQuery的区别

| 维度 | SQL导向测试 | 自然语言驱动测试 |
|------|-----------|-------------------|
| **输入** | 直接URL + SQL语句 | 自然语言需求（中文） |
| **测试内容** | SQL是否执行 | Agent是否理解 + 执行是否正确 + 输出是否正确 |
| **验证点** | 查询结果的正确性 | 理解→执行→输出三层验证 |
| **缺陷类型** | SQL语法错误 | 理解偏差、执行错误、格式错误 |
| **最终产物** | JSON数据 | CSV/MD文件 |
| **用户体验** | 需要懂SQL | 完全自然语言 |

---

## 🏆 优先级和通过标准说明

### 优先级分类

Every test case is marked with a priority level:

- 🔴 **P0 (必做, Must-Pass)**: 基础功能，Agent必须正确理解和执行
  - 这些测试验证Agent的核心能力
  - 如果P0测试全部失败，说明Agent基本功能有问题
  - **P0总数**: Level 1占25% (5个), Level 2占20% (8个), Level 3占15% (6个)

- 🟠 **P1 (应做, Should-Pass)**: 常见查询场景，Agent应该能搞定
  - 体现Agent的常规操作能力
  - **P1总数**: Level 1占50% (10个), Level 2占50% (20个), Level 3占50% (20个)

- 🟡 **P2 (可选, Nice-to-Have)**: 边界情况或增强功能
  - 验证Agent的容错能力和高级特性
  - 可以延后实现或在资源充足时优化
  - **P2总数**: Level 1占25% (5个), Level 2占30% (12个), Level 3占35% (14个)

### 通过标准

**每个Level的通过标准**:

| Level | PASS条件 | 失败条件 |
|-------|---------|--------|
| **L1** | ✅ P0全过 (5/5) AND 总过≥17/20 | ❌ P0有失败 OR 总过<17/20 |
| **L2** | ✅ P0过≥7/8 AND 总过≥28/40 | ❌ P0过<7/8 OR 总过<28/40 |
| **L3** | ✅ P0过≥5/6 AND 总过≥18/40 | ❌ P0过<5/6 OR 总过<18/40 |

**整体通过标准**:
```
L1 PASS ✓ AND
L2 PASS ✓ AND
L3 PASS ✓
→ Agent通过能力验证 ✅
```

### 验证优先级顺序

建议按以下顺序验证，可以逐步了解Agent能力：

1. **第1阶段** (Day 1): 验证所有L1-P0 (5个) → 判断基本是否可用
2. **第2阶段** (Day 2): 完成所有L1 (20个) → 确认基础能力
3. **第3阶段** (Day 3-4): 验证L2-P0 (8个) → 判断进阶能力
4. **第4阶段** (Day 5-6): 完成所有L2 (40个) → 统计中等能力
5. **第5阶段** (Day 7-9): 逐个L3场景 → 分析高级能力
6. **第6阶段** (Day 10): 生成最终报告

---

## 📋 Level 1 - 基础查询 (20测试)

### 特点
- **语言复杂度**: ⭐ 简单明确
- **查询复杂度**: ⭐ 单表或简单统计
- **预期通过率**: 95%+ (Agent应该100%理解)
- **验证方式**: 文件是否生成 + 数据是否完整
- **优先级分布**: 🔴 P0×5个 | 🟠 P1×10个 | 🟡 P2×5个
- **通过标准**: P0全过 (5/5) AND 总过≥17/20

### 测试清单

#### 1.1 列表类查询

```python
# 🔴 L1-001 (P0): 列出设备
用户需求: "列出所有设备"
期望输出: exports/all_devices.csv
关键能力: Agent能否理解基础"列出"命令
验证:
  ✓ 文件存在
  ✓ 列: device_id, name, device_type, mgmt_ip, location
  ✓ 行数 = 80 (测试数据设备数)
  ✓ 无重复行

# 🔴 L1-002 (P0): 列出接口
用户需求: "列出所有接口及其速率"
期望输出: exports/all_interfaces.csv
关键能力: Agent能否理解多字段查询
验证:
  ✓ 文件存在
  ✓ 列: interface_id, device_name, interface_name, speed_gbps, status
  ✓ 行数 = 1200
  ✓ speed_gbps全为正数

# 🟠 L1-003 (P1): 显示启用的接口
用户需求: "显示所有启用的接口"
期望输出: exports/enabled_interfaces.csv
关键能力: Agent能否理解过滤条件
验证:
  ✓ 所有行的enabled字段为true
  ✓ status仅为"up"或"down"，不包含"admin-down"
  ✓ 行数 = ~1140 (95% of 1200)
```

#### 1.2 统计类查询

```python
# 🔴 L1-004 (P0): 接口总数
用户需求: "有多少个接口?"
期望输出: exports/interface_count.md
关键能力: Agent能否理解COUNT聚合
验证:
  ✓ 文件包含数字 = 1200
  ✓ 格式正确（markdown或纯文本）

# 🟠 L1-005 (P1): 设备数统计
用户需求: "统计一下现在有多少个设备"
期望输出: exports/device_statistics.csv 或 .md
关键能力: Agent能否理解按类型分组
验证:
  ✓ 包含设备总数 = 80
  ✓ 按设备类型分类统计 (Router/Switch/Firewall)
  ✓ 各类型行数合计 = 80

# 🟠 L1-006 (P1): 接口状态分布
用户需求: "接口状态分布怎么样，up的有多少，down的有多少?"
期望输出: exports/interface_status_distribution.csv
关键能力: Agent能否理解多条件聚合
验证:
  ✓ 列: status, count, percentage
  ✓ 总count = 1200
  ✓ percentage和为100%
  ✓ up:down:admin-down ≈ 85%:10%:5%
```

#### 1.3 排序类查询

```python
# 🟠 L1-007 (P1): 按名称排序设备
用户需求: "列出所有设备，按名称排序"
期望输出: exports/devices_sorted_by_name.csv
关键能力: Agent能否理解ORDER BY
验证:
  ✓ name列按字母序排列 (A-Z)
  ✓ 所有80个设备都包含

# 🟡 L1-008 (P2): 显示最快和最慢的接口
用户需求: "显示速率最高和最低的接口"
期望输出: exports/extreme_speed_interfaces.csv
关键能力: Agent能否理解MIN/MAX
验证:
  ✓ 至少包含1个最快的接口 (100 Gbps)
  ✓ 至少包含1个最慢的接口 (1 Gbps)
  ✓ speed_gbps值范围正确

# 🟡 L1-009 (P2): 按位置统计接口
用户需求: "各个位置的接口有多少个?"
期望输出: exports/interfaces_by_location.csv
关键能力: Agent能否理解GROUP BY多维度
验证:
  ✓ 列: location, interface_count
  ✓ 按count从高到低排序
  ✓ 所有位置都被统计
```

#### 1.4 简单过滤

```python
# 🔴 L1-010 (P0): 过滤特定设备类型
用户需求: "显示所有路由器设备"
期望输出: exports/routers_only.csv
关键能力: Agent能否理解WHERE过滤
验证:
  ✓ 所有device_type都是"Router"
  ✓ 行数 = ~24 (30% of 80)

# 🟠 L1-011 (P1): 找出特定位置的设备
用户需求: "北京DC有多少台设备?"
期望输出: exports/beijing_devices.csv
关键能力: Agent能否理解中文位置名称
验证:
  ✓ 所有location都是"Beijing DC"
  ✓ 行数 = ~20

# 🟡 L1-012 (P2): 显示故障接口
用户需求: "显示状态为down的接口"
期望输出: exports/down_interfaces.csv
关键能力: Agent能否理解状态枚举值
验证:
  ✓ 所有status都是"down"
  ✓ 行数 = ~120 (10% of 1200)
```

#### 1.5 基本关联

```python
# 🟠 L1-013 (P1): 显示每个设备的接口
用户需求: "列出每个设备以及它有多少个接口"
期望输出: exports/devices_with_interface_count.csv
关键能力: Agent能否理解JOIN和GROUP BY
验证:
  ✓ 列: device_name, interface_count
  ✓ 所有接口都被计入
  ✓ 总和 = 1200
  ✓ count都是正数，平均15个/设备

# 🟡 L1-014 (P2): 显示有邻接关系的接口
用户需求: "哪些接口有邻接关系?"
期望输出: exports/interfaces_with_neighbors.csv
关键能力: Agent能否理解关联表查询
验证:
  ✓ 列: local_interface_id, remote_interface_id
  ✓ 行数 = 60 (邻接关系总数)

# 🟡 L1-015 (P2): 显示BGP邻居设备
用户需求: "哪些设备配置了BGP?"
期望输出: exports/bgp_enabled_devices.csv
关键能力: Agent能否理解关联子表
验证:
  ✓ 所有设备都在bgp_routes表中
  ✓ 行数 = 24 (BGP邻接设备数)
```

#### 1.6 导出格式验证

```python
# 🟠 L1-016 (P1): CSV格式验证
用户需求: "导出所有设备为CSV"
期望输出: exports/all_devices_export.csv
关键能力: Agent能否生成标准CSV
验证:
  ✓ 格式严格是CSV（逗号分隔，引号转义）
  ✓ 包含header行
  ✓ 可被Python csv.DictReader读取

# 🟡 L1-017 (P2): Markdown表格导出
用户需求: "用表格形式显示设备列表，可以复制到文档里"
期望输出: exports/devices_table.md
关键能力: Agent能否生成Markdown格式
验证:
  ✓ 是有效的markdown表格
  ✓ 包含table header分隔符 |---|
  ✓ 能在markdown预览器正确显示

# 🟡 L1-018 (P2): 空结果处理
用户需求: "显示没有任何接口的设备"  (结果应为0条)
期望输出: exports/no_interfaces_devices.csv
关键能力: Agent能否处理空结果集
验证:
  ✓ 文件存在（不crash）
  ✓ 只有header，无数据行（或友好提示）

# 🟡 L1-019 (P2): 非ASCII字符处理
用户需求: "显示所有设备及其位置" (含中文"北京DC"等)
期望输出: exports/all_devices_with_location.csv
关键能力: Agent能否正确处理UTF-8编码
验证:
  ✓ CSV能用UTF-8正确读取
  ✓ 中文位置名显示无乱码
  ✓ 行数 = 80

# 🟡 L1-020 (P2): 大小写统一处理
用户需求: "显示Router和router类型的设备"  (大小写混用)
期望输出: exports/routers_case_insensitive.csv
关键能力: Agent能否处理大小写敏感性
验证:
  ✓ 输出中只包含"Router"（统一为标准值）
  ✓ 无"router"的小写版本
  ✓ 行数 = ~24
```

---

## 📋 Level 2 - 中级查询 (40测试)

### 特点
- **语言复杂度**: ⭐⭐ 带条件和聚合
- **查询复杂度**: ⭐⭐ 多表JOIN或时间过滤
- **预期通过率**: 70-80% (某些Agent可能理解不完整)
- **验证方式**: 数据准确性 + 聚合逻辑 + 格式正确
- **优先级分布**: 🔴 P0×8个 | 🟠 P1×20个 | 🟡 P2×12个
- **通过标准**: P0过≥7/8 AND 总过≥28/40
- **高频失败原因**: 时间范围理解错误、NULL值处理、JOIN逻辑

### 典型场景

#### 2.1 时间范围查询

```python
# 🔴 L2-1 (P0): 过去N天的数据
用户需求: "过去10天的流量统计"
期望输出: exports/last_10_days_traffic.csv
关键能力: Agent能否理解相对时间范围
验证:
  ✓ 时间范围正确: [CURRENT_DATE-10, CURRENT_DATE]
  ✓ 列: date, interface_id, total_bytes_in, total_bytes_out  
  ✓ 行数约 = 1200接口 * 10天 = 12000行
  ✓ 无未来日期数据
  ✓ 日期跨度精确为10天
  💡 **常见失败原因**: Agent理解成"前10天"导致日期偏移

# 🔴 L2-2 (P0): 昨天的流量
用户需求: "昨天各接口的流量是多少?" 
期望输出: exports/yesterday_traffic.csv
关键能力: Agent能否理解"昨天"的准确含义
验证:
  ✓ 所有timestamp日期都是 CURRENT_DATE - 1
  ✓ 包含00:00-23:55的288条样本
  ✓ 无今天或前天的数据
  💡 **常见失败原因**: 把"昨天"理解成"前24小时"

# 🟠 L2-3 (P1): 本周流量
用户需求: "这一周各个接口的流量分别是多少?"
期望输出: exports/this_week_traffic.csv
关键能力: Agent能否理解周概念 (Monday-Sunday)
验证:
  ✓ 时间范围为本周（周一-今天）
  ✓ 周期计算正确
```

#### 2.2 聚合和统计

```python
# 🔴 L2-4 (P0): 接口平均流量
用户需求: "计算每个接口的平均流量"
期望输出: exports/interfaces_avg_traffic.csv
关键能力: Agent能否正确执行AVG聚合
验证:
  ✓ 列: interface_id, interface_name, avg_bytes_in, avg_bytes_out, avg_gbps
  ✓ avg值合理: min ≤ avg ≤ max
  ✓ 无NaN/Inf值
  ✓ 能处理无记录接口: avg=0或NULL
  💡 **常见失败原因**: 0值除法导致Inf或NULL

# 🟠 L2-5 (P1): 最大流量接口
用户需求: "找出流量最高的接口"
期望输出: exports/max_traffic_interface.csv
关键能力: Agent能否正确使用LIMIT 1
验证:
  ✓ 恰好1行（或并列最高的<5行）
  ✓ 值确实是全局最高

# 🔴 L2-6 (P0): 各设备的接口数
用户需求: "各设备有多少个接口?"
期望输出: exports/interface_count_by_device.csv
关键能力: Agent能否计数并分组
验证:
  ✓ 列: device_name, interface_count
  ✓ 总count = 1200 (所有接口)
  ✓ 行数 = 80 (所有设备)
  ✓ 无漏掉的设备
```

#### 2.3 组合过滤条件

```python
# 测试 L2-7: 启用且有流量的接口
用户需求: "找出启用并且有流量的接口"
期望输出: exports/active_interfaces.csv
验证:
  ✓ 所有enabled = true
  ✓ 所有status = "up"
  ✓ 所有接口在过去10天有流量

# 测试 L2-8: 未使用的接口
用户需求: "找出启用但在过去10天没有流量的接口"
期望输出: exports/idle_enabled_interfaces.csv
验证:
  ✓ 所有enabled = true
  ✓ 这些接口NOT IN (过去10天有流量的接口)
  ✓ 不包含新接口（created_at < 8天前）

# 测试 L2-9: 故障接口统计
用户需求: "各设备有多少个故障接口?"
期望输出: exports/down_interfaces_by_device.csv
验证:
  ✓ 列: device_name, down_count
  ✓ 只统计status="down"的接口
```

#### 2.4 多表关联

```python
# 测试 L2-10: 设备及其接口列表
用户需求: "列出每个设备以及它的接口"
期望输出: exports/devices_with_interfaces.csv
验证:
  ✓ JOIN成功（没有丢失数据）
  ✓ 列: device_name, interface_name, speed_gbps
  ✓ 总行数 = 总接口数

# 测试 L2-11: 接口及其流量统计
用户需求: "列出接口及其过去10天的总流量"
期望输出: exports/interfaces_with_stats.csv
验证:
  ✓ LEFT JOIN（不漏接口）
  ✓ 无流量的接口显示0或null
  ✓ 有流量的接口值正确

# 测试 L2-12: 邻接关系详情
用户需求: "显示所有邻接关系的详情"
期望输出: exports/link_relationships_detail.csv
验证:
  ✓ 列: local_device, local_interface, remote_device, remote_interface
  ✓ 任何未找到的邻接要明确说明
```

#### 2.5 排序和分组

```python
# 测试 L2-13: TOP 5流量接口
用户需求: "流量最高的5个接口是什么?"
期望输出: exports/top_5_traffic_interfaces.csv
验证:
  ✓ 恰好5行（或少于5行如果总共不足5个）
  ✓ 按流量从高到低排序
  ✓ 第一行的流量 ≥ 第二行 ≥ ...

# 测试 L2-14: 按设备类型统计接口
用户需求: "各种设备类型的接口数分别是多少?"
期望输出: exports/interface_count_by_type.csv
验证:
  ✓ 列: device_type, interface_count
  ✓ 总count = 总接口数
  ✓ 按count从高到低排序

# 测试 L2-15: 各位置的故障接口
用户需求: "各个位置的故障接口有多少个?"
期望输出: exports/down_interfaces_by_location.csv
验证:
  ✓ 列: location, down_count
  ✓ 只统计status="down"的
```

#### 2.6 百分比和比例

```python
# 测试 L2-16: 接口可用率
用户需求: "计算每个设备的接口可用率"
期望输出: exports/device_interface_availability.csv
验证:
  ✓ 列: device_name, total_count, up_count, availability_percent
  ✓ 百分比 = up_count / total_count * 100
  ✓ 范围0-100%

# 测试 L2-17: 流量占比
用户需求: "各个设备的流量占比是多少?"
期望输出: exports/device_traffic_percentage.csv
验证:
  ✓ 百分比和为100%
  ✓ 正确处理总流量为0的情况
```

#### 2.7-2.20: 更多场景
- L2-18: 周日和周日的流量对比
- L2-19: 特定协议的汇总（如BGP）
- L2-20: 缓存影响测试

---

## 📋 Level 3 - 高级查询 + 5大网络运维场景 (40测试)

### 特点
- **语言复杂度**: ⭐⭐⭐ 复杂的多维需求描述
- **查询复杂度**: ⭐⭐⭐ Window函数、递归、自连接等
- **预期通过率**: 30-50% (复杂需求，Agent可能理解不足)
- **验证方式**: 业务逻辑准确性 + HTML/PDF报告质量
- **优先级分布**: 🔴 P0×6个 | 🟠 P1×20个 | 🟡 P2×14个
- **通过标准**: P0过≥5/6 AND 总过≥18/40
- **高频失败原因**: Window函数理解错误、多维JOIN复杂度高、性能超时

### 5大核心网络运维场景

#### 场景 1: 容量规划 - TOP 10流量接口（L3-1~L3-8）

**运维背景**:
"过去10天哪些接口流量最多，我需要判断是否要升级。"

**复杂度分析**:
- ✅ 涉及表: devices → interfaces ← interface_stats
- ✅ 聚合: SUM(bytes), AVG计算Gbps
- ✅ 时间过滤: CURRENT_DATE - 10
- ✅ 排序+LIMIT: ORDER BY DESC LIMIT 10

**测试清单**:
```python
# L3-1: 基础版本
用户需求: "过去10天流量最高的接口"
期望输出: exports/top_10_traffic_interfaces_10d.csv
验证:
  ✓ 包含device_name, interface_name, total_bytes, avg_gbps
  ✓ 恰好10行（或全部如果 < 10）
  ✓ 按流量从高到低排序
  ✓ 单位正确（Gbps在合理范围）

# L3-2: 带速率信息
用户需求: "给我列出过去10天流量TOP 10的接口，包括它们的配置速率和实际流量，帮助我判断是否饱和"
期望输出: exports/top_traffic_capacity_analysis.csv
验证:
  ✓ 列: device, interface, speed_gbps, avg_gbps, utilization_percent
  ✓ utilization = avg_gbps / speed_gbps * 100
  ✓ 找出接近饱和的接口（>80%）

# L3-3, L3-4: 按设备分组版本、按协议分组版本

# L3-5~L3-8: 变体和边界
- 按天统计（每天TOP 1）
- 包含趋势（本周vs上周）
- 只看工作时间的流量
- 处理无流量接口
```

**预期输出示例**:
```csv
device_name,interface_name,speed_gbps,total_bytes_10d,avg_gbps,utilization_percent
R1,Gi0/0/0,100.0,2500000000000,25.5,25.5%
R2,Gi0/0/1,100.0,2100000000000,21.6,21.6%
SW1,Gi0/48,10.0,850000000000,8.7,87.0%
R3,Gi0/0/2,10.0,720000000000,7.4,74.0%
```

#### 场景 2: 异常检测 - 无流量接口（L3-9~L3-16）

**运维背景**:
"找出那些启用了但在过去10天没有任何流量的接口，可能是配置错误或Link Down。"

**复杂度分析**:
- ✅ 子查询: 构建"有流量的接口"列表
- ✅ NOT IN: 反向过滤
- ✅ LEFT JOIN: 保留所有启用的接口
- ✅ DATEDIFF: 排除太新的接口

**关键SQL逻辑**:
```sql
WITH active_ifaces AS (
  SELECT DISTINCT interface_id FROM interface_stats
  WHERE timestamp >= CURRENT_DATE - 10
)
SELECT i.device_id, d.name, i.interface_name, i.status, 
       DATE_DIFF('day', i.created_at, CURRENT_DATE) as age_days,
       lr.remote_device_id  
FROM interfaces i
JOIN devices d ON i.device_id = d.device_id
LEFT JOIN link_relationships lr ON i.interface_id = lr.local_interface_id
LEFT JOIN active_ifaces a ON i.interface_id = a.interface_id
WHERE i.enabled = true 
  AND a.interface_id IS NULL  -- 无流量
  AND DATE_DIFF('day', i.created_at, CURRENT_DATE) > 2  -- 非新接口
ORDER BY age_days DESC
```

**测试清单**:
```python
# L3-9: 基础版本
用户需求: "哪些接口启用但没有流量?"
期望输出: exports/idle_enabled_interfaces.csv
验证:
  ✓ 所有行的enabled = true
  ✓ 这些接口NOT IN最近10天有数据的接口
  ✓ 列: device, interface, status, age_days

# L3-10~L3-12: 变体
- 只看特定设备类型
- 按邻接关系分类（有邻接vs无邻接）
- 按创建时间划分（新<7天，中等7-30天，老>30天）

# L3-13~L3-16: 高级分析
- 涉及多个邻接关系的接口
- 考虑双向对称性
```

#### 场景 3: 关系验证 - 邻接对称性（L3-17~L3-24）

**运维背景**:
"BGP或OSPF邻接时，需要A向B有邻接，B向A也必须有邻接。我想找出配置不对称的情况。"

**复杂度分析**:
- ✅ 自连接: link_relationships表自己JOIN自己
- ✅ FULL OUTER JOIN: 找出只在一侧有的关系
- ✅ CASE: 分类对称/不对称/丢失

**关键SQL逻辑**:
```sql
SELECT 
  COALESCE(a.local_interface_id, b.remote_interface_id) as from_iface,
  COALESCE(a.remote_interface_id, b.local_interface_id) as to_iface,
  CASE 
    WHEN a.relationship_id IS NOT NULL AND b.relationship_id IS NOT NULL 
      THEN 'Symmetric'
    WHEN a.relationship_id IS NOT NULL 
      THEN 'Missing Return Path'
    ELSE 'Incomplete'
  END as status
FROM link_relationships a
FULL OUTER JOIN link_relationships b
  ON a.local_interface_id = b.remote_interface_id
  AND a.remote_interface_id = b.local_interface_id
```

**测试清单**:
```python
# L3-17: 找不对称的邻接
用户需求: "邻接关系中有没有不对称的情况?"
期望输出: exports/asymmetric_relationships.csv
验证:
  ✓ 只包含status != 'Symmetric'的行
  ✓ 列: from_interface, to_interface, status

# L3-18~L3-24: 变体和修复建议
- 只看特定协议（BGP vs ethernet）
- 包含修复建议SQL
- 违反的严重性评分
```

#### 场景 4: 趋势分析 - 周环比（L3-25~L3-32）

**运维背景**:
"本周的流量比上周有什么变化？增长太快可能有业务高峰，下降可能是故障。"

**复杂度分析**:
- ✅ Window函数: LAG计算前周同期
- ✅ 日期分组: WEEK()和DAYOFWEEK()
- ✅ 百分比: (this_week - last_week) / last_week * 100
- ✅ CASE: 分类异常（>50%, < -50%等）

**关键SQL逻辑**:
```sql
WITH daily_traffic AS (
  SELECT 
    interface_id,
    CAST(timestamp AS DATE) as traffic_date,
    WEEK(timestamp) as week_num,
    DAYNAME(timestamp) as day_name,
    SUM(bytes_in + bytes_out) as daily_bytes
  FROM interface_stats
  WHERE timestamp >= CURRENT_DATE - 21  -- 3周
  GROUP BY ...
),
week_comparison AS (
  SELECT 
    *,
    LAG(daily_bytes) OVER (PARTITION BY interface_id, day_name ORDER BY week_num) as prev_week_bytes,
    ROUND((daily_bytes - LAG(...) OVER (...)) / LAG(...) * 100, 2) as week_on_week_percent
)
SELECT *,
  CASE 
    WHEN week_on_week_percent > 50 THEN 'Significant Increase'
    WHEN week_on_week_percent > 10 THEN 'Moderate Increase'
    WHEN week_on_week_percent < -50 THEN 'Significant Decrease'
  END as anomaly_type
```

**测试清单**:
```python
# L3-25: 基础周环比
用户需求: "各接口这周vs上周流量对比"
期望输出: exports/weekly_traffic_comparison.csv
验证:
  ✓ 列: interface, day_of_week, this_week_bytes, last_week_bytes, wow_percent
  ✓ 百分比范围合理
  ✓ 处理"上周无数据"的情况

# L3-26~L3-32: 变体
- 月环比、年同比
- 异常接口TOP 10
- 包含趋势箭头（↑↓→）
```

#### 场景 5: 多维分析 - 设备×协议×流量（L3-33~L3-40）

**运维背景**:
"我想了解网络各部分的流量分布。不同设备类型，BGP/数据流量占比如何？"

**复杂度分析**:
- ✅ 多表JOIN: devices, interfaces, link_relationships, interface_stats
- ✅ GROUP BY多个维: device_type, relationship_type
- ✅ Window函数: 计算占比
- ✅ HAVING: 过滤异常

**关键SQL逻辑**:
```sql
SELECT 
  d.device_type,
  lr.relationship_type,
  COUNT(DISTINCT i.interface_id) as iface_count,
  SUM(s.bytes_in + s.bytes_out) as total_bytes,
  COUNT(DISTINCT DATE(s.timestamp)) as active_days,
  ROUND(SUM(...) / SUM(...) OVER (PARTITION BY d.device_type) * 100, 2) as percent_of_type
FROM devices d
JOIN interfaces i ON d.device_id = i.device_id
LEFT JOIN link_relationships lr ON i.interface_id = lr.local_interface_id
JOIN interface_stats s ON i.interface_id = s.interface_id
WHERE s.timestamp >= CURRENT_DATE - 10
GROUP BY d.device_type, lr.relationship_type
HAVING COUNT(*) > 0
ORDER BY d.device_type, total_bytes DESC
```

**测试清单**:
```python
# L3-33: 基础多维分析
用户需求: "各设备类型的协议流量分布如何?"
期望输出: exports/traffic_by_device_type_protocol.csv
验证:
  ✓ 列: device_type, protocol_type, iface_count, total_bytes, percent
  ✓ 百分比和 = 100%（按device_type）
  ✓ 识别异常（如BGP占比 > 10%）

# L3-34~L3-40: 高级分析
- 按地点多维分析
- 异常检测和推荐
- HTML仪表板输出
```

---

## 🔍 性能基准 (SLA)

### 预期执行时间

Query Agent的查询响应时间应该满足以下基准：

| Level | 预期时间 | 评价 | 说明 |
|-------|---------|------|------|
| **L1** | <100ms | ✅ 好 | 单表简单查询，应该很快 |
| | <300ms | ⚠️ 可接受 | 有简单JOIN或聚合 |
| | >500ms | ❌ 差 | 可能有性能问题 |
| **L2** | <300ms | ✅ 好 | |
| | <800ms | ⚠️ 可接受 | |
| | >1500ms | ❌ 差 | |
| **L3** | <1000ms | ✅ 好 | |
| | <2000ms | ⚠️ 可接受 | Window函数/复杂JOIN |
| | >5000ms | ❌ 差 | 需要优化或数据量太大 |

### 验证方法

```bash
# 使用time命令测量执行时间
time uv run olav ask "列出所有设备"
# real 0m0.087s  ✅ < 100ms

time uv run olav ask "过去10天流量TOP 10接口"
# real 0m0.342s  ✅ < 500ms

time uv run olav ask "周环比流量分析"
# real 0m1.234s  ⚠️ < 2000ms but slow
```

### 性能问题的诊断

- 如果 L1 > 500ms → 可能Agent生成了复杂SQL或数据库索引缺失
- 如果 L2 > 1500ms → JOIN或聚合有问题，或数据量超预期
- 如果 L3 > 5000ms → Window函数或复杂逻辑优化不足

---

## 🆘 故障诊断指南

### 故障模式 1: 输出文件不存在

**现象**: 用户输入后，期望的CSV/MD文件没有出现在 `exports/`

**可能原因**:
```
A. Agent没有理解用户的意图
   → 检查Agent的中间日志是否有理解失败的迹象
   
B. Query生成或执行失败
   → 手动复制Agent生成的SQL在数据库执行
   → 检查DuckDB错误日志
   
C. 输出路径权限问题
   → 检查 exports/ 目录的写权限
   → ls -la exports/
   
D. 超时或性能问题
   → 观察执行时间是否超过预期
   → 检查数据库连接是否还活跃
```

**诊断步骤**:
```bash
# Step 1: 查看Agent日志
tail -100 logs/query_agent.log | grep "用户输入的关键词"

# Step 2: 验证数据库
duckdb .olav/db/main.duckdb "SELECT COUNT(*) FROM devices"
# 应该返回 80

# Step 3: 检查文件权限
ls -la exports/ | head
chmod 755 exports/  # 如需要

# Step 4: 重新尝试（清除缓存）
rm -f exports/*.csv exports/*.md
uv run olav ask "原始需求"
```

---

### 故障模式 2: 输出文件存在但行数错误

**现象**: CSV生成了，但包含的数据行数不对

```bash
# 验证行数
wc -l exports/all_devices.csv
# 预期: 81 (80 devices + 1 header)
# 实际: 55  ← 缺少25个设备
```

**可能原因**:

```
A. WHERE条件过滤错误
   预期: WHERE device_type = 'Router'
   实际: WHERE device_type LIKE '%router%'  ← 大小写敏感
   
B. JOIN丢失数据
   预期: INNER JOIN → 所有接口的设备都在
   实际: LEFT JOIN可能导致NULL行
   
C. GROUP BY缺少维度
   预期: GROUP BY device_id, device_name
   实际: GROUP BY device_id  ← device_name聚合成一行
   
D. LIMIT不对
   预期: LIMIT 10
   实际: LIMIT 5  ← 返回太少
```

**诊断步骤**:
```bash
# 1. 比较预期行数
echo "Expected: SELECT COUNT(*) FROM devices WHERE device_type='Router'"
duckdb .olav/db/main.duckdb "SELECT COUNT(*) FROM devices WHERE device_type='Router'"
# 输出: 24

# 2. 检查CSV中的实际值
echo "Actual rows in CSV:"
wc -l exports/routers_only.csv
# 如果是 16，说明少了8个 → debug Agent

# 3. 提取SQL看Agent生成了什么
grep "final_sql" logs/query_agent.log | tail -1
```

---

### 故障模式 3: 时间范围理解错误 (L2高频失败)

**现象**: "过去10天"的查询返回了错误的日期范围

```bash
# 检查日期范围
head -5 exports/last_10_days_traffic.csv | cut -d',' -f1
# 预期: date列是 ['2026-01-29', '2026-01-30', ..., '2026-02-08']
# 错误1: 返回 ['2026-02-09', ..., '2026-02-18']  ← 理解成"未来10天"
# 错误2: 返回 ['2026-01-20', ..., '2026-02-08']  ← 理解成"过去20天"
```

**常见误解**:

```
Agent理解: CURRENT_DATE - 10  (错)
应该是:    CURRENT_DATE - INTERVAL 10 DAY

Agent理解: WHERE date >= '2026-01-29'  (之前的日期，错)
应该是:    WHERE date >= CURRENT_DATE - INTERVAL 10 DAY

Agent理解: 包括今天  (对)
应该验证: >= CURRENT_DATE - 10 and < CURRENT_DATE + 1
```

**诊断**:
```bash
# 查看CSV中的最早和最晚日期
echo "Date range in output:"
tail -n +2 exports/last_10_days_traffic.csv | cut -d',' -f1 | sort -u | head -1
tail -n +2 exports/last_10_days_traffic.csv | cut -d',' -f1 | sort -u | tail -1

# 对比系统现在的日期
date +%Y-%m-%d
```

---

### 故障模式 4: NULL值和0值处理

**现象**: 某些聚合结果显示为NULL或不合理

```bash
# 检查是否有过多NULL
grep -c '^.*,,.*$' exports/interfaces_avg_traffic.csv
# 如果>50行有连续逗号(NULL)，说明数据有问题

# 检查0值
awk -F',' '{print $5}' exports/interface_stats.csv | sort -u
# 如果全是0，说明可能没有数据或聚合错误
```

**常见原因**:
```
A. LEFT JOIN导致NULL
   Interfaces LEFT JOIN stats
   → 没有流量的接口显示NULL
   → 验证: 是否应该用COALESCE(..., 0)
   
B. 0值除法
   bytes / duration → NULL或Inf
   → 应该: CASE WHEN duration > 0 THEN bytes/duration ELSE 0 END
   
C. 空表JOIN
   → 验证: 是否bgp_routes表有数据？
   
D. GROUP BY导致结果被NULL覆盖
   → 检查是否遗漏了GROUP BY维度
```

---

## ⚠️ 已知局限

### AI语言模型的通用限制

#### 1. 复杂时间推理 ⚠️
**问题**: Agent对"这个月的第二周"这样的复杂时间表述容易理解错

**建议**:
- ✅ 使用简单表述: "过去10天", "昨天", "本周"
- ❌ 避免复杂表述: "这个月的第二个周一到周三"

#### 2. 多层嵌套逻辑 ⚠️
**问题**: "启用的设备中，接口都是down的设备"这种双重否定容易出错

**建议**:
- ✅ 拆分成多步
- ❌ 避免过深的逻辑嵌套

#### 3. 歧义自然语言 ⚠️✅ **问题**: "接口流量" 可能指 in/out/total，Agent可能猜错

**建议**:
- ✅ 明确指定: "入向字节总和" or "出向字节总和"
- ❌ 模糊表述: "接口的流量"

---

### OLAV系统当前限制

#### 1. 数据库支持 ❌
```
✅ 支持: DuckDB (原生)
❌ 不支持: MySQL, PostgreSQL, Elasticsearch等
```

#### 2. 自然语言支持 ⚠️
```
✅ 支持: 中文, 英文
❌ 不支持: 日语, 韩语, 其他语言
```

#### 3. 输出格式支持 ✅
```
✅ 支持: CSV, Markdown table
⚠️ 部分支持: JSON (仅简单数据)
❌ 不支持: Excel, PDF, HTML报告 (暂时)
```

#### 4. 数据大小限制 ⚠️
```
✅ 测试: < 100MB的结果集
⚠️ 超出: 可能导致内存不足或超时
```

#### 5. 实时预测 ❌
```
❌ 不支持: "预测明天的流量"
❌ 理由: 需要时序预测模型 (ARIMA, ML等)
✅ 支持: "历史流量趋势分析"
```

---

### 设计与范围限制

#### 1. 不在测试范围内的场景

**以下用例不纳入L1-L3能力评估**:
- ❌ L3-场景5 (多维分析): 文档不完整，待明年
- ❌ 实时告警: "接口down时立即通知" → 需要事件驱动系统
- ❌ 配置下发: "根据查询结果修改路由器配置" → 超出Query Agent范围
- ❌ 多步工作流: "先查设备，再查接口，最后导出" → 应该用Orchestrator

#### 2. 不是Bug的"失败"

这些不算Agent能力不足，而是设计局限：

```python
# 例1: 预测
Agent: "我不能预测，只能分析历史"
✅ 正确 - 这不是功能缺陷

# 例2: 无结果的查询  
Agent: "结果为空，未找到" (graceful)
✅ 正确

Agent: "ERROR: Query failed" (crash)
❌ 这才是缺陷

# 例3: 格式限制
Agent: "只能导出CSV"
✅ 正确 - 已声明的限制
```

---

## ✅ 验收标准

### 每个测试的验证维度

1. **理解准确性** (Agent是否理解了需求)
   - ✓ 生成了正确的查询计划
   - ✓ 选择了正确的表和字段
   - ✓ 时间范围、过滤条件都对

2. **执行正确性** (查询结果是否准确)
   - ✓ 数据值在合理范围内
   - ✓ 聚合结果可验证（和、数、平均）
   - ✓ 排序和分组逻辑正确

3. **输出完整性** (文件格式是否符合)
   - ✓ 文件正确生成（路径、格式）
   - ✓ 列名和顺序符合预期
   - ✓ 无遗漏行、无重复行
   - ✓ 字符编码正确（UTF-8）

4. **性能指标** (查询是否高效)
   - ✓ Level 1: <100ms
   - ✓ Level 2: <500ms
   - ✓ Level 3: <1500ms

---

## 🚀 执行计划

### Week 1: Implementation & L1-L2验证
- **Day 1-2**: 准备测试环境 + 验证Level 1 (20个)
  - 手动执行所有L1用例
  - 记录PASS/FAIL状态
  - 收集失败原因
  
- **Day 3-4**: 验证Level 2 (40个)
  - 重点测试P0用例 (时间范围)
  - 监控性能指标
  - 记录异常模式
  
- **Day 5**: 汇总L1-L2结果
  - 计算通过率
  - 优先级分布分析
  - 决策: Level 3是否继续

### Week 2: Level 3验证 & 最终报告
- **Day 1-3**: 验证Level 3各个场景
  - 场景1-3 (容量/异常/关系): 核心场景
  - 场景4-5 (趋势/分析): 高级场景
  - 专注于P0用例
  
- **Day 4-5**: 生成能力摸底报告
  - 性能基准对标
  - 缺陷库和改进建议
  - 下一步优化方向

---

**文档版本**: 2.0.0-with-standards (增强版)  
**最后更新**: 2026-02-08  
**维护者**: OLAV Development Team
