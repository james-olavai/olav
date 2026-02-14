# OLAV Skill 改进分析

**目标**: 通过修改 network-query skill 来提升系统在零值数据下的表现

**当前成功率**: 57.8% (26/45测试通过)  
**改进目标**: 70%+ (通过更好的错误处理和结果解释)

---

## 📊 是否应该修改Skill?

### 答案: **YES，但只改特定部分**

当前Skill的问题分析：

```
当前Skill设计:
├─ ✅ 要求inspect_schema() (好)
├─ ✅ 处理类型转换 (好)
├─ ✅ 推荐使用CTE (好)
├─ ❌ 不处理零值情况 (问题!)
├─ ❌ 不区分"无数据"vs"数据为0" (问题!)
├─ ❌ 无法评估结果是否正确 (问题!)
└─ ❌ 结果解释不清楚 (问题!)
```

---

## 🎯 改什么效果最好？

### 优先级分析

| 改进项 | 难度 | 效果 | ROI | 建议 |
|--------|------|------|-----|------|
| **1. 零值/空结果检测** | 低 | 高 | 9/10 | 🔴 必做 |
| **2. 结果解释改进** | 低 | 高 | 8/10 | 🔴 必做 |
| **3. 数据质量检查** | 中 | 中 | 7/10 | 🟡 应做 |
| **4. 错误恢复提示** | 中 | 中 | 6/10 | 🟡 应做 |
| **5. 动态Schema学习** | 高 | 低 | 4/10 | 🟢 可选 |

**TOP 2改进点**: 零值检测 + 结果解释 → 投入2小时，收益10%成功率

---

## 🔴 MUST DO - 改这两个，立即提升

### 改进1: 添加零值检测逻辑

**当前问题**:
```python
Query: "Which interfaces have CRC errors?"
SQL: SELECT * FROM interfaces WHERE crc_errors > 0
Result: (empty)

输出: "No results found" ❌ 用户困惑
```

**应该改成**:
```python
Query: "Which interfaces have CRC errors?"
SQL: SELECT * FROM interfaces WHERE crc_errors > 0
Result: (empty)

# Agent额外检查:
SELECT COUNT(*) FROM interfaces  → 返回100
SELECT COUNT(CASE WHEN crc_errors > 0 THEN 1 END) FROM interfaces → 返回0

输出: "✅ 已检查100个接口，全部CRC错误计数为0"
    "这表示网络状况良好（模拟器环境中正常为0）"
```

**在Skill中的改写**:

```yaml
# 在system prompt中添加新规则

**11. EMPTY RESULT ANALYSIS** - 区分无数据vs全是0
   
   当查询返回空结果 (empty set) 时:
   ❌ WRONG: 直接返回 "No results found"
   
   ✅ RIGHT: 执行两步检查:
      Step 1: 运行 COUNT(*) 看表中有多少行
      Step 2: 如果有行但WHERE结果为空:
             说明是 "条件匹配为0" 而非 "无数据"
      
      例如:
        查询: "Which interfaces have crc_errors > 0?"
        Step 1: SELECT COUNT(*) FROM interfaces → 100 rows exist
        Step 2: SELECT COUNT(*) WHERE crc_errors > 0 → 0 rows match
        
        报告: "✅ 已检查100个接口，其中0个有CRC错误"
             "这是好消息 - 自动表示网络状况正常"
```

**实现位置**: `.olav/skills/network-query/SKILL.md` 第 25-30 行

**预期效果**: 
- 用户立刻理解结果含义
- 减少困惑，降低重复查询
- **成功率提升**: 5-8%

---

### 改进2: 改进结果解释和建议

**当前问题**:
```python
Query: "Show me devices with errors"

可能失败原因:
1. 字段不存在
2. 数据都是0
3. 真的无数据

输出: "Error: Unknown column" ❌ 用户不知道咋办
```

**应该改成**:
```python
# 改进错误消息

❌ 当前:
   "Error: Column 'input_errors' does not exist"

✅ 改进后:
   "❌ 字段 'input_errors' 不存在
   
   🔍 可能的原因:
      1. 模拟器数据中可能不包含该字段
      2. 字段名可能是: input_error (单数)
      3. 存储在其他表中
   
   ✅ 建议:
      - 运行 inspect_schema('interfaces') 查看实际字段
      - 或尝试其他字段名: 'input_error', 'input_packets_dropped'
      - 或查询其他表: devices, raw_outputs
   
   💡 提示: 模拟器环境中简单查询(VLAN, 设备清单)通常有数据"
```

**在Skill中的改写**:

```yaml
**12. SMART ERROR MESSAGES** - 诊断式错误提示

   当query_database()返回错误时，不要直接转发错误信息
   
   执行错误恢复协议:
   IF error contains "column ... does not exist":
      1. Call inspect_schema(table_name)
      2. 列出实际存在的列名
      3. 建议用户尝试类似的列名
      4. 提示可能的替代方案
      
   IF error contains "table ... does not exist":
      1. Call inspect_schema()
      2. 列出所有可用表
      3. 建议相关的表
      
   IF error contains "no rows":
      1. 检查是否是"零值"还是"真的无数据"
      2. 返回有意义的解释而非"no rows"
      
   例如:
      ❌ "no rows in result"
      ✅ "已检查所有表，在当前条件下无匹配数据"
         "🔍 可能的原因: 条件过于严格/数据不存在/字段名错误"
         "建议: 尝试 inspect_schema() 来探索可用数据"
```

**实现位置**: `.olav/skills/network-query/SKILL.md` 第 40-50 行

**预期效果**: 
- 用户知道如何调试失败的查询
- 减少"查询坏了"的假信号
- **成功率提升**: 3-5%

---

## 🟡 SHOULD DO - 这两个可以稍后做

### 改进3: 数据质量检查

**想法**: 在返回结果前，评估数据质量

```python
BEFORE returning results:

IF table name == 'interfaces':
   # 检查错误计数是否都是0
   SELECT COUNT(CASE WHEN input_errors > 0 THEN 1 END) as errors_found
   
   IF errors_found == 0:  # 所有都是0
      ADD_WARNING: "📊 数据质量提示: 所有错误计数都是0"
              "这在模拟器中很正常，表示网络健康"
              
ELIF table name == 'devices':
   # 检查是否有足够的设备
   IF COUNT(*) < 5:
      ADD_WARNING: "⚠️  只找到{N}个设备，数据可能不完整"
```

**实现难度**: 中  
**实现时间**: 1-2小时  
**预期效果**: +3-5% 成功率

---

### 改进4: 更好的错误恢复提示

**当前**:
```
试图修复 1 次，然后放弃
```

**改进后**:
```
尝试修复步骤:
1. 假设字段名错误 → inspect_schema() → 重试
2. 假设表名错误 → inspect_schema() → 重试  
3. 假设类型不匹配 → CAST字段 → 重试
4. 实在不行 → 输出诊断建议
```

**实现难度**: 中  
**实现时间**: 2-3小时  
**预期效果**: +2-3% 成功率

---

## 🟢 OPTIONAL - 长期改进

### 改进5: 动态Schema学习

**想法**: Agent记住之前成功的查询模式

```
第1次: 尝试查询 → 失败 → 学到 interfaces 有 crc_errors 字段
第2次: 同类查询 → 快速成功 (记住了模式)
```

**难度**: 高  
**收益**: 低 (因为查询类型多)  
**建议**: 不急着做

---

## 📝 具体改进方案

### 方案A: 极简改进 (30分钟) - 推荐

**只改一件事**: 添加零值检测器

```diff
+ # 在SKILL.md的system prompt中添加:
+ 
+ **11. ZERO VALUE DETECTION**
+    When query returns empty result (), check:
+    1. Is it "no data" or "data is all zeros"?
+    
+    执行检查:
+    - SELECT COUNT(*) FROM {table} 
+    - IF count > 0 AND WHERE result is empty:
+      说明是零值，解释为正常现象
```

**预期效果**: +5-8% 成功率  
**工作量**: 30分钟改Skill + 测试

---

### 方案B: 标准改进 (2小时) - 默认推荐 🌟

**改两件事**: 零值检测 + 错误恢复

```diff
+ 11. ZERO VALUE DETECTION (同上)
+ 
+ 12. SMART ERROR RECOVERY
+    When query fails:
+    - Check error type (column/table not found)
+    - Suggest alternatives using inspect_schema()
+    - Provide actionable suggestions
```

**预期效果**: +10-12% 成功率  
**工作量**: 2小时改Skill + 测试  
**ROI**: 非常高

---

### 方案C: 完整改进 (5小时)

**改四件事**: 零值 + 错误 + 数据质量 + 恢复提示

**预期效果**: +15-18% 成功率  
**工作量**: 5小时改Skill + 测试  
**ROI**: 高

---

## 🚀 建议：实施方案B (标准改进)

### 为什么选B?

1. **ROI最高**: 2小时工作 → 10%+ 提升
2. **易于测试**: 改动集中，容易验证
3. **可快速迭代**: 不满意可以继续改C
4. **立竿见影**: 用户立刻感受到改进

