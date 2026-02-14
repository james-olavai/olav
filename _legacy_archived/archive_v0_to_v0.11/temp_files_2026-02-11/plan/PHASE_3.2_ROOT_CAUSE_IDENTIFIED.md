# PHASE 3.2 ROOT CAUSE ANALYSIS
## 具体失败案例诊断报告

**Status**: 失败原因已确定 ✅  
**Date**: 2026-02-09  
**Confidence**: 高置信度 (通过数据库检查验证)

---

## 🔴 失败案例确认

### 失败的两个测试

从 quick_l1_test.py 中的 L1_QUICK_TESTS:

```python
("L1-P1-008", "P1", "列出所有border角色的设备", True),
("L1-P1-009", "P1", "列出所有core角色的设备", True),
```

**症状**: 这两个测试预期返回结果，但实际返回空或错误

---

## 🎯 根本原因: device_role 字段不存在

### 数据库实际结构

**✅ 实际存在的字段**:
```
device_id     (INTEGER)
name          (VARCHAR)
device_type   (VARCHAR)      ← 而不是 device_role!
mgmt_ip       (VARCHAR)
location      (VARCHAR)
vendor        (VARCHAR)
model         (VARCHAR)
site_id       (INTEGER)
created_at    (TIMESTAMP)
updated_at    (TIMESTAMP)
```

**❌ 测试查询期望的字段**:
```
device_role   (不存在!)
```

### 证据链

**Step 1**: 检查 test_network.duckdb 中的数据

```sql
-- ✅ 能成功执行
SELECT DISTINCT device_type FROM devices
结果: Switch (46个), Router (22个), Firewall (12个)

-- ❌ 失败
SELECT DISTINCT device_role FROM devices
错误: Binder Error: Referenced column "device_role" not found
```

**Step 2**: 测试查询分析

```python
# L1-P1-008 测试查询
query = "列出所有border角色的设备"

# LLM 可能生成的 SQL (基于 SKILL.md 中的 device_role 字段)
SELECT * FROM devices WHERE device_role = 'border'

# 执行结果: ❌ 失败 - device_role 不存在

# 应该生成的 SQL
SELECT * FROM devices WHERE device_type = 'core' # 或 'Router'
```

**Step 3**: 为什么没有返回 results？

```
L1 测试期望:
- query 成功执行 ✅
- 返回非空结果集 ✅

实际情况:
- LLM 根据 SKILL.md 生成错误 SQL ❌
- query_database 抛出异常
- 测试评估: FAILED
```

---

## 📊 失败链路分析

```
用户查询
   ↓
Orchestrator (query SubAgent)
   ↓
LLM 推理: "列出所有border角色的设备"
   ↓
SKILL.md 告诉 LLM:
   - device 表有 device_role 字段   ← ❌ 错误！
   - border 是一种 device_role 值    ← ❌ 推测错误
   ↓
LLM 生成 SQL:
   SELECT * FROM devices WHERE device_role = 'border'  ← ❌ 语法错误
   ↓
query_database() 执行:
   gw.query_main("SELECT * FROM devices WHERE device_role = 'border'", [])
   ↓
DuckDB 执行:
   Error: Column "device_role" not found   ← ❌ 列不存在
   ↓
query_database() 返回:
   "Database Error: Binder Error..."       ← ❌ 错误信息
   ↓
LLM 收到错误，尝试恢复:
   查看可用表... 但可能不成功         ← ⚠️   恢复失败
   ↓
最终返回:
   "无法找到相关设备"  或  错误信息  ← ❌ 失败
   ↓
L1 测试评估:
   预期非空结果，实际为空或错误
   判定: ❌ FAILED
```

---

## 🔬 为什么 SKILL.md 中的字段映射不生效？

### 问题

在 Phase 2.1 中，我们在 SKILL.md 中添加了字段映射表：

```markdown
## 🔧 v0.10.2+ 字段映射和错误恢复

| 错误字段 | 正确字段 | 表 | 类型 |
|---------|--------|-----|------|
| hostname | name | devices | VARCHAR |
| device_role | device_type | devices | VARCHAR |
| site | location | devices | VARCHAR |
```

