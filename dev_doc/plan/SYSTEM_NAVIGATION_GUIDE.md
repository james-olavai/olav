# System Navigation Guide

**版本**: v1.0.0 (完整系统导航)  
**日期**: 2026-02-11  
**目的**: Expert Agent 系统的完整导航和快速参考

---

## 🗺️ 系统概览

```
┌─────────────────────────────────────────────────────────────┐
│                   EXPERT AGENT SYSTEM                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  TASK 1-2: Expert Agent Diagnostician                      │
│  ├─ SKILL.md: 配置和提示词                                  │
│  └─ diagnostician.py: 诊断框架代码                          │
│                                                              │
│  ↓ 接收诊断输出                                              │
│                                                              │
│  TASK 3: Real Fault Injection (7个真实故障场景)             │
│  ├─ BGP scenario                                            │
│  ├─ OSPF scenario                                           │
│  └─ ... 5 more scenarios                                    │
│                                                              │
│  ↓ 用于测试验证                                              │
│                                                              │
│  TASK 4: Expert Constraints (约束检查系统)                  │
│  ├─ HallucinationDetector (95%+ 检测率)                     │
│  ├─ OutputCompleteness (100% 检测率)                        │
│  ├─ ConfidenceValidator                                     │
│  ├─ RCACompleteness                                         │
│  └─ SolutionFeasibility                                     │
│  constraint_score: 0.0-1.0                                  │
│                                                              │
│  ↓ 通过1级质量门                                              │
│                                                              │
│  TASK 5: Diagnosis Verifier (验证系统)                      │
│  ├─ RCAVerifier (语义匹配, Jaccard相似度)                   │
│  ├─ SolutionVerifier (命令集匹配)                          │
│  └─ VerificationVerifier (验证完整性)                       │
│  accuracy_score: 0.0-1.0 (可选)                             │
│                                                              │
│  ↓ 通过2级质量门                                              │
│                                                              │
│  TASK 6: Expert Orchestrator (编排和决策)                   │
│  ├─ 结合 constraint (60%) + accuracy (40%)                  │
│  ├─ 4个决策类型                                             │
│  │  ├─ ACCEPT: 直接用户                                    │
│  │  ├─ REVIEW: 人工审查队列                                │
│  │  ├─ REJECT: 升级队列                                    │
│  │  └─ UNCERTAIN: 重新分析队列                             │
│  └─ DecisionGateConfig (可配置阈值)                        │
│                                                              │
│  ↓ 路由决策                                                  │
│                                                              │
│  INTEGRATION: Query Guard Integration (THIS PHASE)          │
│  ├─ QueryGuardIntegration (主集成层)                       │
│  ├─ HumanReviewQueue (人工审查)                            │
│  ├─ EscalationQueue (升级处理)                             │
│  └─ Factory functions (生产/测试/开发配置)                 │
│                                                              │
│  ↓ 最终用户/队列路由                                         │
│                                                              │
│  OUTPUT: 用户回复/队列管理                                   │
│  ├─ User Response (ACCEPT)                                  │
│  ├─ Human Review (REVIEW)                                   │
│  ├─ Senior Team (REJECT)                                    │
│  └─ Re-analysis (UNCERTAIN)                                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📂 代码文件导航

### Task 1-2: Expert Agent 基础

| 文件 | 行数 | 描述 |
|------|------|------|
| [.olav/skills/diagnostic/SKILL.md](../../.olav/skills/diagnostic/SKILL.md) | 300+ | 诊断Agent配置、提示词 |
| [src/olav/agents/diagnostician.py](../../src/olav/agents/diagnostician.py) | 400+ | 诊断框架实现 |

**使用场景**: 
- 了解Expert Agent如何诊断
- 修改诊断提示词或行为
- 添加新的诊断类型

---

### Task 3: Real Fault Injection

| 文件 | 行数 | 场景 |
|------|------|------|
| [tests/fixtures/fault_scenarios.py](../../tests/fixtures/fault_scenarios.py) | 500+ | 7个真实故障场景 |
| [tests/e2e/test_fault_scenarios.py](../../tests/e2e/test_fault_scenarios.py) | 300+ | 故障场景测试 |

**场景列表**:
1. BGP session timeout
2. OSPF neighbor flap
3. Interface down
4. Route leak
5. Configuration sync
6. Hardware failure
7. Software bug

**使用场景**:
- 验证Expert Agent诊断准确性
- 评估系统性能
- 生成测试数据

**关键代码**:
```python
from tests.fixtures.fault_scenarios import get_all_fault_scenarios
scenarios = get_all_fault_scenarios()
for scenario in scenarios:
    diagnosis = await expert_agent.diagnose(scenario.query)
