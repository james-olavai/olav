# Expert Orchestrator - 快速参考指南

**版本**: v1.0.0 (Task 6 完成)  
**更新时间**: 2026-02-11  
**目的**: 中央协调诊断验证流程

---

## 🎯 核心概念（5分钟）

### Orchestrator 职责

```
Expert Agent Diagnosis
         ↓
    [Orchestrator]
         ↓
  ┌─────────────────┐
  │ Constraint      │ → 检测幻觉 (Task 4)
  │ Validation      │   打分: 0.0-1.0
  │ (REQUIRED)      │   结果: PASS/WARN/FAIL
  └─────────────────┘
         ↓
  ┌─────────────────┐
  │ Accuracy        │ → 对比实际 (Task 5, 可选)
  │ Verification    │   打分: 0.0-1.0
  │ (OPTIONAL)      │   对比: Ground Truth
  └─────────────────┘
         ↓
  ┌─────────────────┐
  │ Decision Gate   │ → 最终决策
  │ Apply Rules     │   ACCEPT / REVIEW / REJECT / UNCERTAIN
  └─────────────────┘
         ↓
  ┌─────────────────┐
  │ Route Decision  │ → 路由目标
  │ (Human/Queue)   │   DIRECT_USER / REVIEW_QUEUE / ESCALATION
  └─────────────────┘
```

### 4个核心决策

| 决策 | 含义 | 约束分数 | 信心分数 | 路由目标 |
|------|------|---------|---------|---------|
| **ACCEPT** | 通过所有检查，可直接返回 | ≥ 0.85 | ≥ 0.80 | DIRECT_USER |
| **REVIEW** | 警告级问题，需人工审查 | 0.70-0.85 | ≥ 0.80 | HUMAN_REVIEW_QUEUE |
| **REJECT** | 关键问题，拒绝诊断 | < 0.70 | 任意 | ESCALATION_QUEUE |
| **UNCERTAIN** | 信心低，需重新分析 | 任意 | < 0.80 | REANALYSIS_QUEUE |

---

## 🚀 5分钟快速开始

### 安装 & 导入

```python
from olav.orchestrator import ExpertOrchestrator, DecisionGateConfig
from olav.testing.expert_constraints import (
    ExpertConstraintsValidator,
    ExpertDiagnosisOutput,
)
```

### 最简单使用方式

```python
import asyncio

async def main():
    # 1. 创建 orchestrator
    orchestrator = ExpertOrchestrator(
        constraint_validator=ExpertConstraintsValidator()
    )
    
    # 2. 创建诊断
    diagnosis = ExpertDiagnosisOutput(
        scenario_id="issue_1",
        root_cause="BGP session down due to TCP connection timeout",
        confidence_score=0.92,  # Expert Agent 的信心
        solution="Restart BGP daemon and verify TCP port 179",
        recovery_commands=["service bgp restart"],
        verification_steps=["show ip bgp neighbor"],
        evidence="BGP state ESTABLISHED → IDLE",
        diagnostic_reasoning="TCP timeout indicates connectivity issue"
    )
    
    # 3. 处理
    report = await orchestrator.process(diagnosis)
    
    # 4. 查看结果
    print(report.summary())
    print(f"Decision: {report.overall_decision.value}")
    print(f"Routing: {report.routing_decision.target.value}")

asyncio.run(main())
```

### 输出示例

```
═══════════════════════════════════════════════════════
ORCHESTRATOR REPORT: issue_1
═══════════════════════════════════════════════════════

Decision:     ACCEPT
Routing:      direct_user
Reason:       Constraint score 0.94 >= 0.85

Constraint Score: 94.00%
Confidence Score: 92.00%

Execution Time: 45.2ms
═══════════════════════════════════════════════════════
```

---

## ⚙️ 决策规则（详细）

### Gate 1: 约束分数（Task 4）