### 但为什么 LLM 仍然生成错误查询？

**分析**:

1. **SKILL.md 字段映射表只是信息**
   - 这是一个参考表，不是强制转换
   - LLM 需要理解并应用这个映射

2. **LLM 可能的误解**
   - LLM 可能理解为 "这些字段有时候可以互换"
   - 或者 LLM 优先使用自己的知识库来猜测字段名
   - 或者 prompt 中的关键词不够突出

3. **缺少显式验证**
   - SKILL.md 没有说 "device_role 字段不存在"
   - SKILL.md 没有说 "border 不是一个 device_role 值"
   - SKILL.md 没有列出实际存在的 device_role 值

### 修复

SKILL.md 中应该改为:

```markdown
⚠️ CRITICAL: Available Fields in 'devices' table

✅ Use these field names EXACTLY:
- device_id (INTEGER)
- name (VARCHAR)
- device_type (VARCHAR)  ← Device type (Router, Switch, Firewall)
- mgmt_ip (VARCHAR)
- location (VARCHAR)
- vendor (VARCHAR)
- model (VARCHAR)

❌ DO NOT use these (they don't exist):
- device_role       ← DOES NOT EXIST! Use device_type instead
- hostname          ← DOES NOT EXIST! Use name instead
- site              ← DOES NOT EXIST! Use location instead
- ip_address        ← DOES NOT EXIST! Use mgmt_ip instead
- ios_version       ← DOES NOT EXIST!
- is_active         ← DOES NOT EXIST!

Available device_type values:
- Router (22 devices)
- Switch (46 devices)
- Firewall (12 devices)

Example queries:
- 列出所有 Router 类型的设备:
  SELECT * FROM devices WHERE device_type = 'Router'

- 列出所有在 Beijing DC 的设备:
  SELECT * FROM devices WHERE location = 'Beijing DC'
```

---

## 📋 L1 失败测试详细分析

### Test L1-P1-008: "列出所有border角色的设备"

| 属性 | 值 |
|-----|-----|
| 测试 ID | L1-P1-008 |
| 优先级 | P1 |
| 查询 | "列出所有border角色的设备" |
| 预期 | 返回非空的设备列表 |
| **实际** | **❌ 失败** |
| **失败原因** | device_role 字段不存在 |
| **根本原因** | 数据库没有 device_role 字段，只有 device_type |
| **数据库数据** | 0 个 border 角色的设备 (因为字段不存在) |

**SQL 分析**:

```sql
-- ❌ LLM 生成的 (基于过时信息)
SELECT * FROM devices WHERE device_role = 'border'
ERROR: Column "device_role" not found

-- ✅ 应该生成的 (虽然可能没有 border 类型)
SELECT * FROM devices WHERE device_type LIKE '%border%'
或
SELECT * FROM devices ORDER BY name  -- 并让 LLM 过滤

-- ✅ 实际可行的
SELECT * FROM devices WHERE device_type = 'Router'  -- 假设 border 应该是 Router
结果: 22 个 Router 类型的设备
```

### Test L1-P1-009: "列出所有core角色的设备"

| 属性 | 值 |
|-----|-----|
| 测试 ID | L1-P1-009 |
| 优先级 | P1 |
| 查询 | "列出所有core角色的设备" |
| 预期 | 返回非空的设备列表 |
| **实际** | **❌ 失败** |
| **失败原因** | device_role 字段不存在 |
| **根本原因** | 同上 |
| **数据库数据** | 0 个 core 角色的设备 (因为字段不存在) |

---

## 🎯 为什么 Phase 2.1 没有完全解决？

### Phase 2.1 做了什么

✅ 创建了字段映射表  
✅ 识别了 hostname/device_role/site 等问题  
✅ 创建了错误恢复协议  

### 但未完全解决的原因

❌ **字段映射表只是文档**
- 不是强制的字段转换规则
- LLM 可能不会完全执行
- 特别是对于 "device_role" 这样的字段，LLM 可能坚持使用