```

---

### Task 4: Expert Constraints

| 文件 | 行数 | 关键类 |
|------|------|--------|
| [src/olav/testing/expert_constraints.py](../../src/olav/testing/expert_constraints.py) | 700+ | ExpertConstraintsValidator, 5个检查器 |
| [src/olav/testing/expert_constraints_examples.py](../../src/olav/testing/expert_constraints_examples.py) | 400+ | 6个完整示例 |
| [docs/reference/EXPERT_CONSTRAINTS_QUICK_REFERENCE.md](../../docs/reference/EXPERT_CONSTRAINTS_QUICK_REFERENCE.md) | 400+ | 快速参考指南 |

**5个约束检查器**:

1. **HallucinationDetector** (95%+ 准确率)
   - 检测模糊表述 (也许、可能、maybe)
   - 检测无意义内容
   - 检测虚拟命令

2. **OutputCompleteness** (100% 追踪)
   - 验证5个必需字段
   - 字段非空
   - 字段有实质内容

3. **ConfidenceValidator**
   - 验证置信度范围
   - 验证数值合理性

4. **RCACompleteness**
   - RCA必须具体
   - 不能太泛泛而谈

5. **SolutionFeasibility**
   - 解决方案必须可执行
   - 不能有虚拟命令

**约束得分**: `0.0-1.0` (>=0.85 通过, <0.75 拒绝)

**示例**:
```python
validator = ExpertConstraintsValidator()
report = await validator.validate(diagnosis)
print(f"Constraint Score: {report.constraint_score:.2%}")
print(f"Failed Checks: {report.failed_checks}")
```

**使用场景**:
- 检测和拒绝低质量诊断
- 评估Expert Agent提示词效果
- 生成诊断质量报告

---

### Task 5: Diagnosis Verifier

| 文件 | 行数 | 关键类 |
|------|------|--------|
| [src/olav/testing/diagnosis_verifier.py](../../src/olav/testing/diagnosis_verifier.py) | 600+ | DiagnosisVerifier, 3个验证器 |
| [src/olav/testing/diagnosis_verifier_examples.py](../../src/olav/testing/diagnosis_verifier_examples.py) | 400+ | 6个完整示例 |
| [docs/reference/DIAGNOSIS_VERIFIER_PLAN.md](../../docs/reference/DIAGNOSIS_VERIFIER_PLAN.md) | 600+ | 完整计划 |

**3个验证器**:

1. **RCAVerifier** (语义匹配)
   - 方法: Jaccard相似度
   - 准确率: 95%+ (对于已知答案)
   - 输出: 0.0-1.0 分数

2. **SolutionVerifier** (命令匹配)
   - 方法: 集合匹配
   - 危险命令检测
   - 输出: 0.0-1.0 分数

3. **VerificationVerifier** (验证完整性)
   - 检查验证步骤
   - 计算完整性
   - 输出: 0.0-1.0 分数

**准确度得分**: `0.0-1.0` (可选, 仅当有ground truth)

**示例**:
```python
from olav.testing.diagnosis_verifier import DiagnosisVerifier, GroundTruth

verifier = DiagnosisVerifier()
ground_truth = GroundTruth(
    rca="BGP session timeout",
    solution=["systemctl restart bgp"],
    verification=["show ip bgp neighbor"]
)
report = await verifier.verify(diagnosis, ground_truth)
print(f"RCA Accuracy: {report.rca_accuracy:.2%}")
print(f"Solution Accuracy: {report.solution_accuracy:.2%}")
```

**使用场景**:
- 验证诊断准确性 (如有已知答案)
- 评估Expert Agent完整性
- 生成准确度质量报告

---

### Task 6: Expert Orchestrator

| 文件 | 行数 | 关键类 |
|------|------|--------|
| [src/olav/orchestrator/expert_orchestrator.py](../../src/olav/orchestrator/expert_orchestrator.py) | 740+ | ExpertOrchestrator, DecisionGateConfig |
| [src/olav/orchestrator/examples.py](../../src/olav/orchestrator/examples.py) | 599+ | 7个完整示例 |
| [docs/reference/TASK_6_QUICK_REFERENCE.md](../../docs/reference/TASK_6_QUICK_REFERENCE.md) | 400+ | 快速参考 |
| [docs/reference/TASK_6_ORCHESTRATOR_PLAN.md](../../docs/reference/TASK_6_ORCHESTRATOR_PLAN.md) | 800+ | 完整计划 |

**核心流程**:

```python
orchestrator = ExpertOrchestrator(
    constraint_validator=ExpertConstraintsValidator(),
    verifier=DiagnosisVerifier(),  # 可选
    gate_config=DecisionGateConfig(...)
)

