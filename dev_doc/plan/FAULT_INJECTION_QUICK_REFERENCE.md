# 故障注入框架使用指南 - 快速参考

**版本**: v1.0.0 (2026-02-11)  
**目的**: 快速指导如何使用故障注入框架验证Expert Agent的诊断能力  
**目标用户**: QA工程师、测试人员、开发人员

---

## 🎯 核心概念

### 三个关键文档

```
│
├─ 📋 FAULT_INJECTION_DETAILED_PROCEDURES.md
│  └─ 手工操作指南 - 包含所有7个故障场景的具体命令
│     • 注入命令 (如何在设备上引入故障)
│     • 验证命令 (如何确认故障存在)
│     • 恢复命令 (如何修复故障)
│     • 期望的诊断输出
│
├─ 🔧 fault_injection.py  
│  └─ 框架代码 - 自动化执行故障注入
│     • FaultScenario: 定义一个故障场景
│     • FaultInjector: 执行注入/验证/恢复
│     • FaultScenarioRegistry: 管理所有场景
│
└─ 💻 fault_injection_examples.py
   └─ 使用示例 - 展示如何集成测试
      • Example1: 运行单个场景
      • Example2: 批量运行所有场景
      • Example3: 创建自定义场景
      • Example4: 按类别/严重度过滤
```

---

## 📊 7个故障场景速查表

| # | 名称 | 难度 | 注入时间 | 故障设备 | 验证命令 |
|---|------|------|---------|---------|---------|
| **1** | BGP邻接-接口Down | 简单 | 30s | R1 Gi1 | `show int Gi1` |
| **2** | BGP邻接-配置错 | 中等 | 60s | R1 BGP AS | `show run \| i bgp` |
| **3** | OSPF邻接-参数不匹 | 中等 | 60s | R1 Gi1 hello | `show ip ospf int` |
| **4** | 接口CRC错误 | 复杂 | 90s | R1-R2 物理 | `show int Gi1 \| i CRC` |
| **5** | BGP网络错 | 复杂 | 60s | R2 network | `show ip bgp` |
| **6** | BGP下一跳坏 | 复杂 | 90s | R4 route-map | `show ip bgp neighbors` |
| **7** | OSPF成本错 | 复杂 | 60s | R2 Gi1成本 | `show ip ospf int \| i Cost` |

---

## 🚀 快速开始 (5分钟)

### 方式A: 手工执行场景1

```bash
# Step 1: SSH到R1
ssh admin@R1

# Step 2: 注入故障 (关闭接口)
configure terminal
interface GigabitEthernet1
 shutdown
exit

# Step 3: 验证故障 (查看接口状态)
show interface GigabitEthernet1
# 期望输出: "GigabitEthernet1 is administratively down"

show ip bgp summary
# 期望输出: 邻接10.1.12.2消失

# Step 4: 运行Expert Agent诊断
# 在另一个终端:
olav ask "R1和R2之间的BGP邻接中断了，请诊断"

# Step 5: 恢复故障
configure terminal
interface GigabitEthernet1
 no shutdown
exit

# Step 6: 验证恢复
show interface GigabitEthernet1
show ip bgp summary
# 期望: 邻接恢复到Established
```

### 方式B: 代码执行 (自动化)

```python
import asyncio
from olav.testing.fault_injection import (
    FaultScenarioRegistry, 
    FaultInjectionTestHarness
)

async def test_bgp_scenario():
    # 获取预定义的场景1
    scenario = FaultScenarioRegistry.get_scenario(1)
    
    # 创建测试工具
    harness = FaultInjectionTestHarness(scenario)
    
    # 执行完整周期: 注入 → 验证 → 诊断 → 恢复 → 验证
    report = await harness.run_complete_test_cycle()
    
    # 生成报告
    print(harness.generate_report())
    
    # 检查结果
    assert report['status'] == 'completed_successfully'
    assert harness.diagnosis_result.confidence_score >= 0.95

# 运行测试
asyncio.run(test_bgp_scenario())
```

---

## 📋 各个场景的关键信息

