# Ralph Loop Instruction - OLAV v0.9.8 循环开发指南

> **Ralph Wiggum 循环**: 迭代式 TDD 开发流程，直至所有任务完成

---

## 🎯 Ralph Loop 核心流程

```
/ralph-wiggum:ralph-loop "执行 OLAV v0.9.8 开发循环"
```

---

## 📋 循环步骤 (Loop Steps)

### Step 1: 文档清单与任务识别

**操作**:
```bash
# 1. 读取核心文档（按顺序）
1. README.md - 架构概览
2. docs/100_audit_report.md - 架构决策（Section 0.5 立即行动清单）
3. docs/03_development_spec.md - 开发规范
4. docs/99_project_progress.md - 任务清单
```

**决策树**:
```
所有任务都标记为 [x]？
├─ YES → 跳转到 Step 6 (完成)
└─ NO  → 继续 Step 2
```

**任务优先级**:
1. 🔴 **Critical** - `docs/100_audit_report.md` Section 0.5 立即行动清单
2. 🟡 **High** - `docs/99_project_progress.md` 中的 `[ ]` 任务
3. 🟢 **Normal** - Feature roadmap 任务

**示例任务识别**:
```markdown
# docs/100_audit_report.md Section 0.5
立即行动清单 (1-2天内):

1. [ ] 版本统一: 所有文档和代码改为 v0.9.8
2. [ ] 实施精确匹配缓存
3. [ ] 合并为 network-expert
4. [ ] 废弃冲突文档
5. [ ] 清理孤立代码
6. [ ] 更新 README.md
```

---

### Step 2: 质量检查优先 (Quality First)

**CRITICAL**: 在编写任何新代码前，先修复现有错误

```bash
# 2.1 检查代码质量
uv run ruff check src/
uv run ruff format --check src/
uv run pyright src/

# 2.2 如果有错误
uv run ruff check src/ --fix
uv run ruff format src/

# 2.3 验证修复
uv run pytest tests/00_e2e_acceptance_test.py::TestCodeQuality -v
```

**如果质量检查失败**:
- ⛔ **禁止开始新任务**
- ✅ **优先修复质量问题**
- ✅ **提交修复**: `git commit -m "fix: 修复 ruff/pyright 错误"`

---

### Step 3: TDD 组件开发 (Red-Green-Refactor)

**3.1 针对当前任务创建测试**

**示例**: 实施精确匹配缓存

```python
# tests/core/test_exact_match_cache.py
def test_exact_match_cache_hit():
    """测试精确匹配缓存命中"""
    db = UnifiedDatabase()
    
    # 存储缓存
    db.save_cache("show bgp neighbor R1", {"action": "SELECT ..."})
    
    # 精确匹配（应命中）
    result = db.search_cache("show bgp neighbor R1")
    assert result is not None
    
    # 相似但不精确（应未命中）
    result = db.search_cache("show bgp neighbor R2")
    assert result is None  # ✅ 精确匹配，不容近似
```

**3.2 运行测试 → 确认 FAIL**

```bash
uv run pytest tests/core/test_exact_match_cache.py -v
# 预期输出: FAILED (因为功能未实现)
```

**3.3 实现最小核心逻辑**

```python
# src/olav/core/unified_database.py
def search_cache(self, query: str) -> dict[str, Any] | None:
    """精确匹配查询缓存（不使用向量搜索）"""
    result = self.conn.execute(
        "SELECT * FROM commands.main.semantic_cache WHERE query_text = ?",
        [query]
    ).fetchone()
    return result if result else None
```

**3.4 运行测试 → 确认 PASS**

```bash
uv run pytest tests/core/test_exact_match_cache.py -v
# 预期输出: PASSED ✅
```

**⚠️ CRITICAL - 禁止 Legacy 模式**:
```python
# ❌ FORBIDDEN - 不使用旧的 smart_query 魔法
from olav.legacy.smart_query import magic_query

# ✅ CORRECT - 使用新的架构
from olav.core.skill_adapter import SkillAdapter
```

