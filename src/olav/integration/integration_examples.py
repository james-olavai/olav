# Integration Examples

**版本**: v1.0.0  
**目的**: Expert Agent 集成的完整工作示例  
**包含**: 5个完整场景

---

## Example 1: 简单的单诊断处理

```python
import asyncio
from olav.integration import create_staging_integration
from olav.testing.expert_constraints import ExpertDiagnosisOutput

async def example_single_diagnosis():
    """
    场景: 处理单个Expert Agent诊断
    用途: 实时处理用户查询
    预期: ACCEPT决策，直接返回用户
    """
    
    # 创建集成
    integration = create_staging_integration()
    
    # 模拟Expert Agent输出（高质量诊断）
    diagnosis = ExpertDiagnosisOutput(
        scenario_id="bgp_down_001",
        root_cause="BGP TCP session timeout",
        confidence_score=0.95,
        solution="Restart BGP daemon",
        recovery_commands=[
            "service bgp restart"
        ],
        verification_steps=[
            "show ip bgp neighbor",
            "show ip bgp summary"
        ],
        evidence="BGP neighbor state changed from ESTABLISHED to IDLE",
        diagnostic_reasoning="TCP RST received after 19200s idle timeout"
    )
    
    # 处理诊断
    result = await integration.process_expert_diagnosis(diagnosis)
    
    # 显示结果
    print("\n=== Example 1: 简单诊断 ===")
    print(f"Scenario ID: {diagnosis.scenario_id}")
    print(f"Decision: {result['decision']}")
    print(f"Routing: {result['routing']}")
    print(f"Message: {result['message']}")
    print(f"Constraint Score: {result['report'].constraint_score:.2%}")
    print(f"Confidence Score: {result['report'].confidence_score:.2%}")
    print()
    
    return result

# 输出预期:
# ✅ Decision: accept
# ✅ Routing: direct_user
# ✅ Message: [诊断内容]
```

---

## Example 2: 需要人工审查的边界情况

```python
async def example_boundary_diagnosis():
    """
    场景: 处理置信度不足的诊断
    用途: 验证 REVIEW 路由
    预期: REVIEW决策，加入人工审查队列
    """
    
    integration = create_staging_integration()
    
    # 次优质量诊断：低置信度
    diagnosis = ExpertDiagnosisOutput(
        scenario_id="ospf_flap_002",
        root_cause="OSPF interface cost mismatch or MTU issue",
        confidence_score=0.72,  # ⚠️ 低于阈值
        solution="Check interface MTU and OSPF cost configuration",
        recovery_commands=[
            "show ip ospf interface",
            "show ip ospf neighbor detail"
        ],
        verification_steps=[
            "ping -df with size 1500",
            "show ip ospf neighbor"
        ],
        evidence="Interface flapping, MTU not explicitly confirmed",
        diagnostic_reasoning="Likely MTU issue but not 100% certain"
    )
    
    result = await integration.process_expert_diagnosis(diagnosis)
    
    print("\n=== Example 2: 边界诊断 (REVIEW) ===")
    print(f"Scenario ID: {diagnosis.scenario_id}")
    print(f"Decision: {result['decision']}")
    print(f"Routing: {result['routing']}")
    print(f"Reason: {result['report'].reason}")
    print(f"Constraint Score: {result['report'].constraint_score:.2%}")
    print(f"Confidence: {diagnosis.confidence_score:.2%}")
    print()
    
    return result

# 输出预期:
# ⚠️ Decision: uncertain
# ⚠️ Routing: reanalysis_queue
# Reason: Confidence too low
```

---

## Example 3: 检测到幻觉的诊断

```python
async def example_hallucination_detection():
    """
    场景: 检测并拒绝包含幻觉的诊断
    用途: 验证约束检查能否检测到无意义内容
    预期: REJECT决策，升级处理
    """
    
    integration = create_staging_integration()
    
    # 坏质量诊断：包含幻觉和模糊表述
    diagnosis = ExpertDiagnosisOutput(
        scenario_id="bad_diagnosis_003",
        root_cause="也许是接口被某种神奇的网络精灵附身了",  # 💀 幻觉
        confidence_score=0.88,
        solution="可能需要重启路由器或者进行某些操作",  # 💀 模糊
        recovery_commands=[
            "do something magical",  # 💀 无效命令
            "restart the network spirits"
        ],
        verification_steps=[
            "Pray to the routing gods",  # 💀 无效验证
            "Check if magic worked"
        ],
        evidence="Definitely maybe the issue is here",  # 💀 模糊证据
        diagnostic_reasoning="The routing demons have spoken"  # 💀 幻觉推理
    )
    
    result = await integration.process_expert_diagnosis(diagnosis)
    
    print("\n=== Example 3: 幻觉检测 (REJECT) ===")
    print(f"Scenario ID: {diagnosis.scenario_id}")
    print(f"Decision: {result['decision']}")
    print(f"Routing: {result['routing']}")
    print(f"Critical Failures: {result['report'].critical_failures}")
    print(f"Constraint Score: {result['report'].constraint_score:.2%}")
    print()
    
    return result

# 输出预期:
# ❌ Decision: reject
# ❌ Routing: escalation_queue
# Critical Failures: HallucinationDetected
```