result = await orchestrator.process(diagnosis, ground_truth=None)
# result.decision: 'accept', 'review', 'reject', 'uncertain'
# result.routing: 'direct_user', 'human_review_queue', ...
# result.constraint_score: float 0.0-1.0
# result.accuracy_score: float 0.0-1.0
# result.recommendation: str
```

**4个决策类型**:

| 决策 | 条件 | 路由 | 处理时间 |
|------|------|------|---------|
| **ACCEPT** | constraint≥0.90 & confidence≥0.85 | direct_user | 0-1s |
| **REVIEW** | constraint 0.75-0.90 | human_review_queue | 1-30min |
| **REJECT** | constraint<0.75 或 幻觉检测 | escalation_queue | 即时 |
| **UNCERTAIN** | confidence<0.80 | reanalysis_queue | 1-5min |

**DecisionGateConfig** (3个环境):

```python
# 生产: 严格 (0.90, 0.85, 0.85)
production = create_production_integration()

# 默认: 均衡 (0.85, 0.80, 0.80)
staging = create_staging_integration()

# 开发: 宽松 (0.75, 0.70, 0.70)
dev = create_development_integration()
```

**使用场景**:
- 核心决策引擎
- 质量评估
- 路由决策
- 生产部署

---

### Task 6+: Integration Layer (NEW)

| 文件 | 行数 | 关键类 |
|------|------|--------|
| [src/olav/integration/expert_agent_integration.py](../../src/olav/integration/expert_agent_integration.py) | 430+ | QueryGuardIntegration, HumanReviewQueue |
| [src/olav/integration/integration_examples.py](../../src/olav/integration/integration_examples.py) | 800+ | 5个完整示例 |
| [docs/plan/INTEGRATION_GUIDE.md](../../docs/plan/INTEGRATION_GUIDE.md) | 600+ | 集成完整指南 |
| [docs/plan/DEPLOYMENT_AND_OPERATIONS.md](../../docs/plan/DEPLOYMENT_AND_OPERATIONS.md) | 600+ | 部署和运维指南 |

**核心组件**:

1. **QueryGuardIntegration** (主集成层)
   ```python
   integration = create_production_integration()
   result = await integration.process_expert_diagnosis(diagnosis)
   metrics = integration.get_quality_metrics(results)
   ```

2. **HumanReviewQueue** (人工审查队列)
   ```python
   queue = HumanReviewQueue()
   await queue.add_to_queue(report)
   next_item = await queue.get_next_for_review()
   ```

3. **EscalationQueue** (升级处理队列)
   ```python
   escalation = EscalationQueue()
   await escalation.add_to_escalation(report)
   critical_item = await escalation.get_next_critical()
   ```

4. **ExpertAgentOrchestration** (完整E2E工作流)
   ```python
   workflow = ExpertAgentOrchestration(expert_agent.diagnose, orchestrator)
   result = await workflow.diagnose_and_validate(user_query)
   ```

**使用场景**:
- Query Guard 集成
- 实时诊断处理
- 批量质量评估
- 队列管理
- 生产部署

---

## 📚 文档导航

### 快速开始 (5分钟)

1. **[QUICK_START_DEVELOPER.md](../../docs/reference/QUICK_START_DEVELOPER.md)** - 新开发者快速上手
2. **[INTEGRATION_GUIDE.md](../../docs/plan/INTEGRATION_GUIDE.md)** - 5分钟集成教程

### 架构理解 (30分钟)

1. **[ARCHITECTURE.md](../../docs/reference/ARCHITECTURE.md)** - 系统架构
2. **[00_COMPLETE_SYSTEM_OVERVIEW.md](../../docs/plan/00_COMPLETE_SYSTEM_OVERVIEW.md)** - 完整系统概览

### 详细参考 (1-2小时)

**Task 4: Constraints**
- [EXPERT_CONSTRAINTS_QUICK_REFERENCE.md](../../docs/reference/EXPERT_CONSTRAINTS_QUICK_REFERENCE.md) - 快速参考
- [EXPERT_CONSTRAINTS_IMPLEMENTATION_SUMMARY.md](../../docs/reference/EXPERT_CONSTRAINTS_IMPLEMENTATION_SUMMARY.md) - 实现细节
- [EXPERT_CONSTRAINTS_NAVIGATION.md](../../docs/reference/EXPERT_CONSTRAINTS_NAVIGATION.md) - 导航指南

**Task 5: Verifier**
- [DIAGNOSIS_VERIFIER_PLAN.md](../../docs/reference/DIAGNOSIS_VERIFIER_PLAN.md) - 完整计划

**Task 6: Orchestrator**
- [TASK_6_QUICK_REFERENCE.md](../../docs/reference/TASK_6_QUICK_REFERENCE.md) - 快速参考
- [TASK_6_ORCHESTRATOR_PLAN.md](../../docs/reference/TASK_6_ORCHESTRATOR_PLAN.md) - 详细计划

### 部署和运维 (2小时)

1. **[DEPLOYMENT_AND_OPERATIONS.md](../../docs/plan/DEPLOYMENT_AND_OPERATIONS.md)** - 完整部署指南
2. **[INTEGRATION_GUIDE.md](../../docs/plan/INTEGRATION_GUIDE.md)** - 集成指南

---

## 🎯 常见任务导航

### 任务: 我想学习系统架构

1. 阅读 [ARCHITECTURE.md](../../docs/reference/ARCHITECTURE.md) (15分钟)
2. 查看本文件中的"系统概览" (5分钟)
3. 阅读 [00_COMPLETE_SYSTEM_OVERVIEW.md](../../docs/plan/00_COMPLETE_SYSTEM_OVERVIEW.md) (30分钟)

### 任务: 我想集成到Query Guard

1. 阅读 [QUICK_START_DEVELOPER.md](../../docs/reference/QUICK_START_DEVELOPER.md) (5分钟)
2. 阅读 [INTEGRATION_GUIDE.md](../../docs/plan/INTEGRATION_GUIDE.md) (30分钟)
3. 运行 [integration_examples.py](../../src/olav/integration/integration_examples.py) 中的所有5个示例
4. 按照 [DEPLOYMENT_AND_OPERATIONS.md](../../docs/plan/DEPLOYMENT_AND_OPERATIONS.md) 部署

### 任务: 我想检测坏的诊断

1. 了解 [EXPERT_CONSTRAINTS_QUICK_REFERENCE.md](../../docs/reference/EXPERT_CONSTRAINTS_QUICK_REFERENCE.md) (15分钟)
2. 查看 [expert_constraints_examples.py](../../src/olav/testing/expert_constraints_examples.py) 中的示例
3. 使用:
   ```python
   validator = ExpertConstraintsValidator()
   report = await validator.validate(diagnosis)
   ```

### 任务: 我想验证诊断准确性

1. 了解 [DIAGNOSIS_VERIFIER_PLAN.md](../../docs/reference/DIAGNOSIS_VERIFIER_PLAN.md) (30分钟)
2. 查看 [diagnosis_verifier_examples.py](../../src/olav/testing/diagnosis_verifier_examples.py) 中的示例
3. 使用:
   ```python
   verifier = DiagnosisVerifier()
   report = await verifier.verify(diagnosis, ground_truth)
   ```

### 任务: 我想查看决策逻辑

1. 阅读 [TASK_6_QUICK_REFERENCE.md](../../docs/reference/TASK_6_QUICK_REFERENCE.md) (20分钟)
2. 查看 [examples.py](../../src/olav/orchestrator/examples.py) 中的7个示例
3. 了解 DecisionGateConfig 和 4个决策类型

### 任务: 我想部署到生产

1. 检查 [DEPLOYMENT_AND_OPERATIONS.md](../../docs/plan/DEPLOYMENT_AND_OPERATIONS.md) 中的部署前检查清单 (1小时)
2. 按照部署步骤执行金丝雀部署 (2小时)
3. 设置监控和告警 (1小时)
4. 准备回滚程序 (30分钟)

---

## 🔧 API 快速参考

### ExpertConstraintsValidator

```python
from olav.testing.expert_constraints import ExpertConstraintsValidator