---

### Step 4: 集成验证 (Integration Verification)

**4.1 确定相关 E2E 阶段**

任务 → E2E Phase 映射:
```
精确匹配缓存 → Phase 5 (ReAct 查询功能)
网络专家合并 → Phase 5 (Skill 加载)
数据库结构 → Phase 4 (数据库结构)
```

**4.2 运行相关 E2E 测试**

```bash
# 示例: 精确匹配缓存
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase5QueryTools -v

# 如果失败
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase5QueryTools -v --pdb
```

**4.3 验证数据融合 (DB + CLI)**

```bash
# 确保混合查询工作正常
uv run olav query "查询 R1 BGP 邻居状态"

# 验证输出包含：
# - DuckDB 历史数据（快照）
# - 实时 CLI 数据（如果需要）
```

---

### Step 5: 更新文档并迭代 (Update & Loop)

**5.1 标记任务完成**

```markdown
# docs/100_audit_report.md Section 0.5
立即行动清单 (1-2天内):

1. [x] 版本统一: 所有文档和代码改为 v0.9.8 ✅
2. [ ] 实施精确匹配缓存  ← 当前任务
3. [ ] 合并为 network-expert
```

**5.2 提交代码**

```bash
git add .
git commit -m "feat: 实施精确匹配缓存

- 修改 UnifiedDatabase.search_cache() 为精确匹配
- 删除 array_cosine_similarity() 调用
- 添加单元测试 test_exact_match_cache
- E2E Phase 5 测试通过"

git push
```

**5.3 立即返回 Step 1**

⚠️ **CRITICAL**: 不要停止，立即处理下一个任务

```
✅ 任务 2 完成 → 立即检查任务 3 → 重复 Step 1-5
```

---

### Step 6: 最终退出 (Final Exit)

**触发条件**: 所有文档中的任务都标记为 `[x]`

**验证**:
```bash
# 6.1 确认所有任务完成
grep -r "\[ \]" docs/100_audit_report.md docs/99_project_progress.md
# 预期输出: 空（无未完成任务）

# 6.2 运行完整 E2E 测试
uv run pytest tests/00_e2e_acceptance_test.py -v
# 预期输出: ALL PASSED ✅

# 6.3 代码质量检查
uv run ruff check src/
uv run pyright src/
uv run pytest --cov=src/olav --cov-fail-under=80
# 预期输出: ALL PASSED ✅
```

**输出**:
```
<promise>COMPLETE</promise>
```

---

## 📚 关键文档参考

### 架构决策文档 (必读)

| 文档 | 用途 | 何时阅读 |
|:---|:---|:---|
| `README.md` | v0.9.8 架构概览 | 每次循环开始 |
| `docs/100_audit_report.md` | 架构决策和立即行动清单 | 识别任务优先级 |
| `docs/03_development_spec.md` | 代码质量要求 | 编写代码前 |
| `.claude/claude.md` | 开发规范（含禁止模式） | 避免错误 |

### 任务清单文档

| 文档 | 内容 | 更新频率 |
|:---|:---|:---|
| `docs/100_audit_report.md` § 0.5 | 🔴 立即行动清单 (6步) | 每完成1步更新 |
| `docs/99_project_progress.md` | 🟡 Feature 开发进度 | 每完成1个功能更新 |

---

## 🚫 常见陷阱与避免

### 陷阱 1: 不阅读文档就开始编码

❌ **错误**:
```
开发者: "我开始实现 Federated Specialists..."
```

✅ **正确**:
```
1. 阅读 README.md → 发现架构是 Unified Expert
2. 阅读 docs/100_audit_report.md → 确认决策
3. 实现 Unified Network Expert
```

### 陷阱 2: 质量检查失败仍继续开发

❌ **错误**:
```bash
$ uv run ruff check src/
Found 15 errors ❌
# 开发者继续编写新功能...
```

