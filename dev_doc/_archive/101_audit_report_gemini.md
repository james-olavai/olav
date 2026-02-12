# OLAV v0.9.8 架构审计报告

**审计日期**: 2026年2月1日
**审计结果**: ❌ **CRITICAL FAIL (40/100)**

## 1. 核心发现 (Core Findings)

项目目前处于 **严重不一致** 状态，存在会导致运行时崩溃的接口错配，且未完成 v0.9.8 核心规范（移除向量搜索）。

### 🚨 阻断性问题 (Critical Issues)

1.  **运行时接口崩溃 (Runtime Crash)**
    *   **位置**: `src/olav/agents/query_agent_v2.py` (Line 163)
    *   **问题**: 调用了 `db.save_semantic_cache(user_query, embedding, action)`。
    *   **原因**: `src/olav/core/unified_database.py` 中的 `UnifiedDatabase` 类 **不存在** 该方法。它只有 `save_cache(query_text, action)`。
    *   **后果**: 缓存保存操作将抛出 `AttributeError`，虽然被 `try...except` 捕获，但意味着缓存功能完全失效。

2.  **Embedding 未移除 (Dead Code & Violation)**
    *   **规范**: v0.9.8 要求移除所有向量语义搜索和 embedding 列。
    *   **现状**:
        *   `src/olav/core/embeddings.py` 仍然存在。
        *   `src/olav/agents/query_agent_v2.py` 仍在使用 `get_embedder()` 生成向量。
        *   `src/olav/core/database.py` (知识库) 仍定义了 `embedding FLOAT[768]` 列和 `HNSW` 索引。

### 2. 详细合规性检查

| 审计领域 | 检查项 | 结果 | 说明 |
|:---|:---|:---|:---|
| **架构一致性** | 精确匹配缓存 | ⚠️ 部分通过 | DB层已改为精确匹配，但Agent层仍试图生成Embedding。 |
| | 删除向量搜索 | ❌ 失败 | 代码库中仍大量存在 Embedding 相关代码。 |
| | 统一网络专家 | ✅ 通过 | 使用了统一的 `network-query` skill。 |
| **代码清理** | `memory_manager.py` | ✅ 已删除 | 文件已移除。 |
| | `analysis/` 目录 | ✅ 已删除 | 目录已移除。 |
| | `embeddings.py` | ❌ 存在 | 应删除但未删除。 |
| **数据库** | Schema 合规 | ⚠️ 部分通过 | `UnifiedDatabase` 移除了 embedding 列，但 `OlavDatabase` (Knowledge) 未移除。 |

## 3. 建议行动 (Action Items)

请立即执行以下修复以恢复合规性：

1.  **[Fix] 修复 Agent 崩溃**:
    修改 `src/olav/agents/query_agent_v2.py`，移除所有 embedding 生成逻辑，将 `db.save_semantic_cache(...)` 调用替换为 `db.save_cache(user_query, action)`。

2.  **[Delete] 移除 Embedding 模块**:
    删除 `src/olav/core/embeddings.py` 文件，并清理 `src/olav/core/llm.py` 中的相关工厂方法。

3.  **[DB] 降级知识库 Schema**:
    修改 `src/olav/core/database.py`，移除 `knowledge_chunks` 表中的 `embedding` 字段和向量索引，仅保留 FTS 全文搜索。

4.  **[Rename] 重命名缓存表**:
    建议将 `UnifiedDatabase` 中的 `semantic_cache` 表重命名为 `command_cache` 或 `query_cache`，以消除歧义。

## 4. 详细审计发现

### 4.1 架构一致性 (40/100)

#### ✅ 已完成的清理
- `src/olav/core/memory_manager.py` - 已删除 ✅
- `src/olav/analysis/` 目录 - 已删除 ✅
- `src/olav/core/unified_database.py` - 已改为精确匹配缓存 ✅

#### ❌ 未完成的清理
- `src/olav/core/embeddings.py` - 仍存在 ❌
- `src/olav/agents/query_agent_v2.py` - 仍在使用 `get_embedder()` ❌
- `src/olav/core/database.py` - 保留 `embedding` 列和向量索引 ❌

#### 🐛 关键 Bug
**位置**: `src/olav/agents/query_agent_v2.py:163`

```python
# 当前代码 (会崩溃)
db.save_semantic_cache(user_query, embedding, action)

# 应该改为
db.save_cache(user_query, action)
```

### 4.2 统一网络专家 (100/100)

#### ✅ 架构符合规范
- 使用统一的 `network-query` skill ✅
- 不存在独立的子专家（routing-expert, switching-expert 等）✅
- 查询路由通过 `QueryRouter` 进行模式匹配 ✅

### 4.3 缓存实现 (50/100)

#### ✅ 正确实现
- `UnifiedDatabase.search_cache()` 使用精确字符串匹配 ✅
- 查询使用 `WHERE query_text = ?` 而非向量搜索 ✅
- 移除了 `semantic_threshold` 相关代码 ✅

#### ❌ 残留问题
- 表名仍为 `semantic_cache`（应改为 `command_cache`）⚠️
- Agent 层仍在调用 `get_embedder()` 生成无用向量 ❌
- 知识库 `knowledge_chunks` 表仍保留 `embedding` 列 ❌

### 4.4 测试覆盖 (0/100)

#### ❌ 测试文件缺失
- `tests/00_e2e_acceptance_test.py` 被忽略配置跳过 ❌
- 无法验证架构改造后的功能正确性 ❌

## 5. 代码质量问题

### 5.1 Dead Code
- `src/olav/core/embeddings.py` - 整个文件无实际用途
- `src/olav/core/database.py` 中的 `embedding` 字段和相关索引

### 5.2 接口不一致
- `UnifiedDatabase` 提供 `save_cache()`，但 Agent 调用 `save_semantic_cache()`
- 虽然被 `try...except` 捕获，但缓存功能完全失效

### 5.3 命名混乱
- 表名 `semantic_cache` 与实际功能（精确匹配缓存）不符
- 应重命名为 `command_cache` 或 `query_cache`

## 6. 最佳实践建议

### 6.1 立即修复 (P0 - Critical)
1. 修复 `query_agent_v2.py` 中的接口调用错误
2. 删除 `src/olav/core/embeddings.py`
3. 重命名缓存表并更新所有引用

### 6.2 短期改进 (P1 - High)
1. 清理 `database.py` 中的向量字段和索引
2. 更新测试配置，允许 E2E 测试运行
3. 添加回归测试防止类似问题

### 6.3 长期优化 (P2 - Medium)
1. 统一缓存命名约定
2. 添加代码静态检查（mypy/pyright）
3. 建立 CI/CD 自动化测试

## 7. 合规性评分

| 类别 | 得分 | 权重 | 加权分 |
|:---|:---:|:---:|:---:|
| 架构一致性 | 40/100 | 40% | 16/40 |
| 代码清理 | 70/100 | 30% | 21/30 |
| 缓存实现 | 50/100 | 20% | 10/20 |
| 测试覆盖 | 0/100 | 10% | 0/10 |
| **总分** | - | **100%** | **47/100** |

## 8. 结论

OLAV v0.9.8 项目 **未达到架构规范要求**，存在严重的接口不一致和代码残留问题。虽然部分清理工作已完成，但核心的 embedding 移除工作未彻底完成，导致运行时崩溃风险。

**建议**: 立即执行 P0 级别的修复项，然后运行完整的测试套件验证功能正确性。

---

**审计工具**: Gemini CLI
**审计时间**: 2026-02-01
**审计人**: OpenClaw AI Assistant