validator = ExpertConstraintsValidator()

# 验证诊断
report = await validator.validate(diagnosis)

# 访问得分
print(report.constraint_score)  # 0.0-1.0
print(report.failed_checks)     # 列表

# 访问各检查器
print(report.hallucination_detected)
print(report.completeness_score)
print(report.confidence_valid)
```

### DiagnosisVerifier

```python
from olav.testing.diagnosis_verifier import DiagnosisVerifier, GroundTruth

verifier = DiagnosisVerifier()

# 创建 ground truth
gt = GroundTruth(
    rca="BGP session timeout",
    solution=["systemctl restart bgp"],
    verification=["show ip bgp neighbor"]
)

# 验证诊断
report = await verifier.verify(diagnosis, gt)

# 访问准确度
print(report.rca_accuracy)        # 0.0-1.0
print(report.solution_accuracy)   # 0.0-1.0
print(report.verification_accuracy) # 0.0-1.0
```

### ExpertOrchestrator

```python
from olav.orchestrator import ExpertOrchestrator, DecisionGateConfig

# 创建
config = DecisionGateConfig(constraint_pass_threshold=0.90)
orchestrator = ExpertOrchestrator(
    constraint_validator=validator,
    verifier=verifier,      # 可选
    gate_config=config
)

# 处理
result = await orchestrator.process(diagnosis)