**Pass**: ≥ 0.85
- ✅ 完整诊断（5个必填字段都有）
- ✅ 没有幻觉（没有模糊词汇）
- ✅ 信心分数有效（0.0-1.0）
- ✅ RCA 完整（10+ 词，具体）
- ✅ 解决方案可行（有恢复命令）

**Warning**: 0.70-0.85
- ⚠️ 有轻微问题（如几个模糊词汇）
- ⚠️ RCA 不够详细
- ⚠️ 解决方案缺少验证步骤

**Fail**: < 0.70
- ❌ 检测到幻觉（impossible 命令、contradictions）
- ❌ 关键字段缺失
- ❌ 高度模糊内容（> 5% 模糊词汇）

### Gate 2: 信心分数（Expert Agent）

**Pass**: ≥ 0.80
- Expert Agent 自己对诊断有信心

**Fail**: < 0.80
- Return to Expert Agent for re-analysis

### Gate 3: 准确分数（Task 5, 可选）

**Pass**: ≥ 0.80
- 诊断与 ground truth 匹配 ≥ 80%

**Fail**: < 0.80
- Needs human review

### Gate 4: 混合分数（可选）

If 已配置混合门：
```
hybrid_score = 0.60 * constraint_score + 0.40 * accuracy_score
```

需要 ≥ 0.85 才能 ACCEPT

---

## 📊 如何解读报告

### OrchestratorReport 结构

```python
report = await orchestrator.process(diagnosis)

# 关键属性
report.overall_decision          # ACCEPT / REVIEW / REJECT / UNCERTAIN
report.routing_decision          # RouteDecision (target, reason)
report.constraint_score          # 0.0-1.0 (from Task 4)
report.accuracy_score            # 0.0-1.0 (from Task 5, optional)
report.hybrid_score              # 0.0-1.0 (combined score)
report.confidence_score          # 0.0-1.0 (from diagnosis)

# 问题列表
report.critical_failures         # List[str] (阻止性问题)
report.warnings                  # List[str] (警告性问题)
report.improvement_suggestions   # List[str] (改进建议)

# 详细报告
report.constraint_report         # ValidationReport (Task 4 详情)
report.verification_report       # VerificationReport (Task 5 详情, optional)

# 时间统计
report.total_execution_time_ms   # 处理耗时 (毫秒)
```

### 示例：解读 REVIEW 决策

```
Decision:     REVIEW
Routing:      human_review_queue
Reason:       Constraint score 0.78 in warning range

Constraint Score: 78.00%        ← 低于 Pass 阈值 0.85
Confidence Score: 85.00%        ← OK

⚠️  WARNINGS (2):
   - HallucinationDetector: Found 2 vague terms (也许, 可能)
   - RCACompleteness: RCA only 8 words, need 10+

💡 SUGGESTIONS (2):
   - Add more specific technical details to root cause
   - Expand RCA with network context and troubleshooting steps
```

**解读**:
1. 诊断基本 OK，但有轻微问题
2. 发现了模糊词汇（"也许", "可能"）
3. RCA 太短，需要更详细
4. 需要人工审查，但不是吓人的问题
5. 改进建议很具体

---

## 🔄 3种常见工作流

### 工作流 1: 简单诊断（无 Ground Truth）

```python
# 场景: 实时诊断，没有预期答案
orchestrator = ExpertOrchestrator(
    constraint_validator=validator
    # 注意: 没有 verifier！
)

report = await orchestrator.process(diagnosis)

# 决策基于:
# - Task 4 约束检查 (REQUIRED)
# - Expert Agent 信心分数 (REQUIRED)
# - Task 5 验证 (SKIPPED - 没有 ground truth)
```

### 工作流 2: 验证诊断（有 Ground Truth）

