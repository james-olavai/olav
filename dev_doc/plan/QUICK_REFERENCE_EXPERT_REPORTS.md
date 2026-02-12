## 🚀 Expert报告生成 - 快速参考

**版本**: 1.0.0 | **日期**: 2026-02-11 | **状态**: ✅ 生产就绪

---

## ⚡ 30秒快速了解

```python
# 1️⃣ Expert生成诊断（自动）
diagnosis = ExpertDiagnosisOutput(
    scenario_id="bgp_issue_001",
    root_cause="BGP timeout",
    confidence_score=0.94,
    solution="Restart BGP daemon",
    # ... 其他字段
)

# 2️⃣ Orchestrator处理（自动）
orchestrator = create_default_orchestrator()
report = await orchestrator.process(diagnosis)  # ✅ 报告自动生成

# 3️⃣ 使用报告
print(report.summary())  # 显示摘要
path = orchestrator.save_report(report)  # ✅ 可选保存为JSON文件
```

**关键点**: 报告**自动生成**，无需用户指定 ✨

---

## 📋 核心问答

| 问题 | 答案 |
|------|------|
| **报告自动生成吗？** | ✅ 是 - 调用 `process()` 时自动生成 |
| **需要显式指定？** | ❌ 否 - 完全自动化 |
| **是markdown还是JSON？** | 📄 JSON格式 (统一存储) |
| **不保存文件会怎样？** | ✅ 报告仍在内存中可用 |
| **批量处理？** | ✅ 支持 - `process_batch()` |
| **文件保存位置？** | 📁 `exports/orchestrator_*.json` |
| **执行时间？** | ⚡ 2-3ms (总处理时间) |

---

## 🎯 三种使用方式

### 方式1: 仅处理，不保存文件
```python
report = await orchestrator.process(diagnosis)
print(report.summary())  # 显示在控制台
# 报告在内存中，无文件
```

### 方式2: 处理并保存文件
```python
report = await orchestrator.process(diagnosis)
path = orchestrator.save_report(report)
print(f"Saved to: {path}")
# exports/orchestrator_bgp_issue_001_20260211_103536.json
```

### 方式3: 批量处理
```python
diagnoses = [diagnosis1, diagnosis2, diagnosis3]
reports = await orchestrator.process_batch(diagnoses)

for scenario_id, report in reports.items():
    print(report.summary())
    orchestrator.save_report(report)  # 可选保存
```

---

## 📊 报告包含的内容

```json
{
  "scenario_id": "...",              // 场景ID
  "overall_decision": "accept",      // 决策: ACCEPT/REVIEW/REJECT/UNCERTAIN
  "constraint_score": 0.908,         // Task 4: 约束验证分数
  "accuracy_score": 0.925,           // Task 5: 准确性分数
  "confidence_score": 0.94,          // Expert的置信度
  "routing_decision": {...},         // 路由决策
  "critical_failures": [],           // 关键问题
  "warnings": [],                    // 警告
  "improvement_suggestions": [],     // 改进建议
  "execution_time_ms": 2.4          // 执行时间
}
```

---

## 🔄 自动执行的验证步骤

```
诊断输入
    ↓
[Task 4] 约束检查 → 检测幻觉、不完整等
    ↓
[Task 5] 准确性验证 → 与ground truth对比 (可选)
    ↓
[Task 6] 决策判断 → 决定ACCEPT/REVIEW/REJECT
    ↓
报告生成 ← ✅ 全部自动完成
```

---

## 💡 重要提示

### 1. 报告格式固定为JSON
即使Expert在诊断中包含markdown文本，报告仍是JSON。

```
✅ 诊断中可以有markdown文本: diagnostic_reasoning = "# 分析内容..."
❌ 报告始终是JSON: to_json() 返回JSON字符串
```

### 2. 文件保存是可选的
```
✅ save_report() 仅在需要时调用
❌ 不调用也不会报错，报告仍在内存
```