### ✅ 场景1: BGP接口Down (推荐首先测试)

**难度**: ⭐ (简单)  
**对幻觉的抵抗力**: ⭐⭐⭐⭐⭐ (最强)  
**诊断准确度**: 95%+  
**执行时间**: 2-3分钟

**为什么选这个首先测试**:
- 故障症状非常明确 (接口UP/DOWN是二进制的)
- 诊断逻辑简单且准确
- 验证快速有效
- 完美验证基础诊断框架

**关键命令**:
```bash
# 注入
configure terminal
interface GigabitEthernet1
 shutdown
exit

# 验证
show interface GigabitEthernet1 | i "up, line"
show ip bgp summary | i "10.1.12"

# 恢复
configure terminal
interface GigabitEthernet1
 no shutdown
exit
```

---

### ⚠️ 场景2: BGP AS配置错 (最易幻觉的)

**难度**: ⭐⭐ (中等)  
**对幻觉的抵抗力**: ⭐⭐⭐⭐ (强)  
**诊断准确度**: 93%+  
**执行时间**: 3-4分钟

**容易幻觉的点**:
```
❌ 错: "可能AS号配置有问题"
❌ 错: "可能是BGP发言者问题"
❌ 错: "也许需要重启进程"

✅ 正: "neighbor 3.3.3.3 remote-as 配置为65001，
         但应为65000。AS号不匹配。"
```

**关键命令**:
```bash
# 注入
configure terminal
router bgp 65000
 neighbor 3.3.3.3 remote-as 65001
exit

# 验证
show run | i "neighbor 3.3.3.3"
show ip bgp neighbors 3.3.3.3 | i "BGP state"

# 恢复
configure terminal
router bgp 65000
 neighbor 3.3.3.3 remote-as 65000
exit
```

---

### ⚠️ 场景3: OSPF参数不匹配 (中等幻觉风险)

**难度**: ⭐⭐ (中等)  
**对幻觉的抵抗力**: ⭐⭐⭐⭐ (强)  
**诊断准确度**: 88%+

**关键命令**:
```bash
# 注入
configure terminal
interface GigabitEthernet1
 ip ospf hello-interval 20
exit

# 验证
show ip ospf interface Gi1 | i "hello"
show ip ospf neighbor detail | i "State"

# 恢复
configure terminal
interface GigabitEthernet1
 no ip ospf hello-interval
exit
```

---

### 🔴 场景4-7: 复杂场景 (高幻觉风险)

这些场景涉及多个可能的根因，LLM更容易产生幻觉：

**场景4: CRC错误**
- ⚠️ 风险: 可能有多个硬件故障原因
- ✅ 对策: 使用约束系统排除模糊答案

**场景5: BGP网络错**
- ⚠️ 风险: 隐含的路由学习问题
- ✅ 对策: 验证系统检查路由可达性

**场景6: BGP下一跳错**
- ⚠️ 风险: 需要理解路由传播
- ✅ 对策: 要求具体的下一跳地址

**场景7: OSPF成本错**
- ⚠️ 风险: 可能涉及多条路由
- ✅ 对策: 限制成本值范围

---

## 🛠 为Expert Agent增加新场景

### 步骤1: 定义场景

```python
from olav.testing.fault_injection import (
    FaultScenarioBuilder,
    FaultCategory,
    FaultSeverity,
    FaultStep,
    FaultCommand,
)

# 创建新场景
new_scenario = (
    FaultScenarioBuilder(8, "My New Fault")
    .with_description("Description of the fault")
    .with_category(FaultCategory.BGP)
    .with_severity(FaultSeverity.MEDIUM)
    .with_devices("R1", "R2")
    .with_root_cause("Root cause description")
    
    # 添加注入步骤
    .add_injection_step(FaultStep(
        name="Step name",
        commands=[
            FaultCommand("command 1", "device"),
            FaultCommand("command 2", "device"),
        ],
        verification_commands=[
            FaultCommand("verify command", "device")
        ],
        expected_pattern=r"expected output"
    ))
    
    # 添加验证步骤
    .add_verification_step(FaultStep(
        name="Verify fault",
        commands=[FaultCommand("show ...", "device")]
    ))
    
    # 添加恢复步骤
    .add_recovery_step(FaultStep(
        name="Recover",
        commands=[FaultCommand("fix command", "device")]
    ))
    
    .with_expected_diagnosis("Expected diagnosis text")
    .with_confidence_threshold(0.85)
    .build()
)
```

