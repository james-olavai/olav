# 故障注入框架 - 完整资源索引

**版本**: v1.0.0  
**创建**: 2026-02-11  
**状态**: ✅ 完成并可用

---

## 📚 资源导航地图

```
故障注入框架
│
├─ 📖 【快速入门】
│  │
│  ├─ ⭐ FAULT_INJECTION_QUICK_REFERENCE.md (这里开始!)
│  │  └─ 5分钟快速开始
│  │     • 7个场景速查表
│  │     • 快速开始命令
│  │     • 故障排查指南
│  │
│  └─ 🎯 FAULT_INJECTION_COMPLETION_REPORT.md
│     └─ 本次工作总结
│        • 10个交付物
│        • 立即行动清单
│        • 验收标准
│
├─ 📋 【详细过程】
│  │
│  └─ 📚 FAULT_INJECTION_DETAILED_PROCEDURES.md (30分钟深入)
│     └─ 7个故障场景完整指南
│        • 场景1-3: 简单/中等场景 (推荐首先测试)
│        • 场景4-7: 复杂场景 (涉及多个根因)
│        • 每个场景: 注入→验证→诊断→恢复→验证
│
├─ 🔧 【代码实现】
│  │
│  ├─ 💻 fault_injection.py (1小时深入学习)
│  │  └─ 核心框架代码
│  │     • FaultScenario类: 故障场景定义
│  │     • FaultInjector类: 执行器
│  │     • FaultScenarioRegistry: 场景管理
│  │     • 7个预定义场景
│  │
│  └─ 🏃 fault_injection_examples.py (10分钟快速体验)
│     └─ 4个完整示例
│        • Example1: 单个场景测试
│        • Example2: 批量测试所有场景
│        • Example3: 创建自定义场景
│        • Example4: 按条件过滤场景
│
└─ 📊 【总结与规划】
   │
   ├─ 📈 FAULT_INJECTION_IMPLEMENTATION_SUMMARY.md
   │  └─ 实施总结 (5个因素)
   │     • 与前期工作的关联
   │     • 后续改进方向
   │     • 文件位置地图
   │
   └─ 📍 00_FAULT_INJECTION_INDEX.md (本文件)
      └─ 完整资源导航
```

---

## 🎯 按用户角色快速导航

### 👤 我是新手，第一次接触

**推荐路线** (20分钟):
1. 打开本文件 (2分钟) ← 你在这里
2. 阅读 QUICK_REFERENCE.md (5分钟)
3. 手工执行场景1 (10分钟)
4. 查看结果 (3分钟)

**关键文件**:
- `FAULT_INJECTION_QUICK_REFERENCE.md` ← 开始这里
- `FAULT_INJECTION_DETAILED_PROCEDURES.md` ← 查看场景1

---

### 👨‍💼 我是QA工程师，需要设计测试

**推荐路线** (1小时):
1. 阅读全部4个'quick links'部分
2. 学习 DETAILED_PROCEDURES.md 中的诊断工作流
3. 了解框架代码基本结构
4. 设计测试用例

**关键文件**:
- `FAULT_INJECTION_QUICK_REFERENCE.md` ← 测试设计
- `FAULT_INJECTION_DETAILED_PROCEDURES.md` ← 场景详情
- `fault_injection_examples.py` ← 参考实现

---

### 👨‍💻 我是开发人员，需要集成

**推荐路线** (2小时):
1. 理解整体架构 (IMPLEMENTATION_SUMMARY.md)
2. 学习框架代码 (fault_injection.py)
3. 运行示例 (fault_injection_examples.py)
4. 集成到项目

**关键文件**:
- `fault_injection.py` ← 框架代码
- `fault_injection_examples.py` ← 使用示例
- `FAULT_INJECTION_IMPLEMENTATION_SUMMARY.md` ← 架构图

**集成示例**:
```python
from olav.testing.fault_injection import FaultScenarioRegistry, FaultInjectionTestHarness

async def test_expert_agent():
    scenario = FaultScenarioRegistry.get_scenario(1)
    harness = FaultInjectionTestHarness(scenario)
    report = await harness.run_complete_test_cycle()
    return report
```

---

### 👨‍🔬 我是研究人员，需要分析诊断准确度

**推荐路线** (3小时):
1. 理解诊断框架
2. 分析诊断工作流
3. 运行所有场景
4. 统计分析结果

**关键文件**:
- `FAULT_INJECTION_DETAILED_PROCEDURES.md` ← 诊断工作流
- `fault_injection_examples.py` ← 运行所有场景
- SKILL_DIAGNOSTIC_WORKFLOW.md (sibling) ← 诊断配置

**分析要点**:
- 诊断准确度: 与expected_diagnosis对比
- 信心度: confidence_score值
- 幻觉检查: 输出中是否有模糊词

---

## 📊 7个故障场景速查表

| # | 名称 | 难度 | 诊断时间 | 准确度 | 信心度 | 文件位置 |
|---|------|------|---------|--------|--------|---------|
| **1** | BGP接口Down | ⭐简单 | 30-60s | 95%+ | 0.95 | PROCEDURES.md L1-150 |
| **2** | BGP配置错 | ⭐⭐中等 | 1-2min | 93%+ | 0.93 | PROCEDURES.md L151-320 |
| **3** | OSPF参数不匹 | ⭐⭐中等 | 1-2min | 88%+ | 0.88 | PROCEDURES.md L321-450 |
| **4** | CRC错误激增 | ⭐⭐⭐复杂 | 2-3min | 82%+ | 0.82 | PROCEDURES.md L451-600 |
| **5** | BGP网络错 | ⭐⭐⭐复杂 | 2-3min | 85%+ | 0.85 | PROCEDURES.md L601-750 |
| **6** | BGP下一跳坏 | ⭐⭐⭐复杂 | 3-5min | 80%+ | 0.80 | PROCEDURES.md L751-900 |
| **7** | OSPF成本错 | ⭐⭐⭐复杂 | 3-5min | 92%+ | 0.92 | PROCEDURES.md L901-1050 |

