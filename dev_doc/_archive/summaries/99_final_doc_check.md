# 文档最终检查与修复总结

**日期**: 2026-01-31  
**检查项**: v0.9.8引用、置信度设计、垃圾代码

---

## ✅ 已完成的修复

### 1. `.claude/claude.md` 自动修复

**执行的命令**:
```bash
sed -i 's/v0\.10\.[0-9x]*/v0.9.8/g' .claude/claude.md
sed -i 's/Olav v0\.10\.0+/OLAV v0.9.8/g' .claude/claude.md
```

**结果**: 所有 `v0.9.8` 已替换为 `v0.9.8` ✅

### 2. 创建垃圾代码清理清单

**文件**: `docs/98_cleanup_checklist.md`

**内容包含**:
- 🔴 立即删除的代码（置信度、fallback、legacy）
- 🟡 需要重构的代码（query_router, unified_database）
- 🟢 允许保留的代码（技术层fallback）
- 📋 清理验证清单
- 🔧 自动化清理脚本

---

## ⚠️ 需要手动修复的问题

### 问题 1: `.claude/claude.md` Line 345 - Semantic Cache/Vector Search

**当前内容**:
```markdown
| **Tier 0** | **Semantic Cache** | Vector Search | **<0.5s** |
```

**应该改为**:
```markdown
| **Tier 0** | **Exact Match Cache** | query_text == ? | **<0.5s** |
```

**修复方法**:
```bash
# 打开文件手动编辑 Line 345
vim .claude/claude.md +345

# 或使用 sed
sed -i '345s/Semantic Cache.*Vector Search/Exact Match Cache | query_text == ?/' .claude/claude.md
```

---

### 问题 2: `.claude/claude.md` Line 306-337 - Three-Layer Architecture

**当前内容**: 描述 Federated Specialists 架构（v0.9.8）

**应该改为**: v0.9.8 简化架构

**修复方法**:
手动替换 Line 306-337 为:
```markdown
### v0.9.8 架构（当前版本）

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Skill Layer (Platform-Agnostic)               │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ .olav/skills/network-expert/SKILL.md                │ │
│ │ - 统一的 L2-L7 网络诊断专家                          │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Agent Layer (DeepAgents + Custom SkillAdapter)│
│ ┌──────────────┐  ┌──────────────┐                     │
│ │ QueryAgentV2 │  │ Orchestrator │                     │
│ └──────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Layer 3: Cache Layer (Exact Match)                     │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ semantic_cache (query_text PRIMARY KEY)            │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```\n```

---

### 问题 3: `.claude/claude.md` Line 349-362 - Implementation Rules

**当前内容**: Tier 1/Tier 2 规则（包含 confidence）

**应该改为**: Tier 0/Tier 1 精确匹配规则

**修复方法**:
替换为:
```markdown
**实现规则**:
1. **Tier 0 (Exact Cache)**:
   - 精确字符串匹配: `WHERE query_text = ?`
   - 返回值: `result | None` (simple true/false)
   - ❌ **禁止**: `array_cosine_similarity()`, `confidence > 0.95`

2. **Tier 1 (Network Expert)**:
   - 使用 DeepAgents ReAct 引擎
   - 加载 `network-expert` Skill
   - 缓存成功查询到 Tier 0
```

---

## 📝 新增文档

### `docs/98_cleanup_checklist.md` ⭐

**完整的垃圾代码清理指南**，包含:

#### 🔴 立即删除的代码

1. **置信度相关代码**:
   ```bash
   rm src/olav/core/memory_manager.py
   # 删除 array_cosine_similarity() 调用
   # 删除 semantic_threshold 变量
   ```

2. **Fallback 代码**:
   ```python
   # ❌ 禁止业务层 fallback
   try:
       result = execute_sql(query)
   except:
       result = execute_cli(query)  # 禁止
   
   # ✅ 允许技术层 fallback
   if shutil.which("rg"):
       return subprocess.run(["rg", pattern])
   else:
       return subprocess.run(["grep", pattern])  # 允许
   ```

3. **Legacy 专家代码**:
   ```bash
   rm -rf src/olav/analysis/
   find src/olav -name "*routing_expert*" -delete
   ```

#### 🟡 需要重构的代码

- `core/query_router.py` - 删除 `fallback` 字段
- `core/unified_database.py` - 删除 `search_semantic_cache()`
- `agents/intent_agent.py` - 删除 `confidence > 0.95`

#### 📋 清理验证清单

```bash
grep -rn "confidence" src/olav/ | grep -v "test" | wc -l  # 应为 0
grep -rn "similarity" src/olav/ | grep -v "test" | wc -l  # 应为 0
grep -rn "sql.*fallback.*cli" src/olav/ -i | wc -l  # 应为 0
ls src/olav/analysis/  # 应不存在
ls src/olav/core/memory_manager.py  # 应不存在
```

#### 🔧 自动化清理脚本

```bash
#!/bin/bash
# scripts/cleanup_v098.sh

rm -f src/olav/core/memory_manager.py
rm -rf src/olav/analysis/
rm -rf .olav/agent_cache/ (if not used)

uv run ruff check src/ --fix
uv run ruff format src/
uv run pytest tests/00_e2e_acceptance_test.py::TestCodeQuality -v
```

---

## 🎯 下一步行动

### 立即执行 (手动)

1. **修复 `.claude/claude.md`**:
   ```bash
   vim .claude/claude.md
   # 修复 Line 345, 306-337, 349-362
   ```

2. **执行垃圾代码清理**:
   ```bash
   bash scripts/cleanup_v098.sh
   # 或手动按照 docs/98_cleanup_checklist.md 执行
   ```

3. **验证修复**:
   ```bash
   grep -r "v0.10" .claude/ docs/  # 应为空或仅 roadmap.md
   grep -rn "confidence.*0.9" src/olav/  # 应为空
   grep -rn "semantic.*cache.*vector" src/olav/ -i  # 应为空
   ```

### Agent 使用指南

**更新后的文档优先级**:
1. ⭐ `docs/98_cleanup_checklist.md` - 了解哪些代码禁止
2. ⭐ `.claude/claude.md` - 架构决策和禁止模式
3. ⭐ `docs/100_audit_report.md` § 0.5 - 立即行动清单
4. `docs/66_ralph_instruction.md` - 循环开发流程

---

## ✅ 验收标准

**修复完成后执行**:

```bash
# 1. 无 v0.9.8 引用（除了 roadmap.md）
grep -r "v0.10" .claude/ | wc -l
# 预期: 0

# 2. 无置信度代码
grep -rn "confidence.*>" src/olav/ | grep -v "test\|#" | wc -l
# 预期: 0

# 3. 无语义搜索
grep -rn "array_cosine_similarity" src/olav/ | wc -l
# 预期: 0

# 4. 无业务层 fallback
grep -rn "sql.*fallback.*cli" src/olav/ -i | wc -l
# 预期: 0

# 5. E2E 测试通过
uv run pytest tests/00_e2e_acceptance_test.py -v
# 预期: ALL PASSED ✅
```

---

**总结**:
- ✅ v0.9.8 → v0.9.8 (自动修复完成)
- ⚠️ `.claude/claude.md` 需手动修复3处
- ✅ 垃圾代码清理清单已创建
- ⏸️ 等待执行清理脚本

**预计工时**: 1-2小时（手动修复 + 清理验证）