### 步骤2: 注册场景

```python
from olav.testing.fault_injection import FaultScenarioRegistry

FaultScenarioRegistry.register_scenario(new_scenario)
```

### 步骤3: 使用场景

```python
# 检索并运行
scenario = FaultScenarioRegistry.get_scenario(8)
harness = FaultInjectionTestHarness(scenario)
await harness.run_complete_test_cycle()
```

---

## 📊 测试结果解读

### 完整测试报告含高什么？

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ FAULT INJECTION TEST REPORT                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

Overall Status: COMPLETED_SUCCESSFULLY ✓ 
    ↑ 所有阶段都通过

Phase Results:
  • INJECTION....................... ✓ PASS ← 故障成功注入
  • VERIFICATION.................... ✓ PASS ← 故障已确认存在  
  • DIAGNOSIS....................... ✓ PASS ← Expert诊断完成
  • RECOVERY........................ ✓ PASS ← 故障已修复
  • RECOVERY_VERIFICATION.......... ✓ PASS ← 验证恢复完整

DIAGNOSTIC EVALUATION
─────────────────────────────────────────────────────────────────────────────
Root Cause Identified: "Interface administratively shutdown on R1 Gi1"
Confidence Score: 95.00% ← 诊断信心度
Minimum Threshold: 90.00%
Score Status: ✓ PASS ← 超过目标

Accuracy: CORRECT ← 与实际根因匹配
Diagnostic Time: 1250ms ← 诊断耗时
Contains Vague Terms: ✓ NO ← 无"也许"、"可能"等模糊词

Suggested Solution Steps: 3
  1. configure terminal
  2. interface GigabitEthernet1
  3. no shutdown
```

### 关键指标解读

| 指标 | 含义 | 合格值 |
|------|------|--------|
| **Overall Status** | 完整流程是否成功 | `COMPLETED_SUCCESSFULLY` |
| **Injection** | 故障是否成功注入 | `✓ PASS` |
| **Verification** | 故障状态是否验证 | `✓ PASS` |
| **Confidence Score** | Expert诊断的信心度 | ≥ 0.80 (≥80%) |
| **Accuracy** | 诊断是否准确 | `CORRECT` 或 `PARTIAL` |
| **Contains Vague Terms** | 是否有模糊语言 | `✓ NO` |
| **Recovery** | 故障是否成功恢复 | `✓ PASS` |

---

## 🔍 故障排查表

### 问题: 诊断准确度低 (Accuracy: INCORRECT)

**可能原因** | 解决方案
---|---
Expert Agent没有学到这个故障类型 | 增加这个故障的训练数据
决策树配置不对 | 检查SKILL_DIAGNOSTIC_WORKFLOW.md中的diagnostic_trees
约束系统过于严格 | 调整SKILL.md中的constraints.confidence.min_threshold
证据收集不足 | 增加required_commands中的诊断命令

### 问题: 信心度过低 (Confidence: 0.50 vs expected 0.90)

**可能原因** | 解决方案
---|---
不足2个证据来源 | 检查constraints.evidence.min_pieces，增加诊断命令数
使用了模糊词汇 | 检查输出是否包含forbidden_terms中的词
RCA逻辑不清晰 | 改进决策树的节点逻辑
解决方案验证不完整 | 增加验证步骤

### 问题: 恢复失败 (Recovery: ✗ FAIL)

**可能原因** | 解决方案
---|---
设备不可达 | 检查网络连接、SSH连接
恢复命令有误 | 手工验证recovery_steps中的命令
配置未持久化 | 确保使用write memory/copy running-config startup-config
依赖关系问题 | 检查recovery_steps的顺序

---

## 📈 验收标准

### 每个故障场景应达成:

```
✓ 注入成功率: 100%
  - 故障必须能成功注入