### 3. 批量处理自动分别保存
```python
# 3个诊断 → 3个独立报告文件
reports = await orchestrator.process_batch(diagnoses)
for scenario_id, report in reports.items():
    path = orchestrator.save_report(report)  # 分别保存
```

---

## 🧪 验证工作

### 已创建的测试
- ✅ `tests/e2e/test_orchestrator_report_export.py` - 集成测试
- ✅ `/tmp/test_orchestrator_export.py` - 验证脚本

### 运行测试
```bash
# 完整测试
uv run pytest tests/e2e/test_orchestrator_report_export.py -v

# 快速验证脚本
uv run python /tmp/test_orchestrator_export.py
```

### 测试结果
- ✅ 7个测试全部通过
- ✅ 文件生成验证通过
- ✅ JSON格式验证通过
- ✅ 批量处理验证通过

---

## 📚 详细文档

| 文档 | 内容 |
|------|------|
| [EXPERT_REPORT_GENERATION_MECHANISM.md](../EXPERT_REPORT_GENERATION_MECHANISM.md) | 完整机制说明 |
| [INTEGRATION_TEST_REPORT_2026_02_11.md](../INTEGRATION_TEST_REPORT_2026_02_11.md) | 测试报告 |
| [06_CLI_AGENT.md](../../user_guide/06_CLI_AGENT.md) | CLI Agent指南 |

---

## ✅ 生产就绪检查表

- [x] 报告生成机制完整
- [x] 自动化工作流验证
- [x] 文件输出验证
- [x] JSON格式验证
- [x] 性能达到目标 (<5ms)
- [x] 代码修复完成
- [x] 集成测试通过
- [x] 文档完整

---

## 🎓 常见场景解决方案

### 场景1: 我想看诊断的评估结果
```python
report = await orchestrator.process(diagnosis)
print(report.summary())  # 显示可读摘要
```

### 场景2: 我想保存诊断报告
```python
report = await orchestrator.process(diagnosis)
path = orchestrator.save_report(report)  # 保存为JSON
```

### 场景3: 我想批量处理多个诊断
```python
reports = await orchestrator.process_batch(diagnoses)
for scenario_id, report in reports.items():
    orchestrator.save_report(report)
```

### 场景4: 我想获取JSON数据进行程序处理
```python
report = await orchestrator.process(diagnosis)
json_str = report.to_json()  # 获取JSON字符串
report_dict = report.to_dict()  # 获取字典
```

### 场景5: 我想检查报告中的问题
```python
report = await orchestrator.process(diagnosis)
if report.critical_failures:
    print("有关键问题:")
    for issue in report.critical_failures:
        print(f"  - {issue}")
```

---

## 🔗 相关代码文件

```
src/
├── olav/testing/
│   └── expert_constraints.py          # ExpertDiagnosisOutput定义
├── olav/orchestrator/
│   ├── expert_orchestrator.py        # Orchestrator核心
│   └── examples.py                   # 使用示例
└── olav/integration/
    └── expert_agent_integration.py   # 集成层

tests/e2e/
└── test_orchestrator_report_export.py # 集成测试
```

---

## 🎯 核心API

```python
# 初始化
orchestrator = create_default_orchestrator()

# 单条处理
report: OrchestratorReport = await orchestrator.process(
    diagnosis: ExpertDiagnosisOutput,
    ground_truth: Optional[GroundTruth] = None
)

# 批量处理
reports: Dict[str, OrchestratorReport] = await orchestrator.process_batch(
    diagnoses: List[ExpertDiagnosisOutput],
    ground_truths: Optional[Dict[str, GroundTruth]] = None
)

# 保存报告
path: Path = orchestrator.save_report(
    report: OrchestratorReport,
    output_dir: Optional[Path] = None  # 默认: exports/
)

# 获取报告内容
summary: str = report.summary()           # 可读摘要
report_dict: Dict = report.to_dict()      # 字典格式
report_json: str = report.to_json()       # JSON字符串
```

---

**最后更新**: 2026-02-11  
**维护者**: Expert Agent Team  
**许可**: Internal Use  

---
