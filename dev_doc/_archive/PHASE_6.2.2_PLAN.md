# Phase 6.2.2: Enhanced Execution Plan Output

**Status**: Planning  
**Phase**: 6.2.2 Enhanced Plan Output  
**Timeline**: 2-3 days  
**Goal**: Improve plan markdown generation with dynamic information, risk analysis, and visual aids

---

## 🎯 Objectives

### Primary
1. **Dynamic Time Estimation**: Calculate per-step execution time instead of hardcoding "~2-3 minutes"
2. **Dependency Visualization**: Better display of dependency relationships and execution flow
3. **Risk Analysis**: Calculate risk level based on dependency complexity, num steps, etc.
4. **Input Validation**: Show what inputs are required and validate intent

### Secondary
1. More detailed step descriptions with context
2. Better emoji/formatting for readability
3. Show estimated parallelization opportunities  
4. Highlight critical path (steps that block others)

---

## 📋 Implementation Plan

### Sub-Phase 6.2.2.1: Dynamic Time Estimation

**Enhancement**:
```python
# Current (hardcoded):
- **预计时间**: ~2-3 分钟

# New (dynamic):
- **总预计时间**: ~85s (根据步骤和依赖计算)
  - Step 1 (query): ~20s
  - Step 2 (netbox): ~45s (等待Step 1)
  - Step 3 (analyzer): ~20s (等待Step 1 & 2)
```

**Implementation**:
1. Create `time_estimator.py` with SubAgent timing profiles
   - Default times: query=20s, netbox=45s, analyzer=20s, etc.
   - Configurable via SKILL.md or .env
2. Calculate critical path (longest dependency chain)
3. Display per-step and total estimated times
4. Show parallelization info ("Steps can run in parallel: none in this case")

**RED Tests**:
- test_time_estimation_single_step
- test_time_estimation_parallel_dependencies
- test_time_estimation_linear_chain
- test_time_estimation_configurable_profiles

---

### Sub-Phase 6.2.2.2: Dependency Visualization

**Enhancement**:
```python
# Current:
### 1️⃣ QUERY
- **任务**: 查询网络设备数据
- **输出**: `network_devices_data`
- **依赖**: 无

### 2️⃣ NETBOX
- **任务**: 查询NetBox数据库
- **输出**: `netbox_data`
- **依赖**: `network_devices_data`

# New (with visual flow):
### 1️⃣ QUERY
- **任务**: 查询网络设备数据
- **输出**: `network_devices_data`
- **依赖**: 无
- **消费**: Step 2 (NETBOX), Step 3 (ANALYZER)
- **预计时间**: 20s
- **关键信息**: 这是最早执行的步骤，Step 2 开始前必须完成

### 2️⃣ NETBOX  
- **任务**: 查询NetBox数据库
- **输出**: `netbox_data`
- **依赖**: `network_devices_data` ← Step 1
- **消费**: Step 3 (ANALYZER)
- **预计时间**: 45s
- **关键信息**: 关键路径上！延迟这个步骤会影响总时间

### 3️⃣ ANALYZER
- **任务**: 对比数据并生成报告
- **输出**: `diff_report`
- **依赖**: `network_devices_data` ← Step 1, `netbox_data` ← Step 2
- **预计时间**: 20s
- **关键信息**: 最后执行的步骤，依赖所有前面的步骤

## 依赖流程图
```
[QUERY]──┐ (20s)
         ├─→ [ANALYZER]  (20s) → 完成！
[NETBOX]─┘ (45s)

执行流程: QUERY + NETBOX (并行，但此处顺序) → ANALYZER
批判路径: QUERY (20s) → NETBOX (45s) → ANALYZER (20s) = 85s 总计
```

**Implementation**:
1. Extend DependencyGraph to include "consumed_by" relationships
2. Add `is_critical_path()` method to identify bottleneck steps
3. Generate dependency flow visualization
4. Show which steps can run in parallel (if any)

**RED Tests**:
- test_dependency_flow_generation
- test_critical_path_identification
- test_parallel_opportunity_detection
- test_consumed_by_relationships

---

### Sub-Phase 6.2.2.3: Risk Analysis

**Enhancement**:
```python
# Current:
- **风险等级**: 低