✓ 诊断准确度:
  - 简单场景 (1-3): ≥90%
  - 复杂场景 (4-7): ≥85%

✓ 信心度:
  - 简单场景: ≥0.90 (90%)
  - 复杂场景: ≥0.80 (80%)

✓ 无模糊语言:
  - 禁止: "可能", "也许", "不确定", "可能是"等
  - 示例: "Interface shutdown" (✓) vs "Interface might be shutdown" (✗)

✓ 恢复成功率: 100%
  - 所有故障必须全部恢复

✓ 诊断时间:
  - 简单场景: <5秒
  - 复杂场景: <30秒
```

---

## 🚦 改进与迭代

### 根据测试结果改进Expert Agent

**周期**: 每完成一个故障场景群组，更新Expert Agent

```
Test Cycle 1: 场景1-3 (简单场景)
├─ 诊断准确度 < 90%?
│  └─ 改进 decision_trees 或 required_commands
├─ 信心度 < 0.90?
│  └─ 调整 ExpertConstraints 中的阈值
└─ 包含模糊词汇?
   └─ 添加到 constraints.specificity.forbidden_terms

Test Cycle 2: 场景4-7 (复杂场景)
├─ 诊断准确度 < 85%?
│  └─ 加强 verification_rules 或改进 decision_trees
├─ 幻觉率 > 5%?
│  └─ 增加约束规则或提高confidence阈值
└─ 恢复失败?
   └─ 验证recovery_steps命令的正确性
```

### 改进优先级

1. **必须解决** ❌ (阻挡发布)
   - 恢复失败
   - >50% 的诊断不准确
   - 幻觉率 >10%

2. **应该改进** ⚠️ (下个版本)
   - 诊断准确度 < 85%
   - 信心度 < 0.80
   - 诊断时间 > 10秒

3. **可以优化** 💡 (技术债)
   - 轻微幻觉 (<5%)
   - 诊断时间 > 5秒但 < 10秒
   - 冗余的诊断步骤

---

## 📚 完整文档导航

```
一站式学习路径:

Day 1: 手工执行 (30分钟)
├─ 读: FAULT_INJECTION_DETAILED_PROCEDURES.md
├─ 做: 手工执行场景1 (BGP接口Down)
└─ 结果: 理解故障症状和恢复过程

Day 2: 写代码集成 (1小时)
├─ 读: fault_injection.py 代码框架
├─ 读: fault_injection_examples.py 示例
├─ 做: 运行 Example 1
└─ 结果: 理解自动化框架

Day 3: 完整测试 (2小时)
├─ 做: 运行 Example 2 (所有场景)
├─ 看: 测试报告和结果
├─ 调: 改进低准确度的场景
└─ 结果: Expert Agent通过所有测试

Day 4-5: 扩展和维护
├─ 做: 添加新场景 (Example 3)
├─ 做: 按类别过滤 (Example 4)
├─ 维护: 定期运行回归测试
└─ 学习: 从诊断失败中改进
```

---

## ✅ 检查列表

在启动完整的故障注入测试之前:

```
□ 网络拓扑正确配置 (R1-R4, SW1-SW2 都可达)
□ 设备快照已更新 (exports/snapshots/latest/)
□ SSH访问已配置 (admin用户、密钥/密码)
□ Expert Agent框架已部署 (expert_diagnostician.py)
□ SKILL配置已加载 (SKILL_DIAGNOSTIC_WORKFLOW.md)
□ 故障注入框架已安装 (fault_injection.py)
□ 测试工具已配置 (fault_injection_examples.py)
□ 日志级别已设置 (INFO or DEBUG)
□ 恢复命令已验证 (手工测试过)
□ 基线性能已记录 (了解正常诊断时间)
□ 报告存储路径已创建 (exports/test-reports/)
```

---

**更新日期**: 2026-02-11  
**维护者**: Network AI Team  
**反馈**: 报告问题或改进建议到项目仓库
