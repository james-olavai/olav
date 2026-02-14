# OLAV v0.9.8 垃圾代码清理清单 (Cleanup Checklist)

**日期**: 2026-01-31  
**版本**: v0.9.8  
**原则**: 零垃圾代码、零fallback、零置信度分层

---

## 🔴 立即删除的代码 (Immediate Deletion)

### 1. 置信度相关代码 (Confidence/Similarity)

**禁止原因**: v0.9.8 使用精确匹配，不使用置信度分层

**搜索命令**:
```bash
grep -rn "confidence" src/olav/
grep -rn "similarity" src/olav/
grep -rn "array_cosine_similarity" src/olav/
grep -rn "semantic_threshold" src/olav/
```

**需要删除的文件**:
```bash
# memory_manager.py 整个文件（v0.9.8 功能）
rm src/olav/core/memory_manager.py

# embeddings.py 中的向量搜索逻辑
# 保留基本embedding功能（用于知识库），删除缓存相关
```

**需要修改的代码**:
```python
# ❌ 删除这类代码
def search_semantic_cache(self, embedding, threshold=0.95):
    similarity = array_cosine_similarity(embedding, cached_embedding)
    if similarity > threshold:
        return cached_result

# ✅ 替换为精确匹配
def search_cache(self, query_text):
    result = self.conn.execute(
        "SELECT * FROM semantic_cache WHERE query_text = ?",
        [query_text]
    ).fetchone()
    return result if result else None
```

---

### 2. Fallback 代码 (禁止所有 Fallback)

**禁止原因**: Agent 应该自主决策，不应有硬编码的 fallback 逻辑

**搜索命令**:
```bash
grep -rn "fallback" src/olav/ | grep -v "# " | grep -v "test"
```

**需要删除的代码类型**:

#### A. SQL → CLI Fallback (禁止)
```python
# ❌ 禁止
def query_network(query):
    try:
        result = execute_sql(query)
    except:
        # Fallback to CLI
        result = execute_cli(query)
    return result

# ✅ 正确: Agent 自主决策
# Agent 在 ReAct 循环中自行判断使用 SQL 还是 CLI
```

**需要清理的文件**:
- `src/olav/agents/orchestrator.py` - 删除任何 `sql_fails → try_cli` 逻辑
- `src/olav/core/query_router.py` - 删除 `fallback` 字段和相关逻辑

#### B. 工具级 Fallback (允许，但需审查)

**允许的 Fallback**（技术层面，非业务逻辑）:
```python
# ✅ 允许: ripgrep → grep → Python (工具级)
def search_file(pattern):
    if shutil.which("rg"):
        return subprocess.run(["rg", pattern])
    elif shutil.which("grep"):
        return subprocess.run(["grep", pattern])
    else:
        return python_search(pattern)  # 纯 Python fallback

# ✅ 允许: Scrapli → Netmiko (SSH 连接库)
def connect_device(host):
    try:
        return scrapli_connect(host)
    except ScrapliError:
        return netmiko_connect(host)
```

**禁止的 Fallback**（业务逻辑层面）:
```python
# ❌ 禁止: 查询层面的 fallback
def get_bgp_status(device):
    try:
        return query_database(device)  # SQL
    except:
        return run_cli_command(device, "show bgp")  # 业务 fallback

# ✅ 正确: Agent 决策
# Agent: "I need BGP status. Let me check DB first... no data, I'll use CLI."
```

---

### 3. Legacy 专家代码

**需要检查并删除**:
```bash
# 检查是否还存在
find src/olav -name "*expert*.py" -o -name "*specialist*.py"

# 应该只保留:
# - src/olav/agents/query_agent_v2.py (通用 Agent)
# - src/olav/agents/orchestrator.py (Meta-Agent)

# 删除以下文件（如果存在）:
# - src/olav/experts/ 目录
# - src/olav/agents/*_expert.py
# - src/olav/agents/*_specialist.py
```

---

### 4. 分析代码目录

**已确认存在** (需要删除):
```bash
# 整个目录删除
rm -rf src/olav/analysis/

# 检查是否有引用
grep -r "from olav.analysis" src/
grep -r "import olav.analysis" src/

# 如果有引用，先删除引用再删除目录
```

---

### 5. Agent Cache 文件 (如果未使用)

**检查使用情况**:
```bash
# 搜索代码引用
grep -r "agent_cache" src/olav/
grep -r "bgp.duckdb" src/olav/
grep -r "cli.duckdb" src/olav/

# 如果输出为空或只有注释，删除
rm -rf .olav/agent_cache/
```

---

## 🟡 需要重构的代码 (Refactoring Required)

### 1. query_router.py

**需要删除**:
- `fallback` 字段
- `should_fallback_to_cli()` 方法
- `get_fallback_strategy()` 方法
- `semantic_threshold` 变量

**保留**:
- 斜杠命令路由
- 正则模式匹配
- LLM 意图分类（如果需要）

### 2. unified_database.py

**需要修改**:
```python
# ❌ 删除
def search_semantic_cache(self, embedding, threshold):
    ...

# ✅ 替换为
def search_cache(self, query_text: str) -> dict | None:
    """精确匹配查询缓存"""
    result = self.conn.execute(
        "SELECT * FROM commands.main.semantic_cache WHERE query_text = ?",
        [query_text]
    ).fetchone()
    return result
```

