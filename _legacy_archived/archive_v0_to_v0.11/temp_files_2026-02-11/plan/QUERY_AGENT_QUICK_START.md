# Query Agent E2E 测试 - 快速开始指南（自然语言驱动版）

**文档**: Phase 4.1 Query Agent 能力摸底 - 快速参考  
**核心概念**: 用户说自然语言 → Query Agent执行 → 生成CSV/MD → 验证结果  
**版本**: v2.0（自然语言驱动）

---

## ⚡ 5分钟快速开始

### 1. 生成测试数据
```bash
cd /home/yhvh/Olav

# 生成标准测试数据（80个设备，1200个接口，10天流量数据）
uv run python scripts/generate_e2e_test_data.py

# 或清空后重新生成
uv run python scripts/generate_e2e_test_data.py --clear
```

### 2. 理解新的测试流程

**旧方式（SQL导向）**:
```python
# ❌ 过时的方式
result = await query_agent.execute(
    "SELECT * FROM devices WHERE device_type='Router'"
)
assert len(result) == expected_count
```

**新方式（自然语言驱动）**:
```python
# ✅ 新的E2E测试方式
result = await orchestrate_query(
    "列出所有的路由器设备"  # 用自然语言
)
# 验证生成的文件
assert Path("exports/routers_list.csv").exists()
verify_csv_content(Path("exports/routers_list.csv"))
```

### 3. 运行第一个自然语言测试
```bash
# 创建简单的Level 1测试
mkdir -p tests/e2e/level1
cat > tests/e2e/level1/test_basic_nl.py << 'EOF'
import pytest
from pathlib import Path
from olav.agents.orchestrator import orchestrate_query

@pytest.mark.e2e
async def test_list_all_devices():
    """用户需求: 列出所有设备"""
    result = await orchestrate_query("列出所有设备")
    
    # 验证文件是否生成
    csv_file = Path("exports/all_devices.csv")
    assert csv_file.exists(), "应该生成all_devices.csv文件"
    
    # 验证内容
    with open(csv_file) as f:
        content = f.read()
        assert "device_id" in content or "name" in content
        assert len(content.strip().split('\n')) > 1  # 有数据行
        assert "R001" in content or "R002" in content  # 有设备名

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
EOF

# 运行测试
uv run pytest tests/e2e/level1/test_basic_nl.py -v -s
```

---

## 🎯 自然语言查询示例（按难度）

---

## 📋 文件导航

### 规划文档
- **[QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md](QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md)**
  - 完整的摸底计划
  - 100+个测试用例规范
  - 5个网络运维场景详解
  - 性能目标和成功标准

### 实施文档
- **[QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md](QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md)**
  - 表结构和数据量要求
  - 5大网络运维场景的SQL详解
  - 测试框架代码示例
  - 数据验证函数库

### 脚本
- **[scripts/generate_e2e_test_data.py](../../scripts/generate_e2e_test_data.py)**
  - 自动生成完整的网络拓扑测试数据
  - 支持参数定制
  - 创建性能优化索引

---

## 🎯 核心网络运维场景速查

### 场景1: 容量规划 - TOP 10流量接口 ⭐⭐
**复杂度**: ★★☆ (中等)  
**关键技能**: JOIN (3表) + 时间过滤 + GROUP BY + ORDER BY + LIMIT  
**预期查询时间**: <100ms (1200接口)

**示例查询**:
```sql
-- 过去10天流量最高的10个接口
SELECT 
  d.name,
  i.interface_name,
  ROUND(SUM(bytes_in + bytes_out) / 1e9, 2) as total_gb,
  ROUND(SUM(bytes_in + bytes_out) * 8.0 / (10 * 24 * 3600 * 1e9), 2) as avg_gbps
FROM devices d
JOIN interfaces i ON d.device_id = i.device_id
JOIN interface_stats s ON i.interface_id = s.interface_id
WHERE s.timestamp >= CURRENT_DATE - INTERVAL 10 DAY
GROUP BY d.device_id, d.name, i.interface_id, i.interface_name
ORDER BY total_gb DESC
LIMIT 10
```

### 场景2: 异常检测 - 无流量接口 ⭐⭐⭐
**复杂度**: ★★★ (高)  
**关键技能**: 子查询 + NOT IN + LEFT JOIN + CTE + DATEDIFF  
**预期查询时间**: <500ms (1200接口，30天数据)

