# Expert Agent Integration Guide

**版本**: v1.0.0 (集成部署)  
**日期**: 2026-02-11  
**目的**: 完整的Expert Agent系统集成指南

---

## 📋 集成概览

### 整体架构

```
User Query / Network Issue
        │
        ▼
┌──────────────────────┐
│  Query Guard         │  ← Router (SIMPLE/QUERY/EXPERT/CLI)
│  (Route Decision)    │
└──────────┬───────────┘
           │
     ┌─────▼──────────────┐
     │ Expert Agent       │  ← Task 1-2: Diagnostician
     │ (Diagnosis)        │
     └─────┬──────────────┘
           │
      ┌────▼────────────────────────────────┐
      │ INTEGRATION LAYER (This Guide)      │
      │ QueryGuardIntegration               │
      └────┬────────────────────────────────┘
           │
      ┌────▼────────────────────────────────┐
      │  ORCHESTRATOR (Task 6)               │
      │  1. Task 4: Constraint Validation   │
      │  2. Task 5: Accuracy Verification   │
      │  3. Decision Gates                  │
      │  4. Routing Logic                   │
      └────┬────────────────────────────────┘
           │
    ┌──────┴──────────────────────┐
    │                             │
    ▼                             ▼
ACCEPT (90%)              REVIEW/REJECT (10%)
    │                             │
    ├─ Return to User      ┌──────┼──────┐
    │  (immediate)         │      │      │
    └─> User Response  REVIEW REJECT UNCERTAIN
                      Queue  Queue  Queue
                        │      │      │
                        ▼      ▼      ▼
                      Human  Senior  Re-analysis
                      Review  Team    Expert Agent
```

---

## 🚀 快速开始

### 1. 最简单的集成 (5分钟)

```python
import asyncio
from olav.integration import create_production_integration
from olav.testing.expert_constraints import ExpertDiagnosisOutput

async def main():
    # 1. 创建集成
    integration = create_production_integration()
    
    # 2. 接收Expert Agent诊断
    diagnosis = ExpertDiagnosisOutput(
        scenario_id="issue_1",
        root_cause="BGP session down",
        confidence_score=0.92,
        solution="Restart BGP daemon",
        recovery_commands=["service bgp restart"],
        verification_steps=["show ip bgp neighbor"],
        evidence="BGP state ESTABLISHED → IDLE",
        diagnostic_reasoning="TCP timeout"
    )
    
    # 3. 处理
    result = await integration.process_expert_diagnosis(diagnosis)
    
    # 4. 获取结果
    print(f"Decision: {result['decision']}")
    print(f"Routing: {result['routing']}")
    print(f"Message: {result['message']}")

asyncio.run(main())
```

### 输出

```
Decision: accept
Routing: direct_user
Message: Expert diagnosis: Restart BGP daemon
Recovery: service bgp restart
Verification: show ip bgp neighbor
```

---

## ⚙️ 配置

### 生产环境配置

```python
from olav.integration import create_production_integration

# 严格的生产标准
integration = create_production_integration()

# 配置:
# - constraint_pass_threshold: 0.90 (≥90% 才能 ACCEPT)
# - confidence_threshold: 0.85
# - accuracy_threshold: 0.85

# 预期结果:
# - ACCEPT: 75-85% (高质量诊断)
# - REVIEW: 10-15% (需人工审查)
# - REJECT: 2-5% (关键问题)
# - UNCERTAIN: 2-5% (低信心)
```

### 开发环境配置

```python
from olav.integration import create_development_integration

# 宽松的开发标准
integration = create_development_integration()

# 配置:
# - constraint_pass_threshold: 0.75
# - confidence_threshold: 0.70

# 用于: 测试、调试、原型开发
```

### 自定义配置

```python
from olav.orchestrator import DecisionGateConfig, ExpertOrchestrator
from olav.integration import QueryGuardIntegration
from olav.testing.expert_constraints import ExpertConstraintsValidator

# 创建自定义配置
config = DecisionGateConfig(
    constraint_pass_threshold=0.87,
    confidence_pass_threshold=0.82,
    accuracy_pass_threshold=0.82,
)

# 创建orchestrator
validator = ExpertConstraintsValidator()
orchestrator = ExpertOrchestrator(
    constraint_validator=validator,
    gate_config=config
)

# 创建集成
integration = QueryGuardIntegration(orchestrator)
```

---

## 📊 4种使用模式

### 模式 1: 实时诊断 (Simple Case)

用于: **立即响应用户**