**需要删除的表列**:
```sql
-- 执行 schema 迁移
ALTER TABLE commands.main.semantic_cache 
DROP COLUMN IF EXISTS query_embedding;

ALTER TABLE commands.main.semantic_cache 
DROP COLUMN IF EXISTS confidence;

-- 添加 hit_count (可选)
ALTER TABLE commands.main.semantic_cache 
ADD COLUMN IF NOT EXISTS hit_count INTEGER DEFAULT 0;
```

### 3. Intent Agent (如果使用)

**删除置信度检查**:
```python
# ❌ 删除
if cached and cached['confidence'] > 0.95:
    return self._execute_plan(cached['execution_plan'])

# ✅ 替换为
if cached:  # 精确命中即执行
    return self._execute_plan(cached['execution_plan'])
```

---

## 🟢 允许保留的代码 (Allowed to Keep)

### 1. 技术层 Fallback

**文件**: `src/olav/tools/sync_tools.py`
- ✅ `Scrapli → Netmiko fallback` (SSH 连接层)
- ✅ `ripgrep → grep → Python fallback` (搜索工具层)

**文件**: `src/olav/tools/network_executor.py`
- ✅ `TextFSM parsing → raw text fallback` (解析层)

**原因**: 这些是技术实现细节，不是业务逻辑 fallback

### 2. 默认值 Fallback

```python
# ✅ 允许: 配置默认值
config.get("timeout", 30)  # Fallback to 30

# ✅ 允许: 目录查找
snapshot_dir = find_snapshot_dir() or default_dir
```

---

## 📋 清理验证清单

**执行以下命令验证清理完成**:

```bash
# 1. 无置信度代码
grep -rn "confidence" src/olav/ | grep -v "test" | grep -v "#"
# 预期: 空输出

# 2. 无语义相似度
grep -rn "similarity" src/olav/ | grep -v "test" | grep -v "#"
# 预期: 空输出

# 3. 无业务层 fallback
grep -rn "sql.*fallback.*cli" src/olav/ -i
# 预期: 空输出

# 4. 无 analysis 目录
ls src/olav/analysis/
# 预期: No such file or directory

# 5. 无 memory_manager
ls src/olav/core/memory_manager.py
# 预期: No such file or directory

# 6. 无子专家文件
find src/olav -name "*routing_expert*" -o -name "*switching_expert*"
# 预期: 空输出

# 7. E2E 测试通过
uv run pytest tests/00_e2e_acceptance_test.py -v
# 预期: ALL PASSED ✅
```

---

## 🔧 清理脚本

**自动化清理脚本** (`scripts/cleanup_v098.sh`):

```bash
#!/bin/bash
set -e

echo "🧹 OLAV v0.9.8 垃圾代码清理..."

# 1. 删除 memory_manager
echo "删除 memory_manager.py..."
rm -f src/olav/core/memory_manager.py

# 2. 删除 analysis 目录
echo "删除 analysis/ 目录..."
rm -rf src/olav/analysis/

# 3. 删除 agent_cache (如果未使用)
echo "检查 agent_cache 使用情况..."
if ! grep -rq "agent_cache" src/olav/; then
    echo "删除未使用的 agent_cache..."
    rm -rf .olav/agent_cache/
fi

# 4. 检查并移除未使用的导入
echo "修复 ruff 问题..."
uv run ruff check src/ --fix
uv run ruff format src/

# 5. 运行测试验证
echo "运行测试..."
uv run pytest tests/00_e2e_acceptance_test.py::TestCodeQuality -v

echo "✅ 清理完成！"
echo "📝 请手动检查并修复以下内容:"
echo "   1. query_router.py - 删除 fallback 字段"
echo "   2. unified_database.py - 删除 search_semantic_cache()"
echo "   3. intent_agent.py - 删除置信度检查"
```

**执行**:
```bash
chmod +x scripts/cleanup_v098.sh
./scripts/cleanup_v098.sh
```

---

## 📝 手动清理检查点

**开发者必须手动检查**:

| 文件 | 检查项 | 行动 |
|:---|:---|:---|
| `core/query_router.py` | 删除 `fallback` 字段 | 重构路由逻辑 |
| `core/unified_database.py` | 删除 `search_semantic_cache()` | 改为 `search_cache()` |
| `agents/orchestrator.py` | 删除 SQL→CLI fallback | Agent 自主决策 |
| `agents/intent_agent.py` | 删除 `confidence > 0.95` | 改为 `if cached:` |

---

## 🎯 清理后架构

**最终状态**:
- ✅ 精确匹配缓存（无置信度）
- ✅ 统一网络专家（无子专家）
- ✅ 零业务 fallback（Agent 自主决策）
- ✅ 零垃圾代码（删除 analysis, memory_manager）

**验收标准**:
```bash
# 所有检查通过
uv run ruff check src/
uv run pyright src/
uv run pytest tests/00_e2e_acceptance_test.py -v
grep -r "confidence.*0.9" src/olav/ | wc -l  # 应为 0
grep -r "sql.*fallback.*cli" src/olav/ -i | wc -l  # 应为 0
```

---

**更新日期**: 2026-01-31  
**负责人**: Development Team  
**预计工时**: 2-3小时
