# OLAV v0.9.8 路线图 - 简化架构与代码清理 (Simplified Architecture & Code Cleanup)

> **版本**: v0.9.8  
> **核心理念**: K.I.S.S. (Keep It Simple, Stupid)  
> **目标**: 精确匹配缓存 + 统一网络专家 + 零垃圾代码

---

## � 当前状态 (v0.9.8)

### 核心架构

**设计原则**:
- ✅ **精确匹配缓存** - 无语义搜索，无置信度分层
- ✅ **统一网络专家** - 单一 `network-expert` (L2-L7 全栈)
- ✅ **零业务 Fallback** - Agent 自主决策，不硬编码 fallback
- ✅ **DeepAgents ReAct** - 引擎 + 自定义 SkillAdapter

**技术栈**:
- Agent 框架: DeepAgents (ReAct)
- 数据库: DuckDB (精确匹配缓存 + 数据查询)
- Skills: `.olav/skills/network-expert/`
- Scripts: `.olav/scripts/*.py` (stdin/stdout)

---

## 🎯 Phase 1: 代码清理与架构对齐 (1-2周)

**目标**: 删除所有与 v0.9.8 架构不符的代码

### Task 1.1: 删除置信度相关代码 ✅

**删除内容**:
```bash
# 删除整个文件
rm src/olav/core/memory_manager.py

# 删除向量搜索逻辑
# - array_cosine_similarity() 调用
# - semantic_threshold 变量
# - confidence > 0.95 判断
```

**修改文件**:
- `src/olav/core/unified_database.py` - 删除 `search_semantic_cache()` (向量版本)
- `src/olav/agents/intent_agent.py` - 删除 `confidence > 0.95` 检查
- `src/olav/core/query_router.py` - 删除 `semantic_threshold`

**验证**:
```bash
grep -rn "confidence.*>" src/olav/ | wc -l  # 应为 0
grep -rn "array_cosine_similarity" src/olav/ | wc -l  # 应为 0
```

**预计工时**: 2小时  
**参考文档**: `docs/98_cleanup_checklist.md` § 1

---

### Task 1.2: 删除业务层 Fallback ✅

**禁止模式**:
```python
# ❌ 删除这种代码
def query_network(device):
    try:
        return execute_sql(device)
    except:
        return execute_cli(device)  # 业务层 fallback
```

**允许模式**:
```python
# ✅ 保留技术层 fallback
def connect_device(host):
    if shutil.which("scrapli"):
        return scrapli_connect(host)
    else:
        return netmiko_connect(host)  # 工具层 fallback
```

**修改文件**:
- `src/olav/agents/orchestrator.py` - 删除 SQL→CLI fallback
- `src/olav/core/query_router.py` - 删除 `fallback` 字段和方法

**验证**:
```bash
grep -rn "sql.*fallback.*cli" src/olav/ -i | wc -l  # 应为 0
```

**预计工时**: 3小时  
**参考文档**: `docs/98_cleanup_checklist.md` § 2

---

### Task 1.3: 删除 Legacy 代码 ✅

**删除目录**:
```bash
rm -rf src/olav/analysis/
rm -rf .olav/agent_cache/ (if not used)
```

**删除文件**:
```bash
# 检查是否存在子专家文件
find src/olav -name "*routing_expert*" -delete
find src/olav -name "*switching_expert*" -delete
find src/olav -name "*bgp_expert*" -delete
```

**验证**:
```bash
ls src/olav/analysis/  # 应不存在
find src/olav -name "*_expert.py" | wc -l  # 应为 0
```

**预计工时**: 1小时  
**参考文档**: `docs/98_cleanup_checklist.md` § 3, 4

---

### Task 1.4: 简化缓存表结构 ✅

**数据库迁移**:
```sql
-- 删除不需要的列
ALTER TABLE commands.main.semantic_cache 
DROP COLUMN IF EXISTS query_embedding;

ALTER TABLE commands.main.semantic_cache 
DROP COLUMN IF EXISTS confidence;

-- 添加统计列（可选）
ALTER TABLE commands.main.semantic_cache 
ADD COLUMN IF NOT EXISTS hit_count INTEGER DEFAULT 0;

ALTER TABLE commands.main.semantic_cache 
ADD COLUMN IF NOT EXISTS last_used TIMESTAMP DEFAULT NOW;
```

