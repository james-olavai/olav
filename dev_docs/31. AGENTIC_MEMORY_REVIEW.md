# OLAV Agentic Memory 架构审查

> 审查日期：2026-03-15  
> 范围：Memory Cache 与 Long-Term Memory 系统

---

## 一、当前实现全景

### 系统中的记忆层

```
用户输入
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  OLAVAgent.ainvoke()                                            │
│                                                                  │
│  ① AutoRecallMiddleware.enrich()    ← LanceDB memory 表          │
│     (Pre-processor: 注入历史记忆到 prompt)                         │
│                                                                  │
│  ② GuardrailInjector.get_block()    ← LanceDB memory[audit]     │
│     (注入历史失败经验为约束条件)                                    │
│                                                                  │
│  ③ graph.ainvoke()                                               │
│     ├── LangChain SQLiteCache   (LLM 响应缓存)                    │
│     ├── DuckDBSaver             (会话状态持久化)                   │
│     └── LangGraphLanceDBStore   (LangGraph BaseStore 接口)        │
│                                                                  │
│  ④ AutoCaptureMiddleware.process()  ← LanceDB memory 表          │
│     (Post-processor: 提取事实/决策存入 LTM)                        │
└──────────────────────────────────────────────────────────────────┘
```

### 组件一览

| 组件 | 类 / 位置 | 存储后端 | 作用 |
|:---|:---|:---|:---|
| **LangChain LLM Cache** | `SQLiteCache` | `~/.olav/cache/{user}/llm_cache.db` | 相同 prompt 不重复调用 LLM |
| **LangGraph Checkpointer** | `DuckDBSaver` (`core/checkpointer.py`) | `~/.olav/cache/{user}/{agent}/checkpoints.db` | 会话消息历史跨重启持久化 |
| **LangGraph BaseStore** | `LangGraphLanceDBStore` (`core/memory/langgraph_adapter.py`) | LanceDB `memory` 表 | DeepAgents `store=` 接口，Agent 自主 get/put 记忆 |
| **Semantic Cache (Tier-0)** | `SemanticCache` (`core/memory/__init__.py`) | LanceDB `query_cache` 表 | 缓存 `hybrid_search()` 结果，相似查询（≥98%）直接返回 |
| **Long-Term Memory (OCM)** | `LanceDBStore` (`core/memory/__init__.py`) | LanceDB `memory` 表 | 核心 LTM：fact / decision / preference / audit 四类记忆 |
| **Auto-Recall** | `AutoRecallMiddleware` (`core/memory/middleware.py`) | LanceDB `memory` 表 | 每次调用前自动注入相关历史记忆到 prompt |
| **Auto-Capture** | `AutoCaptureMiddleware` (`core/memory/middleware.py`) | LanceDB `memory` 表 | 每次成功调用后，用 LLM 提取事实/决策存入 LTM |
| **Guardrail Injector** | `GuardrailInjector` (`core/memory/guardrails.py`) | LanceDB `memory`（audit 类别） | 注入历史失败约束到 user message |
| **Knowledge Base** | `KnowledgeBase` (`core/knowledge/__init__.py`) | LanceDB `kb_chunks` 表 | 文档 RAG（Markdown / PDF），Hybrid 检索 |
| **recall_memory tool** | `.olav/workspace/ops/tools/recall_memory.py` | LanceDB `memory` 表 | Agent 主动查询 LTM 的工具 |

---

## 二、已识别问题

### 🔴 BUG-1：LanceDB 数据库路径双轨隔离

**严重性**：高。导致记忆系统实质上分裂为两套，互不可见。

**原因**：

```python
# agents/agent.py L199
db_path = self.olav_base_path / "databases" / "memory.lancedb"  # ← .lancedb
self.store = LangGraphLanceDBStore(db_path=str(db_path))

# core/memory/__init__.py L25
DEFAULT_MEMORY_DB = ".olav/databases/memory.lance"              # ← .lance (不同!)
```

