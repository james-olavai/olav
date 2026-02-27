# Plan: OLAV-OPS 架构优化

## TL;DR

> **目标**: 根据架构评审结果，优化 olav-ops skill 的命名、工具集和 prompt 描述
> 
> **改动范围**: olav-ops skill 内部文件修改
> 
> **工作量**: ~1小时（4个小任务）

---

## 背景

### 评审结论

用户提出的 9 条意见全部合理：

1. ✅ 健康评分是 audit 职责
2. ✅ 时序分析 = diff配置 + SQL历史查询
3. ✅ 增加 routing/CEF 路径分析（后续）
4. ✅ 分析靠 LLM 推理而非硬编码
5. ✅ 顶层是 Orchestrator，skill 是 sub-agent
6. ✅ 不需要结构化工具
7. ✅ 集成 web_search
8. ✅ diff 只对比配置，SQL 对比 JSON
9. ✅ diff 命名统一为 diff_configs

### 架构现状

```
OLAV Orchestrator (.olav/OLAV.md)
    ├── olav-ops (查询层 - 只读)
    ├── olav-config (基础设施层 - 读写)
    └── olav-audit (治理层 - 只读评估)
```

---

## TODOs

- [ ] 1. 重命名 diff_snapshot.py → diff_configs.py

  **What to do**:
  - 重命名 `/home/yhvh/Olav/.olav/skills/olav-ops/tools/diff_snapshot.py` 为 `diff_configs.py`
  - 更新文件内函数名为 `diff_configs`
  - 更新 docstring 保持一致

  **Must NOT do**:
  - 不要改变功能逻辑
  - 不要删除现有测试

  **Parallelization**: 可单独执行

  **Acceptance Criteria**:
  - [ ] 文件重命名完成
  - [ ] 函数名更新为 diff_configs
  - [ ] 运行 `python diff_configs.py --help` 无报错

- [ ] 2. 添加 web_search.py 到 olav-ops

  **What to do**:
  - 复制 `olav-config/tools/web_search.py` 到 `olav-ops/tools/web_search.py`
  - 保持功能完全一致（DuckDuckGo 搜索）
  - 遵循 skill 独立性原则

  **Must NOT do**:
  - 不要创建共享工具目录（违反独立性）

  **Parallelization**: 可与任务1并行执行

  **Acceptance Criteria**:
  - [ ] 文件创建完成
  - [ ] 导入测试通过：`python -c "from web_search import web_search"`

- [ ] 3. 更新 olav-ops/SKILL.md 工具列表

  **What to do**:
  - 更新 tools 列表：添加 web_search
  - 更新 diff_snapshot → diff_configs
  - 确保与实际文件一致

  **Parallelization**: 可与任务1、2并行执行

  **Acceptance Criteria**:
  - [ ] SKILL.md tools 列表反映实际状态

- [ ] 4. 增强 network_ops_subagent.md 时序分析指导

  **What to do**:
  - 添加 "时序分析方法" 章节
  - 包含 diff_configs 使用示例
  - 包含 SQL 历史查询示例（snapshot_date 过滤）

  **Parallelization**: 依赖任务1完成（使用正确的工具名）

  **Acceptance Criteria**:
  - [ ] prompt 包含时序分析章节
  - [ ] 示例 SQL 语法正确

---

## 后续扩展（不在本次范围）

1. 修订 `olav-ops/prompts/system.md` 提升为 Orchestrator prompt
2. 扩展 routing/CEF/forwarding 路径分析 schema
3. 在 dev_docs 创建完整架构评审文档

---

## 成功标准

- [ ] 所有文件重命名/创建完成
- [ ] SKILL.md 反映最新状态
- [ ] 无语法错误