```python
async def handle_user_query(user_query: str) -> str:
    # 无 ground truth (实时场景)
    diagnosis = await expert_agent.diagnose(user_query)
    
    result = await integration.process_expert_diagnosis(
        diagnosis,
        user_id="user_123"
    )
    
    if result['decision'] == 'accept':
        return result['message']  # 直接返回
    else:
        return "Processing... please wait"
```

### 模式 2: 验证诊断 (With Ground Truth)

用于: **测试场景、已知答案**

```python
from olav.testing.diagnosis_verifier import GroundTruth

async def verify_diagnosis(diagnosis, ground_truth):
    result = await integration.process_expert_diagnosis(
        diagnosis,
        ground_truth=ground_truth  # 提供预期答案
    )
    
    report = result['report']
    print(f"Accuracy: {report.accuracy_score:.2%}")
    return result
```

### 模式 3: 批量处理 (Batch Mode)

用于: **批量测试诊断质量**

```python
diagnoses = [d1, d2, d3, d4, d5]

results = await integration.process_batch(diagnoses)

# 获取质量指标
metrics = integration.get_quality_metrics(results)
print(f"Pass Rate: {metrics['pass_rate']:.1%}")
print(f"Review Rate: {metrics['review_rate']:.1%}")
print(f"Reject Rate: {metrics['reject_rate']:.1%}")
```

### 模式 4: 完整工作流 (Full Pipeline)

用于: **集成到Query Guard完整流程**

```python
from olav.integration import ExpertAgentOrchestration

# 1. 创建完整工作流
workflow = ExpertAgentOrchestration(
    expert_agent_diagnose_func=expert_agent.diagnose,
    orchestrator=orchestrator
)

# 2. 从用户查询开始
result = await workflow.diagnose_and_validate(
    user_query="BGP neighbor down on R1",
    user_id="user_123"
)

# 3. 返回结果
if result['decision'] == 'accept':
    return result['message']
else:
    # 路由到队列
    if result['routing'] == 'human_review_queue':
        await review_queue.add_to_queue(result['report'])
```

---

## 🎯 决策和路由映射

### ACCEPT (90%) → DIRECT_USER

```
Criteria:
  ✓ constraint_score >= 0.90 (生产) or 0.85 (默认)
  ✓ confidence_score >= threshold
  ✓ No critical failures

Action: 立即返回到用户
Time: 0-1秒
Example:
  "BGP restart should fix the issue"
  → User gets answer immediately
```

### REVIEW (7%) → HUMAN_REVIEW_QUEUE

```
Criteria:
  ⚠️ constraint_score in warning range
  ⚠️ Accuracy < pass threshold (if available)
  ⚠️ Some issues found but not critical

Action: 加入人工审查队列
Time: 1-30分钟 (人工处理)
Example:
  "Issue might be solved by restarting..."
  → Wait for human expert to verify
```

### REJECT (2%) → ESCALATION_QUEUE

```
Criteria:
  ❌ constraint_score < warning threshold
  ❌ Critical failures detected (hallucinations)
  ❌ Cannot be trusted

Action: 升级处理
Time: Immediate escalation
Example:
  "Possessed by routing demons"
  → Immediately escalated to senior team
```

### UNCERTAIN (1%) → REANALYSIS_QUEUE

```
Criteria:
  ⚠️ confidence_score < threshold
  ⚠️ Expert Agent not confident enough

Action: 返回Expert Agent重新分析
Time: Re-analysis + validation
Example:
  Low confidence → Request more detailed analysis
```

---

## 👥 队列管理

### 人工审查队列

```python
from olav.integration import HumanReviewQueue

# 创建队列
review_queue = HumanReviewQueue(max_queue_size=1000)

# 添加诊断
await review_queue.add_to_queue(report)

# 获取下一个待审查诊断
next_diagnosis = await review_queue.get_next_for_review()

# 标记已审查
await review_queue.mark_reviewed(next_diagnosis, approved=True)

# 获取统计
stats = review_queue.stats()
print(f"Pending review: {stats['pending_review']}")
print(f"Processed: {stats['processed']}")
```

### 升级队列

```python
from olav.integration import EscalationQueue

# 创建队列
escalation_queue = EscalationQueue(max_queue_size=100)

# 添加关键诊断
await escalation_queue.add_to_escalation(report)

# 获取下一个关键诊断
critical_issue = await escalation_queue.get_next_critical()

# 获取统计
stats = escalation_queue.stats()
print(f"Pending escalation: {stats['pending_escalation']}")
```

---

## 📈 质量监控

### 获取质量指标

