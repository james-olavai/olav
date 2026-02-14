# 从SQL导向到自然语言驱动 - Query Agent E2E测试方法论的演进

**日期**: 2026-02-08  
**变更说明**: Phase 4.1测试方法从SQL导向改为自然语言驱动  
**文档**: QUERY_AGENT_E2E_NL_DRIVEN.md

---

## 📊 为什么要改变？

### 原始方法的问题 ❌

**旧的SQL导向测试**:
```python
# 测试的是SQL能否运行，而不是Agent的能力
query = "SELECT * FROM devices"
result = await orchestrate_query(query)
assert len(result) >= 10  # 验证数据存在
```

**问题**:
1. **测不出Agent的理解能力** - 直接给SQL，Agent没有理解过程
2. **不符合真实用例** - 用户不会直接写SQL，他们说自然语言
3. **缺少文件输出验证** - 只验证数据，不验证导出格式
4. **不符合OLAV的定位** - OLAV的核心价值是**用自然语言驱动网络查询**

---

### 新的方法的优势 ✅

**新的自然语言驱动测试**:
```python
# 测试Agent能否理解用户的自然语言需求并正确执行
user_request = "过去10天流量最高的10个接口是什么?"
result = await orchestrate_query(user_request)

# 验证三个层面：
# 1. Agent能否理解（有没有生成正确的查询计划）
# 2. 查询能否执行（结果数据是否准确）
# 3. 输出能否满足用户（CSV/MD文件是否正确生成）

assert Path("exports/top_10_traffic_interfaces.csv").exists()
verify_csv_format(...)
verify_data_accuracy(...)
```

**优势**:
1. **真正的E2E测试** - 从用户请求到文件输出的完整流程
2. **符合真实场景** - 用户说自然语言，系统返回可用的文件
3. **多维度验证** - 理解准确性 + 执行正确性 + 输出完整性
4. **发现真实缺陷** - 能识别Agent理解不足、执行错误、格式不对等各种问题
5. **符合OLAV使命** - 让网络工程师用自然语言查询网络数据

---

## 🎯 测试方法的对比

### 维度1: 输入方式

```
旧方法：
用户 → 手写SQL → 传给Query Agent → 执行
问题：不现实，用户不写SQL

新方法：
用户 → 自然语言需求（中文） → Query Agent理解和执行 → 输出CSV/MD
优势：完全符合真实场景
```

### 维度2: 验证内容

| 验证点 | 旧方法 | 新方法 |
|--------|--------|--------|
| **理解准确性** | ❌ 无 | ✅ 验证Agent理解了需求 |
| **执行正确性** | ⚠️ 只检查数据存在 | ✅ 验证数据值准确、聚合正确 |
| **输出完整性** | ❌ 无 | ✅ 验证CSV/MD格式、列名、行数 |
| **性能指标** | ⚠️ 简单记录 | ✅ 分级目标（L1<100ms, L3<1500ms） |
| **用户体验** | ❌ 无 | ✅ 用户获得的是可直接使用的文件 |

### 维度3: 缺陷发现

**旧方法少发现的缺陷**:
- Agent理解偏差（虽然SQL执行了，但理解错了）
- 输出格式错误（虽然数据对，但CSV格式不对）
- 列名不友好（缺少中文说明，格式不符合预期）
- 数据不完整（可能漏了某些聚合）

**新方法可以发现**:
- ✅ "过去10天"：Agent是否正确理解时间范围？
- ✅ "流量最高"：是否正确操作字节转Gbps的计算？
- ✅ "TOP 10"：是否正确限制行数？
- ✅ "导出为CSV"：格式是否可被Excel打开？
- ✅ "有中文列名"：是否生成友好的列标题？

---

## 📋 三级金字塔结构

### Level 1 - 基础（20测试）

**特点**: 简单的自然语言 → CSV基础输出

```
例子1: "列出所有设备"
  Agent需要理解: 查询所有device表记录
  执行: SELECT * FROM devices
  输出: all_devices.csv (含device_id, name, type等)
  验证: 文件存在、有header、行数≥50

例子2: "有多少个接口?"
  Agent需要理解: 统计接口总数
  执行: SELECT COUNT(*) FROM interfaces
  输出: interface_count.csv 或 .md
  验证: 包含数字≥1200

例子3: "显示启用的接口"
  Agent需要理解: 过滤enabled=true
  执行: SELECT * FROM interfaces WHERE enabled=true
  输出: enabled_interfaces.csv
  验证: 所有行enabled都是true
```

**预期通过率**: 95%+（应该完全理解）

---

### Level 2 - 中级（40测试）

**特点**: 复杂条件 + 聚合 + 时间过滤

```
例子1: "过去10天的流量统计"
  Agent需要理解: 
    - 时间范围: CURRENT_DATE - 10
    - 聚合: SUM(bytes_in + bytes_out)
    - 分组: 按日期或接口
  执行: 可能的SQL:
    SELECT DATE(timestamp), interface_id, 
           SUM(bytes_in + bytes_out) as total_bytes
    FROM interface_stats
    WHERE timestamp >= CURRENT_DATE - 10
    GROUP BY DATE(timestamp), interface_id
  输出: last_10_days_traffic.csv
  验证: 
    ✓ 时间范围正确
    ✓ 没有未来日期
    ✓ SUM值合理

例子2: "启用但在10天内无流量的接口"
  Agent需要理解:
    - 条件1: enabled = true
    - 条件2: NOT IN (过去10天有流量的接口)
    - 可选: 排除新接口
  执行: 使用NOT IN或LEFT JOIN
  输出: idle_enabled_interfaces.csv
  验证:
    ✓ 所有行enabled=true
    ✓ 这些接口确实无流量
    ✓ 行数合理（通常是总接口数的5-10%）

例子3: "各设备的接口数按数量排序"
  Agent需要理解:
    - 多表关联: devices ← interfaces
    - 聚合: COUNT(interface)
    - 排序: ORDER BY count DESC
  执行: JOIN + GROUP BY + ORDER BY
  输出: devices_interface_count.csv
  验证:
    ✓ 包含所有设备
    ✓ 总count = 总接口数
    ✓ 排序从高到低
```

