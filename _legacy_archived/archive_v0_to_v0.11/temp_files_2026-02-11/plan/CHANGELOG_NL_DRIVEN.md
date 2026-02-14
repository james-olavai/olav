# Phase 4.1 Query Agent 能力摸底 - 改版说明

**日期**: 2026-02-08  
**改版**: 从SQL导向 → 自然语言驱动  
**状态**: ✅ 完成

---

## 📝 做了什么改变？

### 用户反馈
之前的Plan提出的问题：
> "这个e2e测试不应该给出具体sql命令，测试的目的是用户给出自然语言，LLM能不能理解执行，最终得出用户想要的数据，最后写入到csv或者md"

### 核心改变

**从这样**：
```python
# ❌ SQL导向：直接给SQL
@pytest.mark.e2e
async def test_select_all_devices():
    query = "SELECT * FROM devices"  # ← 直接是SQL
    result = await orchestrate_query(query)
    assert len(result) >= 10
```

**改为这样**：
```python
# ✅ NL驱动：用自然语言
@pytest.mark.e2e
async def test_list_all_devices():
    user_request = "列出所有的设备"  # ← 自然语言
    result = await orchestrate_query(user_request)
    
    # 验证生成的文件而不是直接的数据
    assert Path("exports/all_devices.csv").exists()
    verify_csv_has_correct_columns(...)
    verify_data_is_accurate(...)
```

---

## 📂 新增和更新的文档

### 新增文档

#### 1. **QUERY_AGENT_E2E_NL_DRIVEN.md** (24KB) ⭐ 核心
- 完整的自然语言驱动E2E测试规范
- 100+ 具体测试用例（3个等级）
- 5大网络运维场景详细说明
- 每个测试的验收标准

#### 2. **WHY_NATURAL_LANGUAGE_DRIVEN.md** (12KB) ⭐ 必读
- 说明**为什么**要做这个改变
- SQL导向 vs NL驱动的对比
- 转换指南

#### 3. **QUERY_AGENT_QUICK_START.md** (12KB) 已更新
- 新增NL驱动的快速开始示例
- 自然语言查询举例

#### 4. **INDEX.md** (16KB) 已更新
- 新的文档导航索引
- 推荐阅读顺序
- 优先级标记

### 保留的文档

- **QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md** (20KB)
  - 数据库设计（仍有用）
  - SQL逻辑参考（用于学习）
  
- **QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md** (36KB)
  - 标记为"已过时"
  - 保留作为参考

---

## 📊 新方法的三层测试结构

### Level 1 - 基础（20测试）
自然语言简单明确，查询单表或简单统计

**示例**:
- "列出所有设备"
- "有多少个接口?"
- "显示启用的接口"
- "接口按速率排序"

**验证**: 文件生成 + 列名正确 + 数据完整

**预期通过率**: 95%+

---

### Level 2 - 中级（40测试）
复杂条件、时间过滤、多表关联

**示例**:
- "过去10天的流量统计"
- "启用但在10天内无流量的接口"
- "各设备的接口数按数量排序"
- "计算每个接口的平均流量"

**验证**: 数据准确性 + 聚合逻辑 + 格式正确

**预期通过率**: 70-80%

---

### Level 3 + 5场景 - 高级（40测试）
复杂多维分析、Window函数、业务逻辑

**5大核心场景**:
1. **容量规划** - TOP 10流量接口
2. **异常检测** - 启用但无流量接口
3. **关系验证** - 邻接关系对称性
4. **趋势分析** - 周环比流量变化
5. **多维分析** - 设备类型×协议×流量

**验证**: 业务逻辑准确 + 输出质量（HTML/报告）

**预期通过率**: 30-50%

---

## 🎯 验证维度的改变

### 旧方法的验证（有限）
```
输入SQL → 执行 → 返回数据
验证: ✓ 数据是否存在？
```

### 新方法的验证（全面）
```
输入自然语言 → 理解 → 执行 → 生成文件 → 用户获得可用的数据
验证:
  ✓ 理解准确性 - Agent理解对了吗？
  ✓ 执行准确性 - 数据是否正确？
  ✓ 输出完整性 - CSV/MD格式对吗？
  ✓ 性能指标 - 查询耗时多少？
```