**修改代码**:
```python
# src/olav/core/unified_database.py
def search_cache(self, query_text: str) -> dict | None:
    """精确匹配查询缓存"""
    result = self.conn.execute(
        "SELECT * FROM commands.main.semantic_cache WHERE query_text = ?",
        [query_text]
    ).fetchone()
    return result

def save_cache(self, query_text: str, action: dict) -> None:
    """保存查询结果到缓存"""
    self.conn.execute(
        """INSERT INTO commands.main.semantic_cache 
           (query_text, action_json, hit_count, last_used)
           VALUES (?, ?, 0, NOW())
           ON CONFLICT (query_text) DO UPDATE SET
           hit_count = hit_count + 1,
           last_used = NOW()
        """,
        [query_text, json.dumps(action)]
    )
```

**预计工时**: 2小时  
**参考文档**: `docs/98_cleanup_checklist.md` § 2.2

---

## 🧪 Phase 2: E2E 测试验证 (3-5天)

**目标**: 确保所有清理后代码仍然正常工作

### Task 2.1: 运行完整 E2E 测试 ⏸️

```bash
# 代码质量检查
uv run ruff check src/
uv run ruff format src/
uv run pyright src/

# E2E 测试
uv run pytest tests/00_e2e_acceptance_test.py -v

# 覆盖率检查
uv run pytest --cov=src/olav --cov-fail-under=80
```

**预期结果**: 所有测试通过 ✅

**预计工时**: 2天（包含修复失败的测试）

---

### Task 2.2: 手动验证关键场景 ⏸️

**场景 1: 精确匹配缓存**
```bash
# 第一次查询（缓存未命中）
echo "查询 R1 BGP 邻居状态" | uv run olav

# 第二次相同查询（应命中缓存 <2s）
echo "查询 R1 BGP 邻居状态" | uv run olav

# 相似但不同查询（应未命中）
echo "查询 R2 BGP 邻居状态" | uv run olav
```

**场景 2: 统一网络专家**
```bash
# L2 查询
echo "显示 R1 的 VLAN 配置" | uv run olav

# L3 查询
echo "显示 R1 的 BGP 邻居" | uv run olav

# Security 查询
echo "显示 R1 的 ACL 规则" | uv run olav
```

**预计工时**: 1天

---

## 📚 Phase 3: 文档完善 (1-2天)

**已完成**:
- ✅ `README.md` - v0.9.8 架构概览
- ✅ `docs/03_development_spec.md` - 开发规范
- ✅ `docs/100_audit_report.md` - 架构审计
- ✅ `docs/66_ralph_instruction.md` - 循环开发指南
- ✅ `docs/98_cleanup_checklist.md` - 代码清理清单
- ✅ `.claude/claude.md` - 架构决策

**待完成**:
- ⏸️ 创建迁移指南 (v0.9.7 → v0.9.8)
- ⏸️ 更新 API 文档（如果有）

---

## 🚀 Phase 4: 性能优化 (可选, 1-2周)

### Task 4.1: 缓存性能优化 ⏸️

**目标**: 缓存命中延迟 < 0.5s

**优化项**:
1. 添加 DuckDB 索引
   ```sql
   CREATE INDEX IF NOT EXISTS idx_query_text 
   ON commands.main.semantic_cache(query_text);
   ```

2. 缓存预热（常用查询）
   ```python
   # 启动时预加载常用查询
   def warm_cache():
       common_queries = load_common_queries()
       for query in common_queries:
           db.search_cache(query)
   ```

3. 缓存统计
   ```python
   def cache_stats():
       return db.execute("""
           SELECT 
               COUNT(*) as total_entries,
               SUM(hit_count) as total_hits,
               AVG(hit_count) as avg_hits_per_entry
           FROM commands.main.semantic_cache
       """).fetchone()
   ```