---

## Example 4: 批量质量检查

```python
async def example_batch_quality_check():
    """
    场景: 批量处理多个诊断并生成质量报告
    用途: 定期审查Expert Agent质量
    预期: 显示通过率、审查率、拒绝率
    """
    
    integration = create_staging_integration()
    
    # 创建5个诊断（不同质量）
    diagnoses = [
        # 高质量诊断 → ACCEPT
        ExpertDiagnosisOutput(
            scenario_id="q1_001",
            root_cause="BGP TCP reset",
            confidence_score=0.96,
            solution="Restart BGP daemon",
            recovery_commands=["systemctl restart bgp"],
            verification_steps=["show ip bgp neighbor"],
            evidence="TCP RST packet logged",
            diagnostic_reasoning="Clear reset pattern in logs"
        ),
        
        # 高质量诊断 → ACCEPT
        ExpertDiagnosisOutput(
            scenario_id="q1_002",
            root_cause="OSPF hello timeout",
            confidence_score=0.94,
            solution="Check network connectivity",
            recovery_commands=["ping -c 4 neighbor"],
            verification_steps=["show ip ospf neighbor"],
            evidence="Hello packets stopped",
            diagnostic_reasoning="Standard timeout behavior"
        ),
        
        # 边界诊断 → REVIEW
        ExpertDiagnosisOutput(
            scenario_id="q1_003",
            root_cause="Possible interface MTU mismatch",
            confidence_score=0.75,  # 较低
            solution="Verify MTU settings",
            recovery_commands=["show interface mtu"],
            verification_steps=["ping -df"],
            evidence="Interface flapping observed",
            diagnostic_reasoning="MTU issue suspected but not confirmed"
        ),
        
        # 不完整诊断 → REJECT
        ExpertDiagnosisOutput(
            scenario_id="q1_004",
            root_cause="Network issue",  # 太泛泛
            confidence_score=0.60,  # 很低
            solution="Fix the network",  # 太泛泛
            recovery_commands=["restart network"],  # 太泛泛
            verification_steps=["check"],  # 不完整
            evidence="Something wrong",  # 太泛泛
            diagnostic_reasoning="Unknown problem likely"
        ),
        
        # 好质量诊断 → ACCEPT
        ExpertDiagnosisOutput(
            scenario_id="q1_005",
            root_cause="BGP route flap",
            confidence_score=0.92,
            solution="Enable BGP dampening",
            recovery_commands=["bgp dampening"],
            verification_steps=["show ip bgp"],
            evidence="Route flap detected in BGP log",
            diagnostic_reasoning="Flap damping will stabilize"
        ),
    ]
    
    # 批量处理
    results = await integration.process_batch(diagnoses)
    
    # 获取质量指标
    metrics = integration.get_quality_metrics(results)
    
    # 显示结果
    print("\n=== Example 4: 批量质量检查 ===")
    print(f"总处理数: {metrics['total_processed']}")
    print(f"✅ ACCEPT: {metrics['accept_count']} ({metrics['pass_rate']:.1%})")
    print(f"⚠️  REVIEW: {metrics['review_count']} ({metrics['review_rate']:.1%})")
    print(f"❌ REJECT: {metrics['reject_count']} ({metrics['reject_rate']:.1%})")
    print(f"🔄 UNCERTAIN: {metrics['uncertain_count']} ({metrics['uncertain_rate']:.1%})")
    print(f"平均约束得分: {metrics['avg_constraint_score']:.2%}")
    print(f"平均置信度: {metrics['avg_confidence_score']:.2%}")
    print(f"关键问题: {metrics['critical_issues']}")
    print()
    
    return metrics

# 输出预期:
# 总处理数: 5
# ✅ ACCEPT: 3 (60.0%)
# ⚠️  REVIEW: 1 (20.0%)
# ❌ REJECT: 1 (20.0%)
# 🔄 UNCERTAIN: 0 ( 0.0%)
```

---

## Example 5: 完整的生产工作流