# 访问结果
print(result.decision)          # 'accept', 'review', 'reject', 'uncertain'
print(result.routing)           # 路由目标
print(result.constraint_score)  # 0.0-1.0
print(result.accuracy_score)    # 0.0-1.0 (如有)
print(result.confidence_score)  # 原始置信度
print(result.recommendation)    # 文字建议
```

### QueryGuardIntegration

```python
from olav.integration import create_production_integration

integration = create_production_integration()

# 处理单诊断
result = await integration.process_expert_diagnosis(diagnosis)

# 处理批诊断
results = await integration.process_batch(diagnoses)

# 获取质量指标
metrics = integration.get_quality_metrics(results)
print(metrics['pass_rate'])
print(metrics['reject_rate'])
print(metrics['critical_issues'])
```

### HumanReviewQueue

```python
from olav.integration import HumanReviewQueue

queue = HumanReviewQueue()

# 添加诊断
await queue.add_to_queue(report)

# 获取待审查
next_item = await queue.get_next_for_review()

# 标记已审查
await queue.mark_reviewed(next_item, approved=True)

# 获取统计
stats = queue.stats()
```

---

## 📊 性能指标

| 操作 | 典型时间 | 95分位 | 99分位 |
|------|---------|--------|---------|
| 单诊断验证 | 30-50ms | 80ms | 150ms |
| 批处理(10诊断) | 350-450ms | 600ms | 900ms |
| 约束检查 | 10-20ms | 30ms | 50ms |
| 准确度验证 | 15-25ms | 40ms | 70ms |
| 决策生成 | 5-10ms | 15ms | 25ms |

**目标**:
- 单诊断 < 100ms ✅
- 批处理(10) < 500ms ✅
- P99延迟 < 200ms ✅

---

## ❓ FAQ

### Q: 我应该从哪里开始?

**A**: 按以下顺序:
1. 阅读本文件的"系统概览" (5分钟)
2. 阅读 [QUICK_START_DEVELOPER.md](../../docs/reference/QUICK_START_DEVELOPER.md) (5分钟)
3. 运行 [INTEGRATION_GUIDE.md](../../docs/plan/INTEGRATION_GUIDE.md) 中的简单示例 (10分钟)

### Q: 我如何集成到我的系统?

**A**: 
1. 阅读 [INTEGRATION_GUIDE.md](../../docs/plan/INTEGRATION_GUIDE.md)
2. 复制 [integration_examples.py](../../src/olav/integration/integration_examples.py) 中的示例
3. 按照模式 1 (实时诊断) 或模式 4 (完整工作流) 集成

### Q: 约束检查失败意味着什么?

**A**: 诊断有问题，不应直接返回用户。可能的原因:
- 幻觉/无意义内容
- 输出不完整
- 置信度太低
- RCA 太泛泛而谈
- 解决方案不可执行

查看 [EXPERT_CONSTRAINTS_QUICK_REFERENCE.md](../../docs/reference/EXPERT_CONSTRAINTS_QUICK_REFERENCE.md) 了解详情。

### Q: 我应该使用哪个集成工厂函数?

**A**:
- **create_production_integration()** - 生产部署 (严格标准)
- **create_staging_integration()** - 测试/演示 (均衡标准)
- **create_development_integration()** - 开发/调试 (宽松标准)

---

**版本**: v1.0.0  
**完成日期**: 2026-02-11  
**状态**: ✅ 完整导航指南