**示例查询**:
```sql
-- 开启但无流量的接口（排除新接口）
WITH with_traffic AS (
  SELECT DISTINCT interface_id
  FROM interface_stats
  WHERE timestamp >= CURRENT_DATE - INTERVAL 10 DAY
)
SELECT 
  d.name,
  i.interface_name,
  i.status,
  DATE_DIFF('day', i.created_at, CURRENT_TIMESTAMP) as age_days,
  lr.remote_device_id
FROM interfaces i
JOIN devices d ON i.device_id = d.device_id
LEFT JOIN link_relationships lr ON i.interface_id = lr.local_interface_id
LEFT JOIN with_traffic t ON i.interface_id = t.interface_id
WHERE i.enabled = true
  AND t.interface_id IS NULL  -- 没有流量
  AND DATE_DIFF('day', i.created_at, CURRENT_TIMESTAMP) > 2  -- 不是新接口
ORDER BY age_days DESC
```

### 场景3: 关系验证 - 对称性检查 ⭐⭐⭐
**复杂度**: ★★★ (高)  
**关键技能**: 自连接 + FULL OUTER JOIN + CASE WHEN  
**预期查询时间**: <200ms (60条邻接)

**核心概念**:
```sql
-- 检测邻接关系是否对称（A→B 应该对应 B→A）
SELECT 
  COALESCE(a.local_interface_id, b.remote_interface_id) as local_iface,
  COALESCE(a.remote_interface_id, b.local_interface_id) as remote_iface,
  CASE
    WHEN a.local_interface_id IS NOT NULL AND b.local_interface_id IS NOT NULL 
      THEN 'Symmetric ✓'
    WHEN a.local_interface_id IS NOT NULL 
      THEN 'Missing Return ⚠️'
    ELSE 'Incomplete ✗'
  END as status
FROM link_relationships a
FULL OUTER JOIN link_relationships b
  ON a.local_interface_id = b.remote_interface_id
  AND a.remote_interface_id = b.local_interface_id
WHERE a.local_interface_id IS NULL OR b.local_interface_id IS NULL
```

### 场景4: 趋势分析 - 周环比 ⭐⭐⭐⭐
**复杂度**: ★★★★ (高等)  
**关键技能**: Window函数 + LAG + 日期函数 + 百分比计算  
**预期查询时间**: <1000ms (1200接口，30天数据)

**提示**: 
- 使用 `WEEK(timestamp)` 分组周
- 使用 `LAG(bytes) OVER (PARTITION BY iface ORDER BY date)` 计算前一天
- 计算百分比变化: `(这周-上周) / 上周 * 100`

### 场景5: 多维分析 - 设备×协议×流量 ⭐⭐⭐⭐
**复杂度**: ★★★★ (高等)  
**关键技能**: 4表JOIN + 多维GROUP BY + Window函数 + HAVING  
**预期查询时间**: <1500ms

**优化建议**:
- 使用 `GROUP BY device_type, relationship_type`
- 使用 `SUM() OVER (PARTITION BY device_type)` 计算占比
- 用 `HAVING` 过滤异常（如BGP流量占比>10%）

---

## 🛠️ 常用SQL技巧

### 技巧1: 日期时间过滤
```sql
-- 最常见的时间范围过滤
WHERE timestamp >= CURRENT_DATE - INTERVAL 10 DAY
WHERE timestamp >= CURRENT_TIMESTAMP - INTERVAL '10 days'
WHERE timestamp BETWEEN DATE '2026-01-29' AND DATE '2026-02-08'

-- 提取时间部分
SELECT YEAR(timestamp), MONTH(timestamp), DAY(timestamp), HOUR(timestamp)
SELECT DATE_TRUNC('day', timestamp)  -- 按天分组
SELECT DATE_TRUNC('hour', timestamp)  -- 按小时分组
```

### 技巧2: 大数字转换（字节→GB/Gbps）
```sql
-- 字节转GB
bytes / 1e9 as gb

-- 字节转Gbps（速率计算）
(bytes * 8.0) / (seconds * 1e9) as gbps

-- 例子：10天的平均Gbps
SUM(bytes_in + bytes_out) * 8.0 / (10 * 24 * 3600 * 1e9) as avg_gbps
```