# New (calculated):
- **风险等级**: 🟢 低
  - 步骤数: 3 (低)
  - 依赖复杂度: NETBOX 是关键路径 (中)
  - 失败影响: ANALYZER 依赖所有前面步骤，可能性 (中)
  - **建议**: 优先检查 NETBOX 的成功
```

**Risk Calculation**:
- Step count: <3 = Low, 3-5 = Medium, >5 = High
- Dep complexity: max 1 = Low, 1-2 = Medium, >2 = High  
- Failure impact: num steps that fail if this fails
- Combined: (step_count + dep_complexity + failure_impact) / 3

**Implementation**:
1. Create `risk_analyzer.py` with scoring logic
2. Override `_build_dependency_graph()` to calculate risk
3. Display risk emoji (🟢 Low / 🟡 Medium / 🔴 High)
4. Show specific risk factors

**RED Tests**:
- test_risk_low_simple_plan
- test_risk_high_complex_dependencies  
- test_risk_failure_impact_calculation
- test_risk_emoji_assignment

---

### Sub-Phase 6.2.2.4: Input Validation

**Enhancement**:
```python
# New section before execution steps:
## 📝 输入要求

- **User Intent**: "同步网络设备到NetBox" ✅ 识别 (NetBox sync intent)
- **Required Inputs for Steps**:
  - Step 1 (QUERY): user_query ✅ (推断: "同步网络设备到NetBox")
  - Step 2 (NETBOX): database_access ✅ (将在runtime检查)
  - Step 3 (ANALYZER): 前面步骤输出 ✅
- **Configuration Check**:
  - NetBox URL: ⚠️ 未配置 (假设会在runtime提供)
  - Credentials: ⚠️ 未检查 (假设会在runtime提供)
```

**Implementation**:
1. Extend `plan_mode_handler()` to validate intent
2. Check required config/inputs before showing plan
3. Show validation status for each step
4. Warn about missing credentials

**RED Tests**:
- test_intent_validation_netbox_recognized
- test_intent_validation_bgp_recognized
- test_intent_validation_unknown_recognized
- test_input_validation_missing_config_warning

---

## 📊 Expected Output (Phase 6.2.2 Complete)

```markdown
# 📋 执行计划

## 任务: 同步网络设备到NetBox

生成时间: 2026-02-07 01:15:30

---

## 📝 输入要求

- **User Intent**: "同步网络设备到NetBox" ✅ 识别 (NetBox sync intent)
- **Required Inputs for Steps**:
  - Step 1 (QUERY): user_query ✅ (推断: "同步网络设备到NetBox")
  - Step 2 (NETBOX): database_access ✅ (将在runtime检查)
  - Step 3 (ANALYZER): 前面步骤输出 ✅
- **Configuration Check**:
  - NetBox URL: ⚠️ 不会进行验证 (直到执行时)
  - Credentials: ⚠️ 不会进行验证 (直到执行时)

---

## 执行步骤

### 1️⃣ QUERY (关键路径起点)

- **任务**: 查询网络设备数据: 同步网络设备到NetBox
- **输出**: `network_devices_data`
- **依赖**: 无
- **消费**: Step 2 (NETBOX), Step 3 (ANALYZER)
- **预计时间**: 20s
- **关键信息**: 这是最早执行的步骤，必须完成才能继续

### 2️⃣ NETBOX (关键路径)

- **任务**: 查询NetBox数据库: 同步网络设备到NetBox
- **输出**: `netbox_data`
- **依赖**: `network_devices_data` ← Step 1
- **消费**: Step 3 (ANALYZER)
- **预计时间**: 45s
- **关键信息**: 关键路径上！这是耗时最长的步骤，可能影响总执行时间