```python
# 场景: 测试 Expert Agent，有预期答案
ground_truth = GroundTruth(
    scenario_id="issue_1",
    expected_root_cause="BGP session down",
    expected_recovery_commands=["service bgp restart"],
    # ...
)

orchestrator = ExpertOrchestrator(
    constraint_validator=validator,
    verifier=verifier  # 注意: 有 verifier
)

report = await orchestrator.process(
    diagnosis,
    ground_truth=ground_truth  # 提供 ground truth
)

# 决策基于:
# - Task 4 约束检查 (REQUIRED)
# - Expert Agent 信心分数 (REQUIRED)
# - Task 5 验证 (INCLUDED - 有 ground truth)
# - 混合分数 (0.60*constraint + 0.40*accuracy)
```

### 工作流 3: 批量处理（多个诊断）

```python
# 场景: 测试 Expert Agent 质量，评估 pass/reject 比例
diagnoses = [diagnosis_1, diagnosis_2, diagnosis_3, ...]
ground_truths = {
    "issue_1": ground_truth_1,
    "issue_2": ground_truth_2,
    # ...
}

reports = await orchestrator.process_batch(
    diagnoses,
    ground_truths=ground_truths
)

# 返回: Dict[scenario_id] → OrchestratorReport

# 分析:
pass_count = sum(1 for r in reports.values() 
                 if r.overall_decision == OrchestratorDecision.ACCEPT)
pass_rate = 100 * pass_count / len(reports)
print(f"Pass Rate: {pass_rate:.1f}%")
```

---

## ⚙️ 自定义配置

### 修改接受标准

```python
# 默认配置
config = DecisionGateConfig()
# constraint_pass_threshold = 0.85
# confidence_pass_threshold = 0.80
# accuracy_pass_threshold = 0.80

# 更严格配置（生产环境）
strict_config = DecisionGateConfig(
    constraint_pass_threshold=0.90,  # 提高标准
    confidence_pass_threshold=0.85,
    accuracy_pass_threshold=0.85,
)

orchestrator = ExpertOrchestrator(
    constraint_validator=validator,
    gate_config=strict_config
)

# 更宽松配置（开发环境）
loose_config = DecisionGateConfig(
    constraint_pass_threshold=0.75,
    confidence_pass_threshold=0.70,
)

orchestrator = ExpertOrchestrator(
    constraint_validator=validator,
    gate_config=loose_config
)
```

### 混合 vs. 单一评分

```python
# 默认: 混合评分 (constraint + accuracy)
config = DecisionGateConfig(
    hybrid_gate_enabled=True,           # 启用混合
    hybrid_weight_constraint=0.60,      # 60% 约束
    hybrid_weight_accuracy=0.40,        # 40% 准确性
)

# 仅约束评分 (不需要 ground truth)
config = DecisionGateConfig(
    hybrid_gate_enabled=False,
)
```

---

## 📁 文件和目录

```
src/olav/orchestrator/
├── __init__.py                    # 包导出
├── expert_orchestrator.py         # 核心实现 (800+ 行代码)
├── examples.py                    # 7个完整工作示例 (500+ 行)
└── (integration tests - coming soon)

docs/plan/
├── TASK_6_ORCHESTRATOR_PLAN.md    # 完整实现计划
├── TASK_6_QUICK_REFERENCE.md      # 这个文件
└── 00_TASK_6_INDEX.md             # 导航索引
```

---

## 🧪 测试 Orchestrator

### Example 1: ACCEPT (接受)

```bash
python -m olav.orchestrator.examples
# ... 输出 Example 1 报告 ...
# Decision: ACCEPT
# Routing: direct_user
```

### Example 2: REVIEW (审查)

```bash
# ... Example 2 输出 ...
# Decision: REVIEW
# Routing: human_review_queue
```

### Example 3: REJECT (拒绝)

```bash
# ... Example 3 输出 ...
# Decision: REJECT
# Routing: escalation_queue
```

### 运行所有7个示例

```bash
python -c "
import asyncio
from olav.orchestrator.examples import OrchestratorExamples
asyncio.run(OrchestratorExamples.run_all_examples())
"
```