### 具体步骤

**第1步 (30分钟)**: 改Skill文件

```yaml
位置: .olav/skills/network-query/SKILL.md

在"3. CASE Statements"之后添加:

11. **ZERO VALUE HANDLING**
    When WHERE condition returns no rows:
    
    ✅ DO THIS:
       1. Check if table has data: SELECT COUNT(*) FROM {table}
       2. If count > 0 but WHERE returns empty:
          → Means "condition has no matches" not "no data"
          
       例: WHERE crc_errors > 0 returns empty
           But SELECT COUNT(*) returns 100
           
          解释为: "✅ 已检查100个接口，全部CRC正常"
       
    返回消息格式:
       ✅ [成功] 已检查 {count} 条记录，{matching} 条匹配
       或
       ✅ [成功] 已检查 {count} 条记录，无匹配 (这可能表示状况正常)

12. **ERROR DIAGNOSIS**
    When query_database() returns error:
    
    执行这个流程:
    IF "column ... does not exist":
       → Call inspect_schema(table_name)
       → Show available columns
       → Suggest similar column names
       
    IF "table ... does not exist":
       → Call inspect_schema()
       → Show available tables
       → Suggest similar table names
```

**第2步 (30分钟)**: 改orchestrator逻辑

位置: `src/olav/agents/orchestrator.py`

```python
# 改进返回结果的处理

def orchestrate_query(user_query, ...):
    # ... 现有逻辑 ...
    
    # 改进第1: 零值检测
    if isinstance(result, list) and len(result) == 0:
        # 执行检查
        check_result = check_if_data_exists(table_name)
        if check_result > 0:
            result_message = f"✅ 已检查 {check_result} 条记录，无匹配项"
            result_message += "\n💡 这可能是正常的(例如：无错误=好消息)"
        else:
            result_message = "⚠️ 表中无数据"
    
    # 改进第2: 错误恢复
    if "does not exist" in error_message:
        suggestions = suggest_alternatives(error_message)
        error_message += f"\n🔍 可能的替代方案: {suggestions}"
    
    return {
        'success': success,
        'result': result,
        'message': result_message,
        'explanation': explanation  # 新增：详细说明
    }
```

**第3步 (1小时)**: 测试和验证

```bash
# 创建测试用例
cd /home/yhvh/Olav

# 测试1: 零值检测
uv run olav query "Which interfaces have CRC errors?"
# 期望: "✅ 已检查100个接口，全部CRC正常"

# 测试2: 错误恢复
uv run olav query "Show interfaces with nonexistent_field"
# 期望: "❌ 字段不存在\n🔍 可能的字段: [列表]"

# 测试3: 兼容性检查
uv run python -m pytest tests/test_agent_improvements.py
```

---

## 📈 预期改进前后对比

```
当前状态:
├─ 成功率: 57.8% (26/45)
├─ 用户困惑度: 高 (空结果不知啥意思)
├─ 错误诊断: 不清楚 (Error: column X not found)
└─ 重复查询: 多 (用户重试)

改进后 (方案B):
├─ 成功率: 68-70% (+10%)
├─ 用户困惑度: 低 (清楚了解结果含义)
├─ 错误诊断: 清晰 (知道咋修复)
└─ 重复查询: 少 (用户知道该做什么)

满意度提升:
   客观指标: 成功率 +10%
   主观感受: 用户满意度 +30% (因为更清楚)
```

---

## ⚡ 快速决策树

```
应该改Skill吗?

是否想提升用户体验?
├─ YES
│  └─ 是否有2小时?
│     ├─ YES → 实施方案B (推荐)
│     └─ NO → 实施方案A (快速改)
└─ NO → 先把真实数据接进来，那个ROI更高
```

---

## 🎯 最终建议

### 立即行动 (建议)

✅ **实施方案B** (2小时工作)
1. 改SKILL.md (30分钟)
2. 改orchestrator.py (30分钟)
3. 测试验证 (1小时)

**收益**: 
- 成功率 57.8% → 68-70%
- 用户体验显著改善
- 支持未来迭代

---

### 更高优先级的改进

如果时间有限，这个ROI**更高**:
```
获取真实网络数据
  → 错误计数变成 > 0
  → 43% 的失败查询自动变成成功
  → 成功率 57.8% → 85%+
  → **远超Skill改进的效果**
```

**优先级**:
1. 🥇 获取真实网络数据 (最高ROI)
2. 🥈 改进Skill (中等ROI)
3. 🥉 添加历史数据表 (低ROI)

---

**结论**: ✅ **应该改Skill，但同时也应该准备真实数据。两者结合效果最好。**