---

## 🚀 快速命令

### 手工执行场景1 (5分钟)
```bash
# 1. SSH到R1
ssh admin@R1

# 2. 注入故障
configure terminal
interface GigabitEthernet1
 shutdown
exit

# 3. 验证故障
show interface GigabitEthernet1
show ip bgp summary

# 4. 恢复
configure terminal
interface GigabitEthernet1
 no shutdown
exit
```

### 自动化执行 (1行命令)
```bash
python -m olav.testing.fault_injection_examples
```

### 单个场景的Python代码
```python
import asyncio
from olav.testing.fault_injection import FaultScenarioRegistry, FaultInjectionTestHarness

async def main():
    scenario = FaultScenarioRegistry.get_scenario(1)
    harness = FaultInjectionTestHarness(scenario)
    await harness.run_complete_test_cycle()
    print(harness.generate_report())

asyncio.run(main())
```

---

## 📍 文件位置速查

| 文件 | 路径 | 大小 | 用途 |
|------|------|------|------|
| QUICK_REFERENCE | docs/plan/ | 600行 | 快速参考 |
| DETAILED_PROCEDURES | docs/plan/ | 3500行 | 详细步骤 |
| IMPLEMENTATION_SUMMARY | docs/plan/ | 500行 | 总结文档 |
| COMPLETION_REPORT | docs/plan/ | 400行 | 完成报告 |
| fault_injection.py | src/olav/testing/ | 700行 | 框架代码 |
| fault_injection_examples.py | src/olav/testing/ | 400行 | 示例代码 |

---

## ✅ 验收标准

### 执行完整周期的验收标准
```
✓ 注入成功 - 故障命令无错误
✓ 故障验证 - 症状确实出现
✓ 诊断对 - 根因识别正确
✓ 信心足 - confidence_score ≥ 阈值
✓ 无幻觉 - 无"也许"/"可能"等词
✓ 恢复成功 - 恢复命令无错误
✓ 恢复验证 - 系统回到正常
```

### 诊断质量的验收标准
```
Simple (场景1-3):
  ✅ 准确度 ≥90%
  ✅ 信心度 ≥0.88
  ✅ 幻觉词 <1%

Complex (场景4-7):
  ✅ 准确度 ≥85%
  ✅ 信心度 ≥0.80
  ✅ 幻觉词 <5%
```

---

## 🔗 相关文件导入

### The Expert Agent Framework
- `.olav/skills/network-expert/SKILL_DIAGNOSTIC_WORKFLOW.md` - 诊断配置
- `src/olav/agents/expert_diagnostician.py` - 诊断执行器
- `src/olav/agents/orchestrator_v2.py` - Orchestrator

### Network Configuration
- `exports/snapshots/latest/raw/` - 真实网络配置快照
- `.olav/devices/` - 设备定义 (如果有)

---

## 💡 常见问题

### Q: 从哪里开始?
A: 打开 FAULT_INJECTION_QUICK_REFERENCE.md (5分钟快速开始部分)

### Q: 如何手工执行?
A: 打开 FAULT_INJECTION_DETAILED_PROCEDURES.md，选择场景，按命令操作

### Q: 如何自动化?
A: 运行 `python -m olav.testing.fault_injection_examples`

### Q: 如何添加新场景?
A: 查看 QUICK_REFERENCE.md 中的"为Expert Agent增加新场景"部分

### Q: 如何评估诊断准确度?
A: 对比诊断结果与expected_diagnosis字段

---

## 📅 建议日程

### Week 1 (本周)
```
Day 1: 理解 (1小时)
  □ 读 QUICK_REFERENCE.md
  □ 读 COMPLETION_REPORT.md

Day 2: 验证 (1小时)
  □ 手工执行场景1
  □ 运行自动化框架

Day 3: 分析 (1小时)
  □ 收集诊断结果
  □ 评估准确度

Day 4-5: 改进 (2小时)
  □ 基于失败改进Expert
  □ 重新运行测试
```

### Week 2 (下周)
```
Day 1-2: 实现约束系统 (Task 4)
Day 3-4: 实现验证系统 (Task 5)
Day 5: 集成测试
```

---

## 🎓 学习路径

```
👶 入门 (30分钟)
  1. 本文件
  2. QUICK_REFERENCE.md
  3. 场景1演练

📚 中级 (2小时)
  1. DETAILED_PROCEDURES.md (全部)
  2. fault_injection.py (代码)
  3. fault_injection_examples.py (全部示例)

🚀 高级 (4小时)
  1. 整体架构 (IMPLEMENTATION_SUMMARY.md)
  2. SKILL配置 (SKILL_DIAGNOSTIC_WORKFLOW.md)
  3. 诊断器代码 (expert_diagnostician.py)
  4. 完整集成
```

---

## 📞 联系与支持

### 问题排查
- 故障排查表: QUICK_REFERENCE.md L{故障排查}
- 常见错误: DETAILED_PROCEDURES.md L{各场景错误处理}

### 反馈与改进
- 新增故障场景: 对标 FaultScenarioBuilder 用法
- 改进文档: 编辑相应 .md 文件
- 优化代码: 提交 PR 到 src/olav/testing/

---

**Status**: ✅ 完全准备好  
**Last Updated**: 2026-02-11  
**Maintainer**: Network AI Team

🎯 **现在就开始**: 打开 FAULT_INJECTION_QUICK_REFERENCE.md