```python
async def example_production_workflow():
    """
    场景: 模拟生产中的完整工作流
    用途: 演示从诊断到队列路由的完整流程
    预期: 处理多个诊断，路由到不同队列
    """
    
    from olav.integration import (
        create_production_integration,
        HumanReviewQueue,
        EscalationQueue
    )
    
    # 创建生产集成和队列
    integration = create_production_integration()
    review_queue = HumanReviewQueue()
    escalation_queue = EscalationQueue()
    
    # 模拟5个诊断
    test_cases = [
        {
            "name": "高质量诊断",
            "diagnosis": ExpertDiagnosisOutput(
                scenario_id="prod_001",
                root_cause="Interface down",
                confidence_score=0.96,
                solution="Bring up interface",
                recovery_commands=["no shutdown"],
                verification_steps=["show interface"],
                evidence="Interface state down",
                diagnostic_reasoning="Clear physical layer issue"
            ),
            "expected": "accept"
        },
        {
            "name": "需审查的诊断",
            "diagnosis": ExpertDiagnosisOutput(
                scenario_id="prod_002",
                root_cause="可能是配置问题",  # 模糊
                confidence_score=0.73,  # 低置信度
                solution="检查配置",
                recovery_commands=["show running"],
                verification_steps=["show interface"],
                evidence="配置可能不正确",
                diagnostic_reasoning="配置问题的可能性"
            ),
            "expected": "review"
        },
        {
            "name": "坏的诊断",
            "diagnosis": ExpertDiagnosisOutput(
                scenario_id="prod_003",
                root_cause="网络精灵附身",  # 幻觉
                confidence_score=0.88,
                solution="念咒语修复",  # 幻觉
                recovery_commands=["magic_command"],
                verification_steps=["pray"],
                evidence="神秘力量作用",  # 幻觉
                diagnostic_reasoning="灵异现象"  # 幻觉
            ),
            "expected": "reject"
        }
    ]
    
    # 处理诊断
    print("\n=== Example 5: 生产工作流 ===")
    print("处理诊断与路由：\n")
    
    for i, case in enumerate(test_cases, 1):
        result = await integration.process_expert_diagnosis(case['diagnosis'])
        decision = result['decision']
        
        print(f"{i}. {case['name']}")
        print(f"   预期: {case['expected']}")
        print(f"   实际: {decision}")
        print(f"   路由: {result['routing']}")
        
        # 根据决策路由
        if decision == 'accept':
            print(f"   ✅ → 直接返回用户")
        elif decision == 'review':
            await review_queue.add_to_queue(result['report'])
            print(f"   ⚠️  → 加入人工审查队列")
        elif decision == 'reject':
            await escalation_queue.add_to_escalation(result['report'])
            print(f"   ❌ → 加入升级队列")
        else:
            print(f"   🔄 → 加入重新分析队列")
        
        print()
    
    # 显示队列状态
    print("=== 队列状态 ===")
    review_stats = review_queue.stats()
    escalation_stats = escalation_queue.stats()
    
    print(f"人工审查队列: {review_stats['pending_review']} 待审")
    print(f"升级队列: {escalation_stats['pending_escalation']} 待处理")
    print()
    
    return {
        'review_queue': review_queue,
        'escalation_queue': escalation_queue
    }

# 输出预期:
# 1. 高质量诊断
#    预期: accept
#    实际: accept
#    路由: direct_user
#    ✅ → 直接返回用户
#
# 2. 需审查的诊断
#    预期: review
#    实际: uncertain (置信度低)
#    路由: reanalysis_queue
#    🔄 → 加入重新分析队列
#
# 3. 坏的诊断
#    预期: reject
#    实际: reject
#    路由: escalation_queue
#    ❌ → 加入升级队列
#
# === 队列状态 ===
# 人工审查队列: 0 待审
# 升级队列: 1 待处理
```

---

## 运行所有示例

```python
async def run_all_examples():
    """运行所有5个集成示例"""
    
    print("="*60)
    print("EXPERT AGENT INTEGRATION EXAMPLES")
    print("="*60)
    
    # Example 1
    result1 = await example_single_diagnosis()
    
    # Example 2
    result2 = await example_boundary_diagnosis()
    
    # Example 3
    result3 = await example_hallucination_detection()
    
    # Example 4
    result4 = await example_batch_quality_check()
    
    # Example 5
    result5 = await example_production_workflow()
    
    print("="*60)
    print("✅ 所有示例执行完成")
    print("="*60)

# 执行
if __name__ == "__main__":
    asyncio.run(run_all_examples())
```

---

## 关键学习要点

### 1. 决策逻辑

| 条件 | 决策 | 路由 | 处理 |
|------|------|------|------|
| 约束≥0.90, 置信度≥0.85 | ACCEPT | direct_user | 直接返回 |
| 约束 0.75-0.90 | REVIEW | human_review_queue | 人工审查 |
| 约束<0.75 或 幻觉 | REJECT | escalation_queue | 升级处理 |
| 置信度<0.80 | UNCERTAIN | reanalysis_queue | 重新分析 |

### 2. 约束检查点

- **HallucinationDetector**: 检测模糊或无意义的内容
- **OutputCompleteness**: 确保所有5字段都有
- **ConfidenceValidator**: 验证置信度分数有效
- **RCACompleteness**: 根本原因必须具体
- **SolutionFeasibility**: 解决方案必须可执行

### 3. 集成模式

| 模式 | 用途 | 场景 |
|------|------|------|
| 单诊断处理 | 实时响应 | 用户查询 |
| 批量处理 | 质量审查 | 定期检查 |
| 带验证 | 准确性评估 | 已知答案的测试 |
| 完整工作流 | 生产部署 | 集成到Query Guard |

---

**版本**: v1.0.0  
**完成日期**: 2026-02-11  
**文件目标**: `/src/olav/integration/examples.py`
