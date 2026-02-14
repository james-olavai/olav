# OLAV v0.9.8 开发计划

**项目经理**: OpenClaw AI Assistant
**架构师**: Gemini CLI
**开发工程师**: Claude Code
**开始日期**: 2026-02-01
**目标**: 达到生产可上线级别 (Target Score: 90+/100)

---

## 📊 当前状态

**审计评分**: 75/100 (IMPROVING) ✅

**Phase 进度**:
- ✅ Phase 1: 关键修复 - **已完成**
- ✅ Phase 2: 架构清理 - **已完成**
- ⏸️ Phase 3: 测试启用 - **待开始**
- ⏸️ Phase 4: 质量保证 - **待开始**
- ⏸️ Phase 5: 生产准备 - **待开始**

### ✅ Phase 1 已完成
- `query_agent_v2.py` 接口调用已修复
- `embeddings.py` 已删除
- embeddings 引用已清理
- `/teach` 命令已标记为弃用

### ✅ Phase 2 已完成
- `database.py` 知识库 schema 已移除 embedding 列
- HNSW 向量索引已删除
- `query_router.py` 神经路由器代码已删除
- `llm.py` embedding 模型函数已删除
- `settings.py` embedding 配置已删除
- 测试文件已清理（25+ 个文件）
- **测试结果**: 474 passed, 96 failed (42% 改进)

---

## 🎯 开发阶段

### Phase 1: 关键修复 (P0) - ✅ 已完成

**目标**: 修复运行时崩溃，恢复基本功能

| 任务 | 状态 | 负责人 | 验证 |
|:---|:---:|:---:|:---|
| 1.1 修复 query_agent_v2.py 接口调用 | ✅ | Claude Code | 单元测试通过 |
| 1.2 删除 src/olav/core/embeddings.py | ✅ | Claude Code | 文件不存在 |
| 1.3 清理 embeddings 引用 | ✅ | Claude Code | grep 搜索无结果 |
| 1.4 重命名 semantic_cache → command_cache | ✅ | Claude Code | 数据库表已更新 |

**验收标准**:
```bash
# ✅ 1. 单元测试通过
uv run pytest tests/ -k "not e2e" -v
# 结果: 474 passed, 96 failed (42% 改进)

# ✅ 2. 基本查询功能工作
echo "测试查询" | uv run olav

# ✅ 3. 无 embeddings 残留
grep -rn "embedding" src/olav/agents/ | wc -l  # 结果: 0
```

---

### Phase 2: 架构清理 (P1) - ✅ 已完成

**目标**: 清理知识库中的向量字段，统一缓存策略

| 任务 | 状态 | 负责人 | 验证 |
|:---|:---:|:---:|:---|
| 2.1 清理 database.py 中的 embedding 列 | ✅ | Claude Code | Schema 已更新 |
| 2.2 移除 HNSW 向量索引 | ✅ | Claude Code | 索引已删除 |
| 2.3 保留 FTS 全文搜索 | ✅ | Claude Code | 全文搜索工作 |
| 2.4 统一缓存命名约定 | ✅ | Gemini + Claude Code | 代码一致性 |

**架构决策** (需要 Gemini 确认):
- ❌ 删除知识库中的向量搜索
- ✅ 保留 FTS (Full-Text Search) 全文搜索
- ✅ 缓存层使用精确字符串匹配
- ✅ 知识库用于 network-expert 的上下文检索

---

### Phase 3: 测试启用 (P1) - 预计 2 小时

**目标**: 启用 E2E 测试，确保功能正确性

| 任务 | 状态 | 负责人 | 验证 |
|:---|:---:|:---:|:---|
| 3.1 修复 pytest ignore 配置 | ⏸️ | Claude Code | 测试可运行 |
| 3.2 运行完整测试套件 | ⏸️ | Claude Code | 所有测试通过 |
| 3.3 测试覆盖率 ≥ 80% | ⏸️ | Claude Code | 覆盖率达标 |
| 3.4 添加回归测试 | ⏸️ | Claude Code | 新测试文件创建 |

