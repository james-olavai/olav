# Skill-Centric 架构迁移 - 文档导航

**快速链接**: [架构设计](#架构设计) | [执行清单](#执行清单) | [技术深度](#技术深度) | [FAQ](#常见问题)

---

## 📚 文档体系

本迁移计划由三个互补的文档组成：

### 1️⃣ [架构设计文档](./ARCHITECTURE_MIGRATION_SKILLCENTRIC.md)
**目标读者**: 架构师、技术主管、需要理解总体方案的人

**内容**:
- 📊 当前混乱架构诊断
- 🎯 最终目标架构设计
- 📋 完整的Phase 1-3 执行步骤
- 🔄 导入链变更规则
- ✓ 影响范围和验证清单

**何时阅读**:
- 需要理解为什么要做这个迁移
- 想了解整体的迁移策略
- 需要向团队解释改动

**关键概念**:
```
【Before】Agent → from olav.tools.* ❌
【After】  Agent → from olav.shared.tools.* ✅
                         ↓
                    Wrapper layer
                         ↓
                   src/olav/tools/*
```

---

### 2️⃣ [执行清单文档](./MIGRATION_EXECUTION_CHECKLIST.md)
**目标读者**: 开发人员、需要执行迁移的人

**内容**:
- ✅ 7个要创建的wrapper文件的完整代码
- 📝 13个Python文件的具体修改位置和内容
- 🧪 验证步骤和测试命令
- 🎯 快速检查清单
- ⏱️ 时间估计

**何时阅读**:
- 准备开始执行迁移
- 需要知道修改哪些文件
- 想快速参考代码改动

**关键内容**:
```
✅ Phase 1: 创建7个wrapper文件
   - .olav/skills/shared/tools/data_export.py
   - .olav/skills/shared/tools/network_executor.py
   - .olav/skills/shared/tools/report_formatter.py
   - ... (共7个)

📝 Phase 2: 修改13个Python文件
   - orchestrator.py (4处)
   - guard.py (1处)
   - inspector.py (2处)
   - ... (共13个文件)

🧪 Phase 3: 验证和测试
   - 导入检查
   - E2E测试
   - 手动功能测试
```

---

### 3️⃣ [技术深度文档](./WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md)
**目标读者**: 高级开发人员、负责code review的人、想深入理解架构的人

**内容**:
- 📚 Skill-Centric架构核心原则 (4条)
- 🔄 为什么需要wrapper (5个原因)
- 🎯 每个wrapper的设计规程 (7个wrapper详解)
- 🔗 依赖关系图和导入链
- 🔮 未来演进路径
- 📊 方案对比 (4种方案evaluation)

**何时阅读**:
- 进行code review时
- 对某个具体wrapper有疑问
- 想理解设计决策的背后rationale
- 负责维护wrapper层的人

**关键设计模式**:
```python
【Wrapper最佳实践】
✅ 仅仅转发导入
❌ 不添加额外逻辑
❌ 不修改函数签名
✅ 明确列出__all__

# 示例
from olav.tools.data_export import format_and_export
__all__ = ["format_and_export"]
```

---

## 🗺️ 使用场景导航

### 🎯 Scenario 1: "我是新人，想理解整个迁移"
```
推荐阅读顺序：
1. 本文件 (你在这里) ← Overview
2. ARCHITECTURE_MIGRATION_SKILLCENTRIC.md ← 整体规划
3. MIGRATION_EXECUTION_CHECKLIST.md ← 实际步骤
4. WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md ← 深入理解

预计时间：30分钟
```

### 🔧 Scenario 2: "我需要执行这个迁移"
```
推荐阅读顺序：
1. MIGRATION_EXECUTION_CHECKLIST.md ← 按步骤执行
2. ARCHITECTURE_MIGRATION_SKILLCENTRIC.md ← 理解为什么
3. WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md ← 遇到问题时查看

预计时间：1-2小时 (包括实际执行)
```

### 👀 Scenario 3: "我需要Review别人的代码或Wrapper"
```
推荐阅读顺序：
1. WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md ← 最佳实践
2. MIGRATION_EXECUTION_CHECKLIST.md ← 校验checklist
3. ARCHITECTURE_MIGRATION_SKILLCENTRIC.md ← 背景理解

预计时间：15分钟 (快速review)
```

### ❓ Scenario 4: "我有问题或疑问"
```
建议：
- 问题关于"为什么": ARCHITECTURE_MIGRATION_SKILLCENTRIC.md
- 问题关于"怎么做": MIGRATION_EXECUTION_CHECKLIST.md
- 问题关于"为什么这样设计": WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md

快速查找：见下方 FAQ
```

---

## 📊 迁移时间表

```
【整个迁移流程】
Day 1:
  ├─ 09:00 - 阅读 ARCHITECTURE_MIGRATION_SKILLCENTRIC.md (30 min)
  ├─ 09:30 - 创建 7个wrapper文件 (30 min)
  ├─ 10:00 - 修改 13个Python文件 (45 min)
  └─ 11:00 - 验证和测试 (30 min)

【总计】约 2.5 小时

【可选】
  ├─ 阅读 WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md (30 min)
  └─ 深入理解设计决策和未来演进 (30 min)
```

---

## ✓ 验证清单 (快速版)

迁移完成后，检查以下项目：

```
【Wrapper创建】
☐ 7个wrapper文件已创建在 .olav/skills/shared/tools/
☐ 每个wrapper都能被导入
☐ 没有circular import错误

【代码修改】
☐ 13个文件的导入已更新
☐ orchestrator.py: 4处修改 ✅
☐ guard.py: 1处修改 ✅
☐ inspector.py: 2处修改 ✅
☐ intent_agent.py: 1处修改 ✅
☐ analyzer.py: 修改完成 ✅
☐ cli/cli_main.py: 修改完成 ✅
☐ cli/commands.py: 修改完成 ✅
☐ __init__.py: 修改完成 ✅

【验证命令】
☐ grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools"
   期望：无输出 (表示没有直接导入olav.tools)

【测试】
☐ uv run pytest tests/e2e/test_real_scenarios.py -v
   期望：✅ All tests passed
☐ uv run olav ask "test query"
   期望：✅ Query works normally

【最终】
☐ git commit -m "refactor: migrate to Skill-Centric tools wrapper layer"
☐ git push
```

---

## 🛠️ 文件快速参考

| 文件名 | 行数 | 用途 | 关键章节 |
|--------|------|------|---------|
| ARCHITECTURE_MIGRATION_SKILLCENTRIC.md | ~400 | 整体规划 | Phase 1-3, 导入链变更 |
| MIGRATION_EXECUTION_CHECKLIST.md | ~600 | 执行指南 | 具体代码, wrapper模板 |
| WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md | ~550 | 深度理解 | 设计原理, 依赖关系 |

---

## 🎓 相关文档

这个迁移计划补充以下现有文档：

- [ARCHITECTURE.md](../docs/reference/ARCHITECTURE.md) - 系统总体架构
- [SKILL_AUTHORING_GUIDE.md](../docs/reference/SKILL_AUTHORING_GUIDE.md) - Skill定义方式
- [CONFIGURATION_REFERENCE.md](../docs/reference/CONFIGURATION_REFERENCE.md) - 配置参考
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](../docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md) - Agent开发