**预期通过率**: 70-80%（某些复杂条件可能理解不完）

---

### Level 3 - 高级（40测试 + 5大场景）

**特点**: 多维分析 + Window函数 + 业务逻辑

```
5大核心场景：

场景1: 容量规划
输入: "过去10天流量最高的10个接口"
需要: 4表JOIN + 时间过滤 + 聚合 + TopN
输出: top_10_interfaces.csv
验证: 数据准确、聚合无误、排序正确

场景2: 异常检测
输入: "找出启用但无流量的接口"
需要: 复杂的NOT IN或LEFT JOIN逻辑
输出: idle_interfaces.csv
验证: 数据准确、不遗漏、不误杀

场景3: 关系验证
输入: "邻接关系中有没有不对称的情况?"
需要: 自连接 + FULL OUTER JOIN
输出: asymmetric_relationships.csv
验证: 对称性检查正确

场景4: 趋势分析
输入: "各接口这周vs上周流量对比"
需要: Window函数(LAG) + 百分比计算
输出: weekly_comparison.csv
验证: 周环比计算准确

场景5: 多维分析
输入: "设备类型和协议的流量分布"
需要: 多表JOIN + 多维GROUP BY + 百分比
输出: traffic_by_type_protocol.csv
验证: 维度完整、单位一致、百分比和=100%
```

**预期通过率**: 30-50%（复杂需求，可能理解不足或执行有偏差）

---

## 🔄 转换指南

### 如何从旧方法转换到新方法？

**旧的测试代码**:
```python
@pytest.mark.e2e
async def test_select_all_devices():
    """测试SELECT * FROM devices"""
    query = "SELECT * FROM devices"
    result = await orchestrate_query(query)
    assert len(result) >= 10
    assert all("device_id" in row for row in result)
```

**转换为新方法**:
```python
@pytest.mark.e2e
async def test_natural_language_list_devices():
    """测试: 用户说'列出所有设备'，Agent生成CSV"""
    
    # 1. 输入: 用户的自然语言需求
    user_request = "列出所有的设备，我想看设备ID、名称和类型"
    
    # 2. 执行: 通过orchestrate_query
    result = await orchestrate_query(user_request)
    
    # 3. 验证理解准确性: 是否生成了合理的查询计划
    assert result is not None  # Agent理解了需求
    
    # 4. 验证输出完整性: 文件是否正确生成
    csv_file = Path("exports/all_devices.csv")
    assert csv_file.exists(), "Agent应该生成CSV文件"
    
    # 5. 验证数据准确性: 内容是否正确
    with open(csv_file) as f:
        content = f.read()
        lines = content.strip().split('\n')
        assert len(lines) >= 2  # header + data
        assert "device_id" in lines[0] or "id" in lines[0]
        assert "name" in lines[0] or "设备名" in lines[0]
        assert len(lines) - 1 >= 50  # 至少50个设备

    # 6. 验证格式正确性: CSV格式是否符合预期
    assert content.count(',') > 0  # 逗号分隔
    assert '\n' in content  # 多行数据
```

**关键的转换点**:
1. ❌ 不再直接给SQL语句
2. ✅ 用自然语言描述用户的需求
3. ❌ 不再只验证"数据是否返回"
4. ✅ 验证"文件是否正确生成"
5. ❌ 不再依赖具体的SQL语句格式
6. ✅ 关注最终用户得到的CSV/MD文件

---

## 📊 文档对应关系

| 用途 | 文档 | 说明 |
|------|------|------|
| 理解新方法 | QUERY_AGENT_E2E_NL_DRIVEN.md | 📌 **必读** |
| 快速启动 | QUERY_AGENT_QUICK_START.md | 已更新 |
| 数据模型参考 | QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md | 表结构仍有用 |
| 旧方法参考 | QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md | ⚠️ 已过时 |

---

## 🚀 实施建议

### Week 1: 理解和准备
- [ ] 仔细阅读 QUERY_AGENT_E2E_NL_DRIVEN.md
- [ ] 生成测试数据
- [ ] 运行一个Level 1基础测试作为POC

### Week 2-3: 实现Level 1-2
- [ ] 实现20个Level 1基础测试
- [ ] 实现40个Level 2中级测试
- [ ] 确保所有CSV生成和验证都正确

### Week 4: 实现Level 3
- [ ] 实现5个核心场景的详细测试
- [ ] 收集性能指标
- [ ] 生成第一版摸底报告

---

## 💡 设计原理

### 为什么是"自然语言驱动"？

**OLAV的核心价值**:
> 让网络工程师用自然语言（而不是SQL/API）来查询网络数据

**因此E2E测试应该**:
> 验证这个核心价值是否实现 - Agent能否理解自然语言并返回有用的结果

**SQL导向的测试失效的原因**:
- 这不是真正的端到端流程
- 跳过了最关键的一步：Agent的理解
- 无法发现Agent理解偏差导致的缺陷

**自然语言驱动的测试有效**:
- ✅ 完整的端到端流程（用户请求→最终文件）
- ✅ 测试Agent的理解能力（最容易出问题的地方）
- ✅ 验证输出格式（用户真正需要什么形式的数据）
- ✅ 符合OLAV的使命

---

**版本**: 1.0.0  
**创建时间**: 2026-02-08  
**维护者**: OLAV Development Team