### 3️⃣ ANALYZER (最终步骤)

- **任务**: 对比数据并生成报告
- **输出**: `diff_report`
- **依赖**: `network_devices_data` ← Step 1, `netbox_data` ← Step 2
- **预计时间**: 20s
- **关键信息**: 最后执行的步骤，必须等待所有前面步骤完成

---

## 📊 汇总

### ⏱️ 时间估计

- **Step 1 (QUERY)**: 20s
- **Step 2 (NETBOX)**: 45s (等待Step 1)
- **Step 3 (ANALYZER)**: 20s (等待Step 1 & 2)
- **总预计时间**: 85s (~1.5 分钟)
- **执行模式**: 顺序执行 (依赖关系: QUERY → NETBOX → ANALYZER)
- **并行机会**: 无 (所有步骤形成线性链)

### 📈 风险分析

- **风险等级**: 🟢 低
  - 步骤数: 3 (低)
  - 依赖复杂度: 线性链 (低-中)
  - 失败影响: NETBOX 失败会阻止 ANALYZER (中)
  - **建议**: 监控 NETBOX 执行，确保数据库连接正常

### 🔁 依赖流程

```
[1️⃣ QUERY]
    ↓ (20s)
[2️⃣ NETBOX]
    ↓ (45s)
[3️⃣ ANALYZER] ✅ 完成
    ↓ (20s)

关键路径: QUERY (20s) + NETBOX (45s) + ANALYZER (20s) = 85s
```

---

## ✅ 确认执行?

请输入以下选项之一:
- **Y**: 继续执行 (Step 1 → Step 3)
- **n**: 取消执行
- **edit**: 编辑计划 (未来支持)
- **details**: 显示更多细节

**选择 (Y/n/edit/details)**:
```

---

## 🧪 Testing Strategy

### RED Tests (New)
- 4 per sub-phase (16 total for Phase 6.2.2)
- Focus on output generation correctness
- Verify calculations (time, risk, etc.)

### Integration
- Test with various intent types (NetBox, BGP, etc.)
- Test with different dependency configurations
- Test with missing/invalid configs

---

## 📈 Success Criteria

✅ **Phase 6.2.2 Complete When**:
1. All 16 RED tests PASS (4 per sub-phase)
2. Time estimation within 10% accuracy
3. Risk analysis identifies critical path correctly
4. Input validation catches config issues
5. Markdown output is readable and informative
6. All backward compatibility maintained (Phase 1-5 tests still pass)

---

## ⏳ Timeline

- **6.2.2.1**: Dynamic Time Estimation (8h)
- **6.2.2.2**: Dependency Visualization (8h)
- **6.2.2.3**: Risk Analysis (8h)
- **6.2.2.4**: Input Validation (6h)
- **Integration & Testing**: (4h)
- **Total**: ~2-3 days

---

## Phase Dependencies

✅ **Phase 6.2.1 Complete**: /plan prefix detection working, 6/6 RED tests pass  
⏳ **Phase 6.2.2 In Progress**: Enhanced output (current)  
⏳ **Phase 6.2.3**: User confirmation flow (depends on 6.2.2)  
⏳ **Phase 6.3**: Error recovery (depends on 6.2.2)

---

## 💾 Files to Create/Modify

### Create
- `src/olav/core/time_estimator.py` - SubAgent timing profiles
- `src/olav/core/risk_analyzer.py` - Risk calculation logic

### Modify  
- `src/olav/agents/orchestrator.py` - Enhanced plan_mode_handler()
- `src/olav/core/dependency.py` - Add consumed_by relationships, critical path
- `tests/e2e/test_plan_command_phase2.py` - Add 16 new RED tests

---

**Version**: Phase 6.2.2 Planning Document  
**Created**: 2026-02-07  
**Status**: Ready for Implementation