---

## 📋 立即开始的步骤

### 1. 理解新方法（必做）
```bash
# 阅读这两个文件：
cat docs/plan/WHY_NATURAL_LANGUAGE_DRIVEN.md          # 理解为什么
cat docs/plan/QUERY_AGENT_E2E_NL_DRIVEN.md           # 了解怎么做
```

### 2. 准备环境（5分钟）
```bash
# 生成测试数据
cd /home/yhvh/Olav
uv run python scripts/generate_e2e_test_data.py --clear

# 验证数据
uv run python -c "
import duckdb
c = duckdb.connect('.olav/db/test_network.duckdb')
print('✅ 设备:', c.execute('SELECT COUNT(*) FROM devices').fetchone()[0])
print('✅ 接口:', c.execute('SELECT COUNT(*) FROM interfaces').fetchone()[0])
"
```

### 3. 写第一个NL驱动测试（15分钟）
```bash
# 参考 QUERY_AGENT_E2E_NL_DRIVEN.md 的 Level 1 部分
# 复制一个最简单的测试用例：
# "列出所有设备" → 生成CSV → 验证

mkdir -p tests/e2e/level1
vim tests/e2e/level1/test_nl_basic.py  # 参考QUERY_AGENT_E2E_NL_DRIVEN.md编写
```

### 4. 运行测试（验证）
```bash
uv run pytest tests/e2e/level1/test_nl_basic.py -v -s
```

---

## 📚 文件导航速查

| 需求 | 查看文件 | 位置 |
|------|---------|------|
| 理解改变的原因 | WHY_NATURAL_LANGUAGE_DRIVEN.md | docs/plan/ |
| 了解完整测试设计 | QUERY_AGENT_E2E_NL_DRIVEN.md | docs/plan/ |
| 快速开始 | QUERY_AGENT_QUICK_START.md | docs/plan/ |
| 数据库参考 | QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md | docs/plan/ |
| 生成测试数据 | scripts/generate_e2e_test_data.py | scripts/ |
| 文档导航 | INDEX.md | docs/plan/ |

---

## ✅ 改版完成清单

- [x] 创建NL驱动的完整测试规范 (QUERY_AGENT_E2E_NL_DRIVEN.md)
- [x] 写出改变的原因和说明 (WHY_NATURAL_LANGUAGE_DRIVEN.md)
- [x] 更新快速开始指南 (QUERY_AGENT_QUICK_START.md)
- [x] 更新文档索引 (INDEX.md)
- [x] 保留数据模型和SQL参考资料
- [x] 标记过时的SQL导向文档
- [x] 100+ 具体测试用例规范
- [x] 5大网络运维场景详细说明
- [x] 验收标准和性能指标
- [x] 3个难度等级清晰划分

---

## 🚀 后续工作

### 立即开始（本周）
1. 阅读重要文档
2. 准备测试环境
3. 实现Level 1基础测试（20个）

### 下周开始
1. 实现Level 2中级测试（40个）
2. 实现Level 3高级+场景测试（40个）
3. 运行完整测试套件
4. 收集指标和缺陷

### 两周后
1. 生成Query Agent能力摸底报告
2. 识别缺陷和优化点
3. 规划Phase 4.2

---

## 📞 关键点总结

### 为什么改？
**因为用户不写SQL，他们用自然语言。真正的E2E测试应该验证这个过程。**

### 改成了什么？
**自然语言输入 → Agent理解执行 → 生成CSV/MD文件 → 验证结果准确**

### 如何开始？
1. 读WHY_NATURAL_LANGUAGE_DRIVEN.md（15分钟）
2. 读QUERY_AGENT_E2E_NL_DRIVEN.md Level 1部分（20分钟）
3. 生成测试数据（5分钟）
4. 写第一个测试（30分钟）

### 期望?
**Level 1 (95%通过) → Level 2 (70-80%) → Level 3 (30-50%)**

---

**版本**: 2.0 - NL Driven  
**日期**: 2026-02-08  
**改版人**: OLAV Development Team  
**状态**: ✅ 完成并准备实施