**影响**：

| 写入方 | 路径 | 读取方 | 能否看到？ |
|:---|:---|:---|:---|
| `LangGraphLanceDBStore` (DeepAgents store) | `memory.lancedb` | AutoRecall | ❌ 看不到 |
| `AutoCapture` | `memory.lance` | LangGraph BaseStore | ❌ 看不到 |
| `recall_memory` 工具 | `memory.lance` | LangGraph BaseStore | ❌ 看不到 |

**修复方案**：

```python
# agents/agent.py — 修改 L199，对齐路径
db_path = self.olav_base_path / "databases" / "memory.lance"
```

或者反过来，统一到 `memory.lancedb`，并更新 `DEFAULT_MEMORY_DB`。选一个即可，保持一致。

---

### 🔴 PERF-1：SentenceTransformer Embedder 多实例

**严重性**：高（内存浪费 ~450-540MB）。

**原因**：以下 6 处各自懒加载同一个模型 `BAAI/bge-small-en-v1.5`：

1. `AutoRecallMiddleware._embed()`
2. `AutoCaptureMiddleware._embed()`
3. `GuardrailInjector._embed()`
4. `LangGraphLanceDBStore._embed()`
5. `recall_memory` 工具（函数内 inline）
6. `KnowledgeBase._embed()`

每个模型实例约占 ~90MB。同一进程运行时可能存在 6 个实例。

**修复方案**：提取全局单例：

```python
# 新建 olav/core/embedder.py
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)
_embedder = None

def get_embedder(model: str = "BAAI/bge-small-en-v1.5"):
    """Get or create the shared SentenceTransformer embedder singleton."""
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer(model)
            logger.info(f"✓ Shared embedder loaded: {model}")
        except Exception as e:
            logger.warning(f"Embedder unavailable: {e}")
            _embedder = False
    return _embedder if _embedder else None
```

所有组件替换为 `from olav.core.embedder import get_embedder`。

---

### ⚠️ BUG-2：AutoCapture 在同步上下文中静默失败

**严重性**：中。导致 LTM 学习在 CLI 模式下可能从不执行。

**原因**：

```python
# agents/agent.py L450-453
asyncio.ensure_future(           # ← 在无 running loop 时静默跳过
    self._auto_capture.process(_original_input, result, scope=scope)
)
```

`asyncio.ensure_future()` 要求存在 running event loop。在 CLI 同步调用路径（`invoke()` → `asyncio.run()` → 已结束的 loop）中，AutoCapture **从不运行**。

**修复方案**：

```python
# 在 ainvoke 结束前 await，并加超时保护
if self._auto_capture is not None:
    try:
        await asyncio.wait_for(
            self._auto_capture.process(_original_input, result, scope=scope),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.debug("AutoCapture: timed out (non-fatal)")
    except Exception as _ce:
        logger.debug(f"AutoCapture: {_ce}")
```

---

### ⚠️ PERF-2：SemanticCache 缺少快照更新后的失效机制

**严重性**：中。导致快照刷新后，记忆搜索返回过期结果。

**场景**：
1. 用户运行 `take_snapshot` → DuckDB 快照数据更新
2. 新的 LTM 记忆被 AutoCapture 写入
3. 但 `query_cache` 表中的旧结果仍被 `SemanticCache` 返回（TTL=24h）

**修复方案**：在 `take_snapshot` 成功后，调用：

```python
from olav.core.memory import get_store, SemanticCache
cache = SemanticCache(get_store())
cache.invalidate_all()  # 使缓存失效，下次查询重建
```

或者降低 `cache_ttl_hours` 至 1-2h（适合频繁更新的网络运维场景）。

---

### ⚠️ PERF-3：recall_memory 工具每次调用重新加载 embedder

**严重性**：中（每次工具调用增加 1-2s 延迟）。

**原因**：