✅ **正确**:
```bash
$ uv run ruff check src/
Found 15 errors ❌
# 立即修复
$ uv run ruff check src/ --fix && uv run ruff format src/
All checks passed ✅
# 现在可以开始新功能
```

### 陷阱 3: 完成任务后不更新文档

❌ **错误**:
```python
# 完成精确匹配缓存代码
git commit -m "feat: exact match cache"
# 忘记更新 docs/100_audit_report.md 的任务清单
```

✅ **正确**:
```markdown
# docs/100_audit_report.md
2. [x] 实施精确匹配缓存 ✅
```

### 陷阱 4: 跳过 E2E 测试

❌ **错误**:
```bash
# 单元测试通过就提交
$ pytest tests/core/test_cache.py
All passed ✅
$ git push  # 跳过 E2E
```

✅ **正确**:
```bash
$ pytest tests/core/test_cache.py
All passed ✅
$ pytest tests/00_e2e_acceptance_test.py::TestPhase5 -v
All passed ✅  # 确保集成正常
$ git push
```

---

## 🔄 完整循环示例

### 示例任务: 实施精确匹配缓存

**循环迭代 1**:

```bash
# === Step 1: 读取文档 ===
cat docs/100_audit_report.md  # 发现任务: "实施精确匹配缓存"

# === Step 2: 质量检查 ===
uv run ruff check src/
# Output: All passed ✅

# === Step 3: TDD ===
# 创建测试
cat > tests/core/test_exact_match_cache.py << EOF
def test_exact_match():
    db = UnifiedDatabase()
    db.save_cache("query1", {"data": "result1"})
    assert db.search_cache("query1") is not None
    assert db.search_cache("query2") is None  # 不近似匹配
EOF

# 运行测试 → RED
uv run pytest tests/core/test_exact_match_cache.py
# Output: FAILED ❌

# 实现功能
cat > src/olav/core/unified_database.py << EOF
def search_cache(self, query: str):
    return self.conn.execute(
        "SELECT * FROM semantic_cache WHERE query_text = ?",
        [query]
    ).fetchone()
EOF

# 运行测试 → GREEN
uv run pytest tests/core/test_exact_match_cache.py
# Output: PASSED ✅

# === Step 4: E2E 验证 ===
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase5 -v
# Output: PASSED ✅

# === Step 5: 更新并提交 ===
# 更新文档
sed -i 's/\[ \] 实施精确匹配缓存/\[x\] 实施精确匹配缓存/' docs/100_audit_report.md

# 提交
git add .
git commit -m "feat: 实施精确匹配缓存"
git push

# === 立即返回 Step 1 处理下一个任务 ===
```

---

## 📊 循环终止条件

**检查清单**:

```bash
# 1. 所有任务完成
grep "\[ \]" docs/100_audit_report.md docs/99_project_progress.md
# 输出: 空 ✅

# 2. 所有 E2E 测试通过
uv run pytest tests/00_e2e_acceptance_test.py -v
# 输出: 13 passed ✅

# 3. 代码质量达标
uv run ruff check src/ && uv run pyright src/
# 输出: All checks passed ✅

# 4. 测试覆盖率 ≥ 80%
uv run pytest --cov=src/olav --cov-fail-under=80
# 输出: Coverage: 85% ✅
```

**如果全部 ✅**:
```
输出: <promise>COMPLETE</promise>
```

---

## 🎯 Ralph 循环命令

**标准循环**:
```bash
/ralph-wiggum:ralph-loop "执行 OLAV v0.9.8 开发循环，遵循 TDD，直至所有任务完成" \
  --max-iterations 50 \
  --completion-promise "COMPLETE"
```

**快速循环** (跳过质量检查):
```bash
/ralph-wiggum:ralph-loop "快速开发循环（仅用于 hotfix）" \
  --skip-quality-check \
  --max-iterations 10
```

---

**最后更新**: 2026-01-31  
**版本**: v0.9.8