---

## 📞 常见问题

### Q1: 为什么不直接修改src/olav/tools的导入？
**A**: 因为那样不符合Skill-Centric原则。wrapper在`.olav/skills`下，明确表示这些是Skill的工具，不是通用库。

### Q2: Wrapper是不是多余的一层？
**A**: 不是。它的作用是：
1. 清晰的架构边界 (Agent知道工具来自Skill)
2. 支持未来定制化 (可以创建skill-specific版本)
3. 解耦合 (src/olav/tools变成可选的实现库)

### Q3: 如果某个Wrapper需要修改怎么办？
**A**: 两个选择：
1. **共享修改**: 修改 `src/olav/tools/{name}.py`，会影响所有使用该工具的Skill
2. **定制修改**: 创建 `.olav/skills/{skill}/tools/{name}.py`，仅该Skill使用定制版本

### Q4: wrapper会影响性能吗？
**A**: 不会。导入时只是做转发，运行时调用完全相同。

### Q5: 如果修改src/olav/tools中的代码会怎样？
**A**: Wrapper会自动继承修改。这就是wrapper的优势 - 保持同步无需维护两份代码。

### Q6: 这个迁移会破坏现有功能吗？
**A**: 不会。仅改导入路径，没有改逻辑。所有测试应该通过。

### Q7: 其他部分代码也有from olav.tools导入，都要改吗？
**A**: 是的。规则很简单：
- ✅ `src/olav/tools/` 内部 → 继续用 `from olav.tools`
- ❌ `src/olav/` 外部 → 改为 `from olav.shared.tools`

### Q8: 我该从哪个文件开始创建wrapper？
**A**: 通常的顺序：
1. `network_executor.py` (被多处使用)
2. `data_export.py` (被多处使用)
3. 其他的 (按使用频率)

但顺序不重要，都创建完后一起修改导入。

### Q9: 是否需要改.olav/skills/*/tools中的文件？
**A**: 通常不需要。它们已经在`.olav/skills`下了，符合架构。但如果它们导入了`src/olav/tools`，也需要改为用wrapper（跳过一层，直接导入wrapper）。

### Q10: 这个改动后能删除src/olav/tools吗？
**A**: 暂时不能。src/olav/tools仍是实现层，wrapper指向它。未来可以逐步迁移实现到`.olav/skills/shared/tools`中，那时才能删除。

---

## 📋 下一步

✅ **现在**: 选择合适的Scenario，阅读对应文档

🚀 **然后**: 根据MIGRATION_EXECUTION_CHECKLIST.md执行迁移

🧪 **最后**: 运行测试验证

💬 **如有问题**: 参考常见问题或查看对应技术文档

---

**最后更新**: 2026-02-12  
**版本**: v1.0.0  
**维护者**: AI Architecture Team  
**状态**: 📋 Ready for execution