```python
# .olav/workspace/ops/tools/recall_memory.py L93-95
from sentence_transformers import SentenceTransformer
_embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")  # ← 函数内局部变量，每次调用重建
```

该变量在 `recall_memory` 函数作用域内，每次 Agent 调用工具都重新加载模型。

**修复方案**：改为模块级变量（或使用统一的 `get_embedder()` 单例）。

---

### 🟢 OPT-1：KnowledgeBase 搜索没有 SemanticCache

**严重性**：低。

**现状**：`KnowledgeBase.search()` 直接做 vector+BM25 fusion，没有 Tier-0 cache。对于频繁查询同一文档（如 CCNP 手册），每次都重新计算。

**改进方案**：在 `KnowledgeBase.search()` 中接入 `SemanticCache`，使用独立的 `kb_query_cache` 表（已在代码里定义了 `KB_CACHE_TABLE = "kb_query_cache"`，但未使用）。

---

### 🟢 CLEANUP-1：未使用的 MemorySaver import

**严重性**：低（仅代码整洁问题）。

**位置**：`agents/agent.py` L21：

```python
from langgraph.checkpoint.memory import MemorySaver  # ← 已被 DuckDBSaver 替代，未使用
```

删除该 import 行。

---

## 三、优先级汇总

| 编号 | 类别 | 描述 | 优先级 | 修改文件 |
|:---|:---|:---|:---|:---|
| BUG-1 | Bug | LanceDB 路径双轨隔离 | 🔴 高 | `agents/agent.py` |
| PERF-1 | 性能 | Embedder 多实例（~540MB 浪费） | 🔴 高 | 新建 `core/embedder.py`，改 6 处调用 |
| BUG-2 | Bug | AutoCapture 异步失败 | ⚠️ 中 | `agents/agent.py` |
| PERF-2 | 性能 | SemanticCache 无快照失效 | ⚠️ 中 | `cli/` 或 snapshot 触发器 |
| PERF-3 | 性能 | recall_memory 工具每次重载 embedder | ⚠️ 中 | `recall_memory.py` |
| OPT-1 | 优化 | KnowledgeBase 无 SemanticCache | 🟢 低 | `core/knowledge/__init__.py` |
| CLEANUP-1 | 清理 | 未使用 `MemorySaver` import | 🟢 低 | `agents/agent.py` |

---

## 四、各层关系图（修复后目标状态）

```
用户 query
    │
    ▼
AutoRecall  ──────────────────────────────────┐
                                              │
                                     ┌────────▼────────┐
GuardrailInjector ──────────────────►│  memory.lance   │◄── AutoCapture
                                     │  (统一 LTM)     │
LangGraphLanceDBStore ──────────────►│  全局共享        │◄── recall_memory 工具
                                     └────────┬────────┘
                                              │
                                     ┌────────▼────────┐
                                     │ SemanticCache   │
                                     │ query_cache 表  │
                                     │ (TTL=1-2h)      │
                                     └─────────────────┘

短期缓存（独立）
  ├── SQLiteCache  → llm_cache.db  (LLM 响应)
  └── DuckDBSaver  → checkpoints.db (会话历史)

知识库（独立）
  └── KnowledgeBase → kb_chunks 表 (文档 RAG)
```

---

## 五、参考

- `src/olav/agents/agent.py` — OLAVAgent，记忆中间件集成点
- `src/olav/core/memory/__init__.py` — LanceDBStore, SemanticCache, hybrid_search
- `src/olav/core/memory/middleware.py` — AutoRecallMiddleware, AutoCaptureMiddleware
- `src/olav/core/memory/guardrails.py` — GuardrailInjector
- `src/olav/core/memory/langgraph_adapter.py` — LangGraphLanceDBStore
- `src/olav/core/knowledge/__init__.py` — KnowledgeBase
- `.olav/workspace/ops/tools/recall_memory.py` — recall_memory 工具