```python
# 处理一批诊断
results = await integration.process_batch(diagnoses)

# 计算指标
metrics = integration.get_quality_metrics(results)

# 显示指标
print(f"Total Processed: {metrics['total_processed']}")
print(f"Pass Rate: {metrics['pass_rate']:.1%}")
print(f"Review Rate: {metrics['review_rate']:.1%}")
print(f"Reject Rate: {metrics['reject_rate']:.1%}")
print(f"Avg Constraint: {metrics['avg_constraint_score']:.2%}")
print(f"Avg Confidence: {metrics['avg_confidence_score']:.2%}")
print(f"Critical Issues: {metrics['critical_issues']}")
```

### 生成质量报告

```python
metrics = integration.get_quality_metrics(results)

report = f"""
╔════════════════════════════════════════╗
║  QUALITY METRICS DASHBOARD              ║
╠════════════════════════════════════════╣
║ Total Processed:    {metrics['total_processed']:4}                     ║
║ ✅ ACCEPT:          {metrics['accept_count']:4} ({metrics['pass_rate']:5.1%})        ║
║ ⚠️  REVIEW:         {metrics['review_count']:4} ({metrics['review_rate']:5.1%})        ║
║ ❌ REJECT:          {metrics['reject_count']:4} ({metrics['reject_rate']:5.1%})        ║
║ 🔄 UNCERTAIN:       {metrics['uncertain_count']:4} ({metrics['uncertain_rate']:5.1%})        ║
╠════════════════════════════════════════╣
║ Avg Constraint Score: {metrics['avg_constraint_score']:.2%}          ║
║ Avg Confidence Score: {metrics['avg_confidence_score']:.2%}          ║
║ Critical Issues:      {metrics['critical_issues']:4}                     ║
╚════════════════════════════════════════╝
"""

print(report)
```

---

## 🔗 与Query Guard的集成

### 集成点 1: Expert Agent后

```python
class QueryGuard:
    async def route_query(self, user_query: str) -> dict:
        # 路由决策
        if is_expert_query(user_query):
            # ← 关键集成点
            diagnosis = await expert_agent.diagnose(user_query)
            result = await integration.process_expert_diagnosis(diagnosis)
            
            # 根据决策路由
            if result['decision'] == 'accept':
                return format_response(diagnosis)
            else:
                return queue_for_review(result)
        
        return route_to_other_agent(user_query)
```

### 集成点 2: 批量质量检查

```python
async def check_expert_agent_quality():
    # 在7个测试场景上运行
    test_scenarios = get_fault_scenarios()
    
    diagnoses = []
    for scenario in test_scenarios:
        diagnosis = await expert_agent.diagnose(scenario.query)
        diagnoses.append(diagnosis)
    
    # 批量验证
    results = await integration.process_batch(
        diagnoses,
        scenario_ids=[s.id for s in test_scenarios],
        ground_truths={s.id: s.ground_truth for s in test_scenarios}
    )
    
    # 显示质量
    metrics = integration.get_quality_metrics(results)
    
    if metrics['pass_rate'] < 0.75:
        alert_poor_quality(metrics)
    else:
        log_quality_improvement(metrics)
```

### 集成点 3: 持续监控

```python
class QualityMonitor:
    async def monitor_expert_agent(self):
        while True:
            # 每小时检查一次质量
            recent_diagnoses = get_recent_diagnoses(hours=1)
            
            results = await integration.process_batch(recent_diagnoses)
            metrics = integration.get_quality_metrics(results)
            
            # 记录指标
            log_metrics(metrics)
            
            # 警报
            if metrics['reject_rate'] > 0.05:  # > 5% reject
                send_alert(
                    f"Expert Agent quality degrading: "
                    f"{metrics['reject_rate']:.1%} reject rate"
                )
            
            await asyncio.sleep(3600)  # 1小时
```

---

## 🧪 完整集成示例

### 完整的Query Guard集成

