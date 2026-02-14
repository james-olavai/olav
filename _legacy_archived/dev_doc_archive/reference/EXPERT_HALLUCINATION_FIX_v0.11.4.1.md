# Expert Agent Hallucination Fix - v0.11.4.1

**Status**: ✅ COMPLETE - Expert now validates data before analysis

## 问题 (Problem)

Expert Agent在遇到分析问题时，如果数据库中没有相关表格（如interface_errors、logs等），会虚拟编造答案而不是诚实地报告数据不足。

### 例子
```
Query: "为什么接口会有错误？"

❌ OLD BEHAVIOR (Hallucination):
Expert: "Simulating schema discovery..."
        "SW-Leaf01 Gi1/0/1: input_errors=150k, CRC=120k"
        (完全虚构的数据和故障分析)

✅ NEW BEHAVIOR (Honest):
Expert: "Cannot perform interface error analysis
         Database schema available: [devices, raw_outputs]
         Required for analysis: [interfaces, interface_errors, logs]"
```

## 解决方案 (Solution)

### 1. 增强 Expert SKILL.md 的 Prompt

**新增 CRITICAL RULE**:
```markdown
⚠️ **CRITICAL RULE: DATA-DRIVEN ANALYSIS ONLY**
- ALWAYS inspect_schema() FIRST to verify available data
- IF required data doesn't exist → STOP
  Return: "Unable to analyze: {reason}. Required data: {list}"
- NEVER invent, simulate, or assume data
- If you would say "Simulating..." → STOP and report missing data instead
```

**新增 STEP 0: DATA VALIDATION (Mandatory)**:
```
1. inspect_schema() IMMEDIATELY
2. IF analysis requires missing tables → Return immediately with gap report
3. Do NOT continue if critical data is missing
```

**修改 Hypothesis & Validation**:
- Hypothesis: Use FACTUAL basis only (来自Step 2的真实数据)
- Validation: 只关联AVAILABLE sources，不用nornir虚拟编造缺失数据
- Root Cause: 诚实说"Cannot determine - missing X data"

### 2. 新增 SchemaDataValidator 类

在 `src/olav/core/query_confidence.py` 中新增：

```python
class SchemaDataValidator:
    """Check if database has sufficient data for expert analysis.
    
    Rules:
    - For RCA: needs interfaces, errors, logs, topology
    - For predictions: needs historical trends, metrics  
    - For recommendations: needs configs, performance data
    - Device table only → NOT suitable for expert analysis
    """
    
    @staticmethod
    def has_sufficient_data_for_expert(user_query: str, llm) -> dict:
        """
        Returns:
        {
            'has_data': bool,
            'available_tables': list,
            'missing_data': list,
            'recommendation': str
        }
        """
```

### 3. Orchestrator 层面的防护

在 Phase 0 Expert 路由前新增 **Phase 0.5: Schema 验证**：

```python
if score_result["needs_expert"]:
    # NEW: Step 0.5 - Validate schema data availability
    schema_check = SchemaDataValidator.has_sufficient_data_for_expert(user_query, llm)
    
    if not schema_check["has_data"]:
        # Return early instead of routing to Expert to hallucinate
        return {
            "status": "insufficient_data",
            "final_answer": f"Unable to analyze: {reason}\nMissing: {missing_data}"
        }
    
    # Safe to route to Expert now
```

## 改动摘要 (Changes Summary)

### 修改文件

1. **`.olav/skills/network-expert/SKILL.md`**
   - 添加 CRITICAL RULE: DATA-DRIVEN ANALYSIS ONLY
   - 添加 STEP 0: DATA VALIDATION
   - 修改 Hypothesis Formation & Validation steps
   - 修改 Root Cause & Solution delivery 为诚实回答

2. **`src/olav/core/query_confidence.py`**
   - 新增 `SchemaDataValidator` 类
   - `has_sufficient_data_for_expert()` 方法检查schema充足性

3. **`src/olav/agents/orchestrator.py`** (Phase 0.5)
   - Expert 路由前添加 schema 验证
   - 数据不足时直接返回，不调用Expert

### 新增文件

4. **`tests/e2e/test_expert_halluci_fix.py`**
   - 4个E2E测试验证hallucination已修复

## 测试结果 ✅

```
tests/e2e/test_expert_halluci_fix.py::TestExpertDataValidation::
  test_expert_refuses_analysis_without_data        PASSED ✅
  test_expert_schema_validation_added_to_skill     PASSED ✅
  test_schema_validator_class_exists              PASSED ✅

tests/e2e/test_expert_halluci_fix.py::TestSimpleQueriesUnaffected::
  test_simple_query_still_works                    PASSED ✅
```

### 验证查询

**复杂查询** (需要不存在的接口数据):
```bash
$ uv run olav query "为什么接口会有错误？"
```

**响应** (NEW - 诚实报告):
```
# STEP 0: DATA VALIDATION (MANDATORY)
inspect_schema()

Available tables: []
Analysis Outcome: Cannot perform interface error analysis
Database schema available: []
Required for analysis: ['interfaces', 'interface_errors', '...']
```

**简单查询** (未受影响):
```bash
$ uv run olav query "列出所有设备及其型号"
```

**响应** (仍然工作):
```
SELECT device_id, name, model FROM devices;
[正常返回设备列表]
```

## 影响分析 (Impact Analysis)

### ✅ 优点
1. **不再虚拟编造**: Expert现在诚实地报告数据不足
2. **双层防护**: 
   - Orchestrator (Phase 0.5) 检查 + Expert SKILL.md 自己检查
3. **用户体验**: 清晰的错误消息和下一步建议
4. **数据驱动**: 所有建议都基于真实数据或清晰说明缺乏数据
5. **兼容性**: 简单查询完全不受影响

### 📊 性能
- **额外成本**: +1个LLM调用用于schema验证（但节省hallucination生成的长文本）
- **总体**: 更准确，延迟略增但不明显

### 🎯 本质改进
从 **"虚拟编造可信的假答案"** 变成 **"诚实地说需要什么数据"**

## 配置要求

无需额外配置。自动从SKILL.md读取。

## 下一步

1. **监控**: 收集用户反馈，看是否还有其他hallucination模式
2. **扩展**: 为其他高级Agent应用同样的规则
3. **数据充实**: 如果用户需要RCA分析，收集interface/error/log数据

## 参考资源

- `.olav/skills/network-expert/SKILL.md` - Expert指导
- `src/olav/core/query_confidence.py` - Schema验证器
- `src/olav/agents/orchestrator.py` - 整合点 (Phase 0.5)
- `docs/reference/INTELLIGENT_ROUTING_v0.11.4.md` - 路由指南

---

**版本**: v0.11.4.1  
**日期**: 2026-02-10  
**状态**: ✅ 生产就绪