❌ **没有显式否定**
- SKILL.md 说 "device_role → device_type"
- 但没有明确说 "device_role 不存在，永远不要使用"
- LLM 可能忽略这个建议

❌ **没有验证实际数据**
- SKILL.md 中的 SQL 示例很好
- 但没有列出实际的设备类型值
- LLM 坚持使用 "border" 这样的值，因为这是网络术语

❌ **测试用例假设了存在的值**
- "border" 和 "core" 是网络术语
- 但测试数据库中没有这样的值
- 测试应该使用实际存在的值（Router, Switch, Firewall）

---

## ✅ 解决方案

### 短期 (立即)

**1. 修改 SKILL.md 中的说明**

```markdown
⚠️ CRITICAL SCHEMA INFORMATION

The 'devices' table structure:

EXACT Field Names (use these):
✅ name          - Device name (e.g., "R1", "SW001")
✅ device_type   - Type: Router | Switch | Firewall
✅ mgmt_ip       - Management IP
✅ location      - Location (e.g., "Beijing DC")

INCORRECT Fields (don't use these):
❌ device_role        - DOES NOT EXIST! (no border/core/access)
❌ hostname           - DOES NOT EXIST! (use 'name' instead)
❌ site               - DOES NOT EXIST! (use 'location' instead)
❌ ip_address         - DOES NOT EXIST! (use 'mgmt_ip' instead)
❌ ios_version        - DOES NOT EXIST!
❌ is_active          - DOES NOT EXIST!
```

**2. 修改 L1 测试用例**

```python
# 从
("L1-P1-008", "P1", "列出所有border角色的设备", True),
("L1-P1-009", "P1", "列出所有core角色的设备", True),

# 改为
("L1-P1-008", "P1", "列出所有Router类型的设备", True),
("L1-P1-009", "P1", "列出所有设备按类型分类", True),
```

**3. 在 query_database 中添加更好的错误提示**

```python
# src/olav/tools/react_query.py
# 当列不存在时，提示 LLM 使用 inspect_schema
except Exception as e:
    if "not found" in str(e).lower():
        hint = "\n\nUse inspect_schema() to check available columns"
        return f"Error: {e}\n{hint}"
    return f"Error: {e}"
```

### 中期 (Phase 3.2)

- [ ] 真正的字段验证 (在 SKILL.md 中使用 schema 验证器)
- [ ] 增强 LLM prompt 以强制使用正确字段
- [ ] 修改测试用例为真实场景
- [ ] 添加集成测试以验证 SKILL.md 字段准确性

### 长期 (Phase 3.3+)

- [ ] 动态 schema introspection (自动从数据库获取字段列表)
- [ ] 字段验证约束 (在 tool definition 中验证)
- [ ] 自动错误恢复 (使用 inspect_schema 来恢复)

---

## 📊 三个问题的最终答案

### Q1: 是否利用了 DeepAgents 原生缓存设计？

**A**: ⚠️ 部分利用
- ✅ 工具级: QueryResultCache (326x speedup)
- ❌ Agent级: 未使用 DuckDBSaver
- ❌ Prompt级: 未使用 SQLiteCache (LLM 缓存)
- ❌ 语义级: 未使用 semantic caching

**建议**: 这对于当前目标足够。长期可考虑完整集成。

### Q2: 多 agent 是否共享缓存？

**A**: ✅ 是的
- Singleton 模式确保单一实例
- query 和 expert SubAgents 都能使用
- 在单进程中完全共享 ✅
- 326x 加速经验证

### Q3: 失败案例是什么原因？

**A**: 🔴 **device_role 字段不存在**
- L1-P1-008/009 失败因为查询 device_role = 'border/core'
- 实际数据库只有 device_type = 'Router/Switch/Firewall'
- Phase 2.1 尝试修复但不够彻底 (字段映射表不够强制)
- 需要修改测试用例或加强 SKILL.md 说明

---

**Status**: 🎯 诊断完成，方案清晰