```python
import asyncio
from olav.integration import (
    create_production_integration,
    HumanReviewQueue,
    EscalationQueue
)

class ProductionQueryGuard:
    def __init__(self):
        self.integration = create_production_integration()
        self.review_queue = HumanReviewQueue()
        self.escalation_queue = EscalationQueue()
    
    async def process_query(self, user_query: str, user_id: str) -> dict:
        """处理用户查询的完整流程"""
        
        # 1. Expert Agent 诊断
        diagnosis = await expert_agent.diagnose(user_query)
        
        # 2. Orchestrator 验证
        result = await self.integration.process_expert_diagnosis(
            diagnosis,
            user_id=user_id,
            scenario_id=diagnosis.scenario_id
        )
        
        # 3. 根据决策执行操作
        decision = result['decision']
        
        if decision == 'accept':
            # 直接返回用户
            return {
                'status': 'success',
                'message': result['message'],
                'confidence': diagnosis.confidence_score
            }
        
        elif decision == 'review':
            # 加入审查队列
            await self.review_queue.add_to_queue(result['report'])
            return {
                'status': 'pending_review',
                'message': result['message'],
                'queue_position': self.review_queue.queue_size()
            }
        
        elif decision == 'reject':
            # 升级处理
            await self.escalation_queue.add_to_escalation(result['report'])
            return {
                'status': 'escalated',
                'message': result['message'],
                'critical_issues': result['report'].critical_failures
            }
        
        else:  # uncertain
            # 返回重新分析
            return {
                'status': 'reanalyzing',
                'message': result['message'],
                'reason': result['report'].reason
            }

# 使用
guard = ProductionQueryGuard()
result = await guard.process_query(
    "BGP neighbor down on R1",
    user_id="user_123"
)
print(result)
```

---

## 📊 监控和报告

### 实时仪表板

```python
class RealTimeDashboard:
    async def display_metrics(self):
        while True:
            print("\n" + "="*50)
            print("EXPERT AGENT QUALITY DASHBOARD")
            print("="*50 + "\n")
            
            # 获取最近诊断
            recent = get_recent_diagnoses(hours=1)
            results = await integration.process_batch(recent)
            metrics = integration.get_quality_metrics(results)
            
            # 显示指标
            print(f"📊 Last Hour Metrics:")
            print(f"  Total: {metrics['total_processed']}")
            print(f"  ✅ Accept:   {metrics['accept_count']:3} ({metrics['pass_rate']:5.1%})")
            print(f"  ⚠️  Review:   {metrics['review_count']:3} ({metrics['review_rate']:5.1%})")
            print(f"  ❌ Reject:   {metrics['reject_count']:3} ({metrics['reject_rate']:5.1%})")
            print(f"  🔄 Uncertain: {metrics['uncertain_count']:3} ({metrics['uncertain_rate']:5.1%})")
            
            # 队列状态
            print(f"\n📋 Queues:")
            print(f"  Review Queue: {self.review_queue.queue_size()} pending")
            print(f"  Escalation Queue: {self.escalation_queue.queue_size()} pending")
            
            await asyncio.sleep(60)  # 每分钟更新
```

---

## 🚀 部署检查清单

### 前置条件

- [ ] Expert Agent 已配置并测试 (Task 1-2)
- [ ] Fault Injection 场景可用 (Task 3)
- [ ] Constraint System 已部署 (Task 4)
- [ ] Verifier System 已部署 (Task 5)
- [ ] Orchestrator 已部署 (Task 6)

### 集成部署

- [ ] 创建生产Orchestrator实例
- [ ] 创建QueryGuardIntegration
- [ ] 设置HumanReviewQueue
- [ ] 设置EscalationQueue
- [ ] 配置监控日志
- [ ] 设置质量警报

### 验证

- [ ] 单个诊断处理 ✓
- [ ] 批量处理 ✓
- [ ] ACCEPT 路由 ✓
- [ ] REVIEW 路由 ✓
- [ ] REJECT 路由 ✓
- [ ] UNCERTAIN 路由 ✓
- [ ] 所有决策类型工作正常 ✓

### 性能检查

- [ ] 单诊断 < 100ms
- [ ] 批处理 < 500ms (10诊断)
- [ ] 内存稳定，无泄漏
- [ ] 并发支持 10+ 诊断

---

## 📞 常见问题

### Q1: 什么时候使用 create_production_integration?

**A**: 生产环境部署。使用严格的质量标准（constraint >= 0.90），以确保只有最高质量的诊断直接返回用户。

### Q2: 我可以自定义决策门吗?

**A**: 可以。使用 DecisionGateConfig 自定义所有阈值：

```python
config = DecisionGateConfig(
    constraint_pass_threshold=0.85,
    confidence_pass_threshold=0.80,
    accuracy_pass_threshold=0.80
)
```

### Q3: 如何处理人工审查结果?

**A**: 使用 HumanReviewQueue 获取待审查诊断，然后标记为已审查：

```python
next_issue = await review_queue.get_next_for_review()
# 人工审查...
await review_queue.mark_reviewed(next_issue, approved=True)
```

### Q4: 是否需要 ground truth?

**A**: 不需要。没有 ground truth 的话，只使用 Task 4 约束检查。有 ground truth 可以启用 Task 5 验证获得更精确的决策。

---

**文档版本**: v1.0.0  
**完成日期**: 2026-02-11  
**状态**: ✅ 生产就绪