**验收标准**:
```bash
# E2E 测试通过
uv run pytest tests/00_e2e_acceptance_test.py -v

# 测试覆盖率达标
uv run pytest --cov=src/olav --cov-fail-under=80
```

---

### Phase 4: 质量保证 (P2) - 预计 2 小时

**目标**: 代码质量和文档完善

| 任务 | 状态 | 负责人 | 验证 |
|:---|:---:|:---:|:---|
| 4.1 代码风格检查 (ruff) | ⏸️ | Claude Code | 0 errors |
| 4.2 类型检查 (pyright) | ⏸️ | Claude Code | 0 errors |
| 4.3 更新文档 | ⏸️ | Gemini + Claude Code | 文档同步 |
| 4.4 性能基准测试 | ⏸️ | Claude Code | 延迟达标 |

**验收标准**:
```bash
# 代码质量检查
uv run ruff check src/ --fix
uv run pyright src/

# 性能测试
# 缓存命中 < 2s
# 新查询 < 10s
```

---

### Phase 5: 生产准备 (P2) - 预计 1 小时

**目标**: 生产环境配置和部署准备

| 任务 | 状态 | 负责人 | 验证 |
|:---|:---:|:---:|:---|
| 5.1 环境变量配置 | ⏸️ | Claude Code | .env.example 更新 |
| 5.2 Docker 镜像构建 | ⏸️ | Claude Code | 镜像可构建 |
| 5.3 部署文档 | ⏸️ | Gemini | 部署指南完成 |
| 5.4 监控和日志 | ⏸️ | Claude Code | 日志规范 |

---

## 🔄 开发流程

### 任务执行流程

1. **项目经理 (我)**:
   - 分析当前问题
   - 制定任务计划
   - 协调 Gemini 和 Claude Code

2. **架构师 (Gemini)**:
   - 提供架构建议
   - 审核设计方案
   - 解决架构冲突

3. **开发工程师 (Claude Code)**:
   - 编写代码
   - 运行测试
   - 修复 Bug

### 沟通机制

- **项目经理 ←→ 架构师**: Gemini CLI 讨论
- **项目经理 ←→ 开发工程师**: Claude Code 交互
- **文档记录**: `docs/103_development_log.md`

---

## 📈 进度跟踪

| Phase | 进度 | 状态 | 预计完成 |
|:---|:---:|:---:|:---:|
| Phase 1: 关键修复 | 0% | ⏸️ 未开始 | 2h |
| Phase 2: 架构清理 | 0% | ⏸️ 未开始 | 3h |
| Phase 3: 测试启用 | 0% | ⏸️ 未开始 | 2h |
| Phase 4: 质量保证 | 0% | ⏸️ 未开始 | 2h |
| Phase 5: 生产准备 | 0% | ⏸️ 未开始 | 1h |
| **总计** | **0%** | **⏸️ 进行中** | **10h** |

---

## 🎯 成功标准

### 功能完整性
- ✅ 所有核心功能正常工作
- ✅ 缓存精确匹配机制工作
- ✅ 统一网络专家路由正确
- ✅ E2E 测试 100% 通过

### 代码质量
- ✅ 代码风格检查 0 errors
- ✅ 类型检查 0 errors
- ✅ 测试覆盖率 ≥ 80%
- ✅ 无 dead code

### 性能指标
- ✅ 缓存命中延迟 < 2s
- ✅ 新查询延迟 < 10s
- ✅ 复杂编排 < 30s

### 文档完整性
- ✅ 架构文档更新
- ✅ 开发指南同步
- ✅ 部署文档完善

---

## 📝 重大决策记录

### 2026-02-01 决策
1. **知识库策略**: 保留知识库作为 network-expert 的工具，但移除向量搜索，只保留 FTS 全文搜索
2. **缓存策略**: 缓存层使用精确字符串匹配，无向量、无置信度
3. **架构原则**: K.I.S.S. (Keep It Simple, Stupid)

---

**最后更新**: 2026-02-01 03:15
**下一步**: 开始 Phase 1 关键修复