### 技巧3: 百分比和排名
```sql
-- 使用Window函数计算百分比
SELECT 
  interface_id,
  total_bytes,
  SUM(total_bytes) OVER () as total,
  ROUND(total_bytes / SUM(total_bytes) OVER () * 100, 2) as percent

-- 使用ROW_NUMBER排名（去重后的排名）
SELECT 
  *,
  ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY total_bytes DESC) as rank
WHERE rank <= 10
```

### 技巧4: 子查询vs JOIN性能
```sql
-- ❌ 慢: 子查询（可能导致全表扫描）
WHERE interface_id NOT IN (SELECT interface_id FROM interface_stats WHERE ...)

-- ✅ 快: LEFT JOIN + IS NULL
LEFT JOIN (...) ON condition
WHERE ... IS NULL
```

---

## ✅ 测试编写检查清单

### 前置条件
- [ ] 测试数据已生成 (`generate_e2e_test_data.py --clear`)
- [ ] 数据库路径正确 (`.olav/db/test_network.duckdb`)
- [ ] Query Agent能访问数据库

### 编写测试时
- [ ] 编写failing测试优先（TDD）
- [ ] 验证结果的列名和数据类型
- [ ] 验证结果数量合理（不是零值）
- [ ] 使用 `@pytest.mark.asyncio` 标记异步测试
- [ ] 添加性能断言（如：`elapsed_ms < 1000`）

### 常见陷阱避免
- ❌ 不要mock数据库 - 使用真实DuckDB
- ❌ 不要假设特定的行顺序 - 显式ORDER BY
- ❌ 不要硬编码日期 - 使用 `CURRENT_DATE`
- ❌ 不要忘记处理NULL值 - 使用 `COALESCE`

---

## 📊 性能基线

期望的查询性能目标（基于测试环境数据量）：

| 查询类型 | 数据量 | 目标时间 | 说明 |
|--------|--------|---------|------|
| 简单SELECT | 1.2K接口 | <50ms | 一表，LIMIT |
| 单JOIN | 1.2K接口 | <100ms | 两表JOIN，WHERE |
| 双JOIN | 1.2K接口,3.4M行 | <200ms | 三表JOIN，GROUP BY |
| CTE | 1.2K接口,3.4M行 | <500ms | 子查询+JOIN |
| Window函数 | 1.2K接口,3.4M行 | <1000ms | LAG/ROW_NUMBER |
| 复杂多维 | 1.2K接口,3.4M行 | <1500ms | 4表JOIN+Window |

---

## 🐛 调试技巧

### 慢查询调试
```bash
# 1. 启用EXPLAIN分析
EXPLAIN SELECT ... FROM ...
EXPLAIN ANALYZE SELECT ... FROM ...

# 2. 检查索引使用情况
PRAGMA table_info(interface_stats)
PRAGMA index_list(interface_stats)

# 3. 运行查询并计时
SELECT COUNT(*) FROM interface_stats  -- 基准
```

### 测试失败时
```bash
# 1. 运行具体查询看结果
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/test_network.duckdb')
results = conn.execute('''SELECT COUNT(*) FROM devices''').fetchall()
print(results)
"

# 2. 检查数据完整性
SELECT 
  COUNT(DISTINCT device_id) as devices,
  COUNT(DISTINCT interface_id) as interfaces,
  COUNT(*) as stats,
  MAX(timestamp) as latest_timestamp
FROM interface_stats
```

---

## 📚 相关文档

- 完整计划: [QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md](QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md)
- 实施指南: [QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md](QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md)
- 数据生成脚本: [scripts/generate_e2e_test_data.py](../../scripts/generate_e2e_test_data.py)

---

## 🚀 后续步骤

### Week 1 (Feb 8-14): 实施
1. **Day 1**: 生成测试数据、验证连接
2. **Day 2-3**: 实现Level 1基础查询测试 (20个)
3. **Day 4-5**: 实现Level 2中级查询测试 (40个)
4. **Day 6-7**: 实现Level 3高级查询测试 + 5个场景

### Week 2 (Feb 15-21): 分析与优化
1. 运行完整测试套件（100+个测试）
2. 收集性能数据和失败信息
3. 生成Query Agent能力摸底报告
4. 列出优化建议

---

**最后更新**: 2026-02-08  
**维护者**: OLAV Development Team  
**版本**: v1.0.0-planning
