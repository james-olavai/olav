# OLAV v0.9.8 质量规范 (Development Spec)

> **版本**: v0.9.8  
> **核心原则**: 零垃圾代码、精确匹配缓存、统一网络专家

---

## 1. v0.9.8 架构要求

### 1.1 缓存策略
*   **精确匹配**: 使用 `query_text` 精确字符串匹配，不使用向量语义搜索
*   **无置信度分层**: 缓存命中为简单的 `true/false` 判断
*   **表结构简化**: `semantic_cache` 表无需 `query_embedding` 和 `confidence` 列

### 1.2 专家架构
*   **统一网络专家**: 只保留 `network-expert` (包含 L2/L3/Security)
*   **禁止专家碎片化**: 不应存在 `switching-expert`, `routing-expert`, `bgp-expert`, `security-expert` 等独立专家

### 1.3 代码清理 (Cleanup Requirements)
*   **删除未使用代码**:
    - `src/olav/core/memory_manager.py` (v0.10.x 功能)
    - `src/olav/analysis/` 目录
    - `.olav/agent_cache/*.duckdb` (如未使用)
*   **删除向量相关代码**: 移除 `array_cosine_similarity()` 调用和置信度逻辑

### 1.2 零冗余 (Zero Redundancy)
*   **单一事实来源**: 所有工具的定义必须来自于 `SKILL.md` 的 Schema，严禁在 Python 中重复定义参数结构。
*   **删除迁移中间态**: 一旦新 Agent 验证通过，必须立即删除对应的旧版本文件，不留 `_v1.py` 或 `_old.py`。

---

## 2. 测试要求 (Testing Requirements)

所有功能的合并必须通过以下测试流程：

### 2.1 E2E 验收测试 (End-to-End Testing)
*   **文件**: `tests/00_e2e_acceptance_test.py`
*   **强制要求**: 
    1.  **真实环境验证**: 必须在真实的 DuckDB 网络快照上运行，模拟真实网络设备返回结果。
    2.  **全链路编排验证**: 验证 Orchestrator 是否能正确识别意图、调度专家、并最终合成 Markdown 报告。
    3.  **负面场景测试**: 模拟 SQL 查询失败，验证系统是否能自动通过 ReAct 触发 CLI 回落或报错。

### 2.2 质量检查命令
在提交任何代码前，必须运行：

```bash
# 1. 运行代码质量检查
uv run pytest tests/00_e2e_acceptance_test.py::TestCodeQuality -v

# 2. 运行完整 E2E 验收流程
uv run pytest tests/00_e2e_acceptance_test.py -v

# 3. 性能达标检查
# 简单查询 < 3s, 复杂编排 < 30s
```

---

## 3. 架构一致性 (Architectural Consistency)

### 3.1 跨平台兼容性
*   所有 Skill 定义必须保持 **Platform-Agnostic**。
*   严禁在 Skill 的 Prompt 中加入特定 LLM 厂商的调优指令。

### 3.2 智能记忆
*   新功能的实现必须考虑 **Semantic Memory** 的读写。
*   每个 Specialist 的工具执行成功后，Orchestrator 必须尝试将 [问题-动作-结果] 存入向量缓存。

---

## 4. 垃圾清理清单 (Cleanup Checklist)

| 目标 | 状态 | 负责人 |
|:---|:---:|:---|
| 删除 `src/olav/agents/analysis_agent.py` | ⏳ | Agent Team |
| 删除 `src/olav/experts/` 全目录 | ⏳ | Expert Team |
| 替换 `cli_main.py` 中的硬编码路由逻辑 | ⏳ | CLI Team |
| 统一所有工具调用至 `SkillAdapter` | ⏳ | Tooling Team |

---