---

## 🎓 常见问题

### Q1: ACCEPT vs. REVIEW 的区别？

| 方面 | ACCEPT | REVIEW |
|------|--------|--------|
| 约束分数 | ≥ 0.85 | 0.70-0.85 |
| 行动 | 直接返回用户 | 队列等待人工审查 |
| 时间 | 立即 | < 1 分钟（人工处理） |
| 风险 | 低 | 中等 |
| 用例 | 高质量诊断 | 有轻微问题 |

### Q2: 什么是 Ground Truth？

Ground Truth 是**预期答案**。用于测试 Expert Agent：

```python
ground_truth = GroundTruth(
    scenario_id="scenario_1",
    expected_root_cause="BGP session down",
    expected_solution="Restart BGP",
    expected_recovery_commands=["service bgp restart"],
    expected_verification_steps=["show ip bgp"],
)
```

Expert Agent 诊断与 ground truth 对比，计算准确分数。

### Q3: 我需要 Task 5 (Verifier) 吗？

**不需要**：
- 只要 Orchestrator + Task 4 (Constraints)
- 用于简单的实时诊断验证
- 基于约束和信心分数决策

**推荐**：
- 如果有 ground truth（测试场景）
- 想要更精确的准确率计算
- 需要与预期答案对比

### Q4: 如何保存报告？

```python
report = await orchestrator.process(diagnosis)

# 方式 1: 打印
print(report.summary())

# 方式 2: JSON 导出
json_str = report.to_json()

# 方式 3: 保存到文件
output_path = orchestrator.save_report(report)
print(f"Saved to: {output_path}")

# 方式 4: 获取 Dictionary
report_dict = report.to_dict()
```

---

## 📈 集成与部署

### 与 Query Guard 集成

```python
# 在 Query Guard 中使用 Orchestrator
class QueryGuard:
    async def route_query(self, user_query: str) -> Any:
        # ... 内容识别 ...
        diagnosis = await expert_agent.diagnose(user_query)
        
        # ← 新增: Orchestrator 验证
        report = await orchestrator.process(diagnosis)
        
        # 根据决策路由
        if report.overall_decision == OrchestratorDecision.ACCEPT:
            return result_to_user(diagnosis)
        elif report.overall_decision == OrchestratorDecision.REVIEW:
            return route_to_human_review_queue(diagnosis)
        else:
            return route_to_escalation(diagnosis)
```

### 与 Query Agent 集成

```python
# Expert Agent 诊断后，自动验证
class QueryAgent:
    async def query(self, user_query: str) -> Any:
        result = await database.query(user_query)
        
        # 如果低信心，调用 Expert Agent
        if confidence_score < 0.8:
            diagnosis = await expert_agent.diagnose(user_query)
            
            # ← 验证
            report = await orchestrator.process(diagnosis)
            
            if report.overall_decision == OrchestratorDecision.ACCEPT:
                # 使用 Expert Agent 诊断
                return diagnosis_result
            else:
                # 返回数据库结果
                return result
        
        return result
```

---

## 🚀 下一步

1. **运行示例** (5 min)
   ```bash
   python -m olav.orchestrator.examples
   ```

2. **理解决策规则** (10 min)
   - 查看"决策规则"部分
   - 对比 4 种决策类型

3. **集成到 Expert Agent** (30 min)
   - 创建 orchestrator 实例
   - 在 Expert Agent 流程中调用 process()

4. **配置生产标准** (10 min)
   - 调整 DecisionGateConfig 为生产环境值
   - 定义人工审查队列

5. **实施反馈循环** (后续)
   - 收集 REVIEW/REJECT 的诊断
   - 返回 Expert Agent 进行改进

---

**本文档版本**: v1.0.0  
**完成日期**: 2026-02-11  
**状态**: ✅ 生产就绪