**预计工时**: 3天

---

### Task 4.2: Agent 响应优化 ⏸️

**目标**: 新查询延迟 < 10s

**优化项**:
1. Skills 并行加载
2. Script 预编译（如果可能）
3. LLM 提示词优化

**预计工时**: 5天

---

## 📅 时间表

| Phase | 任务 | 预计工时 | 优先级 | 状态 |
|:---|:---|:---:|:---:|:---:|
| **Phase 1** | 代码清理 | 8小时 | 🔴 高 | ✅ |
| **Phase 2** | E2E 测试 | 3天 | 🔴 高 | ⏸️ |
| **Phase 3** | 文档完善 | 2天 | 🟡 中 | ✅ (主要完成) |
| **Phase 4** | 性能优化 | 8天 | 🟢 低 | ⏸️ |

**总预计**: 2-3周（Phase 1-3）

---

## ✅ 验收标准

### 代码质量

```bash
# 1. 无 ruff 错误
uv run ruff check src/ --fix
# 预期: 0 errors

# 2. 无 pyright 错误
uv run pyright src/
# 预期: 0 errors (warnings 可接受)

# 3. 测试覆盖率 ≥ 80%
uv run pytest --cov=src/olav --cov-fail-under=80
# 预期: PASSED
```

### 架构一致性

```bash
# 1. 无置信度代码
grep -rn "confidence.*>" src/olav/ | wc -l
# 预期: 0

# 2. 无业务 fallback
grep -rn "sql.*fallback.*cli" src/olav/ -i | wc -l
# 预期: 0

# 3. 无子专家
find src/olav -name "*routing_expert*" | wc -l
# 预期: 0

# 4. 无 legacy 目录
ls src/olav/analysis/
# 预期: No such file or directory
```

### 功能验证

```bash
# 1. E2E 测试全通过
uv run pytest tests/00_e2e_acceptance_test.py -v
# 预期: ALL PASSED

# 2. 缓存精确匹配工作
echo "test query" | uv run olav
echo "test query" | uv run olav  # 应 <2s
# 预期: 第二次明显更快

# 3. 统一专家工作
echo "查询 BGP" | uv run olav  # L3
echo "查询 VLAN" | uv run olav  # L2
echo "查询 ACL" | uv run olav  # Security
# 预期: 所有场景都工作
```

---

## 📖 参考文档

| 文档 | 用途 | 优先级 |
|:---|:---|:---:|
| `docs/100_audit_report.md` § 0.5 | 立即行动清单 | 🔴 必读 |
| `docs/98_cleanup_checklist.md` | 代码清理详细步骤 | 🔴 必读 |
| `docs/66_ralph_instruction.md` | 循环开发流程 | 🟡 高 |
| `docs/03_development_spec.md` | 开发规范 | 🟡 高 |
| `.claude/claude.md` § 架构决策 | 禁止模式和决策记录 | 🔴 必读 |

---

## 🎯 下一步: 立即开始 Phase 1

**开始命令**:
```bash
# 1. 创建清理分支
git checkout -b cleanup/v098-architecture

# 2. 删除 memory_manager
rm src/olav/core/memory_manager.py

# 3. 删除 analysis 目录
rm -rf src/olav/analysis/

# 4. 运行测试
uv run pytest tests/00_e2e_acceptance_test.py -v

# 5. 修复失败的测试（如果有）
# 6. 提交
git add .
git commit -m "cleanup: 删除 memory_manager 和 analysis 目录"
git push origin cleanup/v098-architecture
```

**使用 Ralph 循环**:
```bash
/ralph-wiggum:ralph-loop "执行 OLAV v0.9.8 Phase 1 代码清理，
遵循 docs/98_cleanup_checklist.md，直至所有清理任务完成" \
--max-iterations 30 \
--completion-promise "COMPLETE"
```

---

**路线图版本**: v0.9.8
**最后更新**: 2026-01-31
**状态**: Phase 1 已完成 ✅，Phase 2 待执行，Phase 3 已完成
