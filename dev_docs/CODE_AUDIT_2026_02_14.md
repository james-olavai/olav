# OLAV 代码审计报告

**日期**: 2026-02-14  
**审计范围**: 全量代码库 (src/olav, .olav, config, tests, scripts)  
**代码库版本**: pyproject.toml v0.9.8 / 文档标记 v0.11.5  
**审计目标**: 识别技术债、架构问题、DeepAgents利用不足、造轮子问题、功能割裂

---

## 目录

1. [总体评价](#1-总体评价)
2. [架构层面问题](#2-架构层面问题)
3. [DeepAgents能力利用不足](#3-deepagents能力利用不足)
4. [造轮子问题](#4-造轮子问题reinvented-wheels)
5. [死代码与僵尸模块](#5-死代码与僵尸模块)
6. [重复实现](#6-重复实现)
7. [安全漏洞](#7-安全漏洞)
8. [功能割裂问题](#8-功能割裂问题)
9. [配置与依赖问题](#9-配置与依赖问题)
10. [测试体系问题](#10-测试体系问题)
11. [分级改进建议](#11-分级改进建议)
12. [文件级详细问题清单](#12-文件级详细问题清单)

---

## 1. 总体评价

### 优势
- **技能-Agent解耦架构清晰**: `.olav/skills/` 定义技能配置, `src/olav/` 实现Agent逻辑, 方向正确
- **配置层次分明**: `.env` > `settings.json` > `SKILL.md` > `settings.py`, Pydantic v2 验证
- **Guard多级路由管道**: 4阶段分类(regex→cache→heuristic→LLM), 设计精巧
- **多LLM提供者支持**: 7个provider (OpenAI, Ollama, Azure, xAI, Anthropic, Groq, Mistral)
- **文档质量高**: 用户指南完善, SKILL.md规范化程度好

### 核心问题

| 问题类别 | 严重程度 | 影响范围 |
|----------|----------|----------|
| **DeepAgents async弃用, 同步回退绕开框架** | 🔴 Critical | 全系统 |
| **SQL注入漏洞** | 🔴 Critical | API层 |
| **3套独立缓存实现** | 🟡 High | 性能/维护 |
| **Guard-Orchestrator职责重叠** | 🟡 High | 路由逻辑 |
| **~15个死代码文件/功能** | 🟡 High | 维护负担 |
| **DeepAgents原生能力未利用** | 🟡 High | 架构愿景 |
| **scripts/ 目录35个脚本无人维护** | 🟠 Medium | 代码卫生 |
| **12个pyproject依赖未使用** | 🟠 Medium | 安装体积 |
| **异步/同步混合模式** | 🟠 Medium | 代码一致性 |
| **LLM能力未充分利用（靠regex做routing）** | 🟠 Medium | 系统智能 |

---

## 2. 架构层面问题

### 2.1 DeepAgents被架空 — 同步回退成为事实上的主路径

**状态**: `orchestrate_query_sync()` 是实际执行路径, DeepAgents `create_deep_agent()` 在 `router.py` 中虽然创建了, 但主流查询根本不走它。

```
用户查询 → Guard.classify()
  ├─ SIMPLE → ExecutionDispatcher._execute_simple_route()
  │            └─ 直接调用 orchestrate_query_sync()  ← 完全绕过DeepAgents
  ├─ CLI    → ExecutionDispatcher._execute_cli_route()
  │            └─ 直接调用网络执行器              ← 完全绕过DeepAgents
  ├─ EXPERT → ExecutionDispatcher._delegate_to_orchestrator()
  │            └─ 也是调用 orchestrate_query_sync() ← 仍然绕过DeepAgents
  └─ UNKNOWN → 同上
```

**根因**: 
- DeepAgents `ainvoke()` 与 OpenRouter 等 非标OpenAI端点不兼容(async挂起)
- 开发者选择了"同步回退"作为workaround
- `create_orchestrator()`/`create_collaborative_orchestrator()`/`create_planning_orchestrator()` 三个工厂函数创建的Agent实际上无法确认被调用

**影响**:
- DeepAgents的SubAgent路由、中间件栈(Summarization, TodoList)、CheckPointer全部失效
- `router.py` ~300行代码在SIMPLE/CLI路径下完全不执行
- 整个项目声称基于DeepAgents, 实际是"直接LLM调用 + SQL执行"的简单管道
- 协作模式(`_execute_with_dependencies_order`)、规划模式(`create_planning_orchestrator`)名存实亡

### 2.2 Guard与Orchestrator职责混乱

项目有**两层路由**:

1. **Guard** (`agents/guard.py`): 4阶段管道(regex→cache→heuristic→LLM) → RouteCode (SIMPLE/CLI/EXPERT/...)
2. **Orchestrator** (`agents/router.py`): DeepAgents SubAgent routing with complexity scoring

实际运行中:
- Guard做完分类后, `ExecutionDispatcher` 直接执行, **从不真正经过Orchestrator**
- Orchestrator SKILL.md的复杂度评分逻辑(0.0-1.0) **被Guard管道完全取代**
- 文档中描述的"Phase 0-4"六阶段处理流程, 实际只有Guard → Dispatcher

**建议**: 二选一 — 要么让Guard做全部路由(当前事实), 要么让DeepAgents Orchestrator做路由(愿景目标)。当前两者并行, 但只有Guard生效。

### 2.3 Agent间协作能力为零

文档愿景:
- Expert Agent请求CLI数据 → `<need_cli_data>` 标记 → Orchestrator收集 → 返回Expert
- Query Agent升级 → `<escalate_to_expert>` 标记 → Expert处理

实际实现:
- `orchestrate_query_sync()` 是一个**单次** LLM→SQL→执行 管道
- 没有任何代码实现 `<need_cli_data>` 的闭环 (Orchestrator侧检测了标记, 但没有编排CLI→Expert的回路)
- `<escalate_to_expert>` 标记被检测但无后续处理
- 没有Agent间通信、共享状态或消息传递

### 2.4 LLM能力利用不足

Guard路由核心是**regex匹配和关键字检测**, 只有当heuristic置信度<0.75时才回落到LLM:

```python
# security_classifier.py — 大量硬编码regex模式
for pattern in self.simple_indicators:
    try:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return ("SIMPLE", 0.90, reasoning, intent)
```

**问题**:
- 自然语言路由本该是LLM的强项, 却用regex做主力
- 新增路由类型需要修改SKILL.md中的模式列表, 而非让LLM学习
- 在SKILL.md中定义了"分类系统提示词", 但仅作为Stage 4回退

---

## 3. DeepAgents能力利用不足

### 3.1 已使用的DeepAgents API (仅4个)

| API | 位置 | 用途 |
|-----|------|------|
| `create_deep_agent()` | `router.py:17` | 创建Agent (但Agent可能未真正调用) |
| `SubAgent` | `subagent_loader.py:36` | 定义SubAgent配置数据类 |
| `SummarizationMiddleware` | `router.py:148` | 对话摘要中间件 |
| `CompositeBackend/FilesystemBackend/StateBackend` | `storage.py:22-29` | 存储后端 |

### 3.2 未使用的DeepAgents能力

| 原生能力 | 状态 | 应有用途 |
|----------|------|----------|
| **SubAgent路由 (自动)** | ❌ 未使用 | 应由DeepAgents自动选择子Agent, 而非Guard regex |
| **TodoListMiddleware** | ❌ 未使用 | 多步任务规划 (文档中提到但`create_planning_orchestrator`是空壳) |
| **DuckDBSaver checkpointer** | ❌ router.py设为None | 对话持久化/状态恢复 |
| **DuckDBStore** | ❌ 仅在data_gateway中用于数据存储 | 应作为Agent记忆长期存储 |
| **ReAct Loop** | ⚠️ analyzer.py用了LangGraph | 但单独构建, 未整合进DeepAgents |
| **ainvoke() 异步执行** | ❌ 已弃用 | 同步回退workaround |
| **Agent间消息传递** | ❌ 未使用 | Expert→CLI数据请求闭环 |
| **Middleware栈组合** | ⚠️ 仅Summarization | 缺少日志、安全、限流等中间件 |

### 3.3 LangGraph使用情况

LangGraph仅在 `analyzer.py` 中使用(`StateGraph`, `END`), 构建了一个独立的分析图:

```python
from langgraph.graph import END, StateGraph
```

但此图与DeepAgents完全独立, 没有通过DeepAgents的SubAgent机制注入。这导致两套状态管理并行。

**建议**: `analyzer.py` 的LangGraph图应该作为DeepAgents SubAgent的implementation注册, 而非独立运行。

---

## 4. 造轮子问题（Reinvented Wheels）

### 4.1 缓存系统 — 3套独立实现

| 实现 | 文件 | 存储方式 | 用途 |
|------|------|----------|------|
| `QueryCache` | `core/query_cache.py` (148行) | 文件系统 (SHA256 → JSON) | LLM查询结果缓存 |
| `QueryCache` (内存) | `core/database_enhancer.py` (550行) | 内存dict | 数据库查询缓存 |
| `CacheManager` | `agents/cache_manager.py` (243行) | DuckDB | Guard路由决策缓存 |

**应该怎么做**: 
- 使用LangGraph的`DuckDBSaver`/`DuckDBStore`作为统一缓存层
- 或用`cachetools.TTLCache` + SQLite (已有SQLite cache `olav_cache.db`)  
- DeepAgents有内置的状态持久化, 不需要自己造

### 4.2 Guard路由分类 — 自建4阶段管道

700+行代码 (guard.py + security_classifier.py + llm_router.py + cache_manager.py) 实现了一个"查询分类器", 包括:
- 危险模式正则匹配
- 实时关键字检测
- 启发式分类
- LLM回退分类
- DuckDB语义缓存

**应该怎么做**: 
- DeepAgents的SubAgent路由天然支持按能力自动选择Agent
- LLM本身就是最好的意图分类器 — 一个`structured_output`调用就能输出带confidence和reasoning的JSON
- 如需缓存分类结果, 挂一个`DuckDBSaver`作checkpointer即可

### 4.3 数据库管理 — 重复的连接管理

| 实现 | 文件 | 功能 |
|------|------|------|
| `DatabaseManager` | `core/database.py` (823行) | DuckDB连接+CRUD+Schema创建 |
| `UnifiedDatabase` | `core/unified_database.py` (442行) | 跨数据库查询+View创建 |
| `ConnectionPool` | `core/connection_pool.py` (318行) | 线程安全连接池 |
| `DatabaseEnhancer` | `core/database_enhancer.py` (550行) | 事务+批量操作 |
| `DataGateway` | `lib/data_gateway.py` (643行) | 平台无关数据访问层 |

**5个数据库相关模块, ~2,776行**, 做的只是DuckDB连接管理:
- `database.py` 和 `unified_database.py` 有重复的view创建SQL
- `connection_pool.py` 和 `database.py` 有重复的view创建逻辑
- `database_enhancer.py` 有断裂的import路径(`src.olav.core.connection_pool`), 疑似死代码
- `data_gateway.py` 每次查询都新建连接(无池化)

**应该怎么做**:
- DuckDB是嵌入式数据库, 一个连接实例足矣 (DuckDB内部是线程安全的)
- 统一为一个`database.py` + `get_database()` 单例

### 4.4 SKILL.md YAML解析 — 重复实现

| 实现 | 文件 | 功能 |
|------|------|------|
| `SkillLoader` | `core/skill_loader.py` (375行) | 加载SKILL.md frontmatter, 索引所有技能 |
| `SkillConfig` | `core/skill_config.py` (207行) | 加载SKILL.md frontmatter, 获取缓存/行为配置 |
| `GuardRulesLoader` | `core/guard_rules_loader.py` (397行) | 加载Guard SKILL.md的分类规则 |
| `LLMRouter._load_guard_prompt()` | `agents/llm_router.py:100` | 手动解析Guard SKILL.md |

4处独立的YAML/Markdown frontmatter解析, 每处都有自己的`---`分割逻辑。

**应该怎么做**: 统一用`python-frontmatter`库或`skill_loader.py`的单一实现。

### 4.5 配置管理 — 过度工程

`config/settings.py` 有 **1,125行**, 定义了 **13个嵌套Pydantic Settings类**, 包括:
- `AgentSettings` (~180行): 每个Agent的LLM配置
- `DatabaseSettings`, `GuardSettings`, `RoutingSettings`, `HITLSettings`
- `ExecutionSettings`, `RuntimeSettings`, `DiagnosisSettings`
- `ThresholdSettings`, `FeatureFlagSettings`, `CacheSettings`, `SyncSettings`

对于一个当前仅6个Agent的系统, 配置复杂度远超需要。许多设置项从未被读取。

### 4.6 结果分析 — LLM应该直接做

`core/result_analyzer.py` (168行) 调用LLM将SQL结果转换为Markdown摘要。但:
- `query_orchestrator.py` 里已经有LLM调用
- 应该在SQL生成的同一次LLM调用中, 让LLM直接返回用户友好的回答, 而非"生成SQL → 执行 → 再调LLM总结"的两步

### 4.7 命令注册 — 两个CommandRegistry

| 实现 | 文件 | 功能 |
|------|------|------|
| `CommandRegistry` | `core/registry.py` (456行) | 网络命令注册 + TextFSM模板查找 |
| `CommandRegistry` | `core/command_registry.py` (360行) | 从`_schema_catalog`发现命令 |

同名类、相似职责, 维护者容易混淆。

---

## 5. 死代码与僵尸模块

### 5.1 确认死代码

| 文件/模块 | 行数 | 证据 |
|-----------|------|------|
| `core/query_optimizer.py` | 63 | `init_query_optimization()` 是空函数(只log一行) |
| `core/database_enhancer.py` | 550 | import路径断裂 (`src.olav.core.connection_pool`) |
| `cli/commands/base.py` | 93 | `BaseCommand` ABC从未被任何命令类继承 |
| `agents/dependency_executor.py` (部分) | 200 | 协作模式从未真正触发 |
| `router.py:create_planning_orchestrator` | ~30 | 直接调用`create_orchestrator`, 无额外逻辑 |
| `router.py:create_collaborative_orchestrator` | ~30 | 同上 |
| `.olav/skills/orchestrator/` | 目录 | 空目录, 被`olav-orchestrator`取代 |
| `.olav/skills/command_learner/` | SKILL.md | Tools明确标记为"non-existent implementations" |
| `cli/session.py.bak` | 文件 | 备份文件 |
| 8个 `SKILL_old.md` 文件 | 分散 | skills目录下遗留旧版本 |
| `core/guard.py` | 200 | 与`agents/guard.py`功能重叠, 需确认调用链 |

### 5.2 scripts/ 目录 — 35个散乱脚本

包含: `benchmark_guard.py`, `demo_guard_cli.py`, `test_guard_e2e.py`, `test_query_agent_levels.py`等测试脚本, 以及`clean_old_cache.py`, `init_database.py`等工具脚本。

**问题**: 没有README, 没有维护, 可能依赖已删除的模块。建议迁移到`tests/scripts/`或删除。

### 5.3 未使用的pyproject.toml依赖

以下依赖在`src/`活跃代码中无引用:

| 依赖 | 状态 |
|------|------|
| `sqlalchemy>=2.0` | ❌ 0 imports in src/ |
| `networkx>=3.0` | ❌ 仅legacy archive引用 |
| `pyvis>=0.3.0` | ❌ 仅legacy archive引用 |
| `ddgs>=9.10.0` | ❌ 0 imports anywhere |
| `nornir-scrapli` | ⚠️ 需确认, 可能在tools里 |
| `scrapli` / `scrapli-community` | ⚠️ 同上 |
| `duckdb-engine>=0.17.0` | ⚠️ SQLAlchemy engine, 但SQLAlchemy未使用 |
| `langchain-text-splitters` | ⚠️ "Phase 4" 注释, 可能未实现 |
| `nest-asyncio` | ⚠️ 可能在session.py中使用 |
| `requests>=2.31.0` | ⚠️ httpx也安装了, 可能重复 |

---

## 6. 重复实现

### 6.1 汇总表

| 重复项 | 文件A | 文件B | 行数浪费 |
|--------|-------|-------|----------|
| 缓存系统 | query_cache.py | cache_manager.py + database_enhancer.py | ~400行 |
| 数据库连接 | database.py | connection_pool.py + database_enhancer.py + unified_database.py | ~800行 |
| SKILL.md解析 | skill_loader.py | skill_config.py + guard_rules_loader.py + llm_router.py | ~400行 |
| Guard模块 | core/guard.py | agents/guard.py | ~200行 |
| CommandRegistry | core/registry.py | core/command_registry.py | ~360行 |
| View创建SQL | unified_database.py | connection_pool.py | ~50行 |
| 导出检测 | security_classifier.py | query_orchestrator.py(行85) | ~30行 |
| LLM环境设置 | subagent_loader.py | router.py (出现3次) | ~30行 |
| `import os` | paths.py | 同文件出现两次 | 微量 |

**估计重复代码**: ~2,300行 (总代码22,750行的 ~10%)

---

## 7. 安全漏洞

### 7.1 🔴 CRITICAL: SQL注入 — api/v1/devices.py

```python
# devices.py:list_devices()
if vendor:
    conditions.append(f"vendor ILIKE '%{vendor}%'")  # 直接拼接用户输入!

# devices.py:get_device()
query = f"SELECT * FROM devices WHERE device_id = '{device_id}'"  # 直接拼接!
```

**对比**: 同项目的 `api/v1/data.py` 正确使用了参数化查询:
```python
# data.py — 正确做法
conn.execute(query, parameters)
```

**修复**: 所有SQL查询必须使用参数化查询。

### 7.2 🟡 CORS配置过宽

```python
# server.py
app.add_middleware(CORSMiddleware, allow_origins=["*"])
```

### 7.3 🟡 环境变量污染

`subagent_loader.py._setup_llm_environment()` 和 `router.py` (3处) 直接修改 `os.environ`:
```python
os.environ["OPENAI_API_KEY"] = settings.llm_api_key
os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
```

这在多用户/多线程场景下是不安全的。

### 7.4 🟠 MD5用于缓存key

`cache_manager.py` 使用MD5哈希:
```python
query_hash = hashlib.md5(query.encode()).hexdigest()
```

虽非安全场景, 但MD5已被废弃, 应使用SHA256(同项目的`query_cache.py`已用SHA256)。

---

## 8. 功能割裂问题

### 8.1 Guard路由与Orchestrator路由的断裂

Guard做了完整的路由分类, 但结果交给了`ExecutionDispatcher`直接执行, 而非交给Orchestrator统一调度。这导致:

- Guard的`RouteDecision`中的`export_requested`/`export_format`需要在Dispatcher、QueryOrchestrator两处重复处理
- Expert路由最终还是回到`orchestrate_query_sync()`, 走的是SQL查询路径, 而非真正的专家分析
- MULTI_AGENT路由在Dispatcher中有`_execute_multi_agent_route`但疑似未完成

### 8.2 CLI交互模式(`session.py`)与查询管道的断裂

`session.py` (1,195行) 维护了完整的对话历史、PromptToolkit会话、命令补全, 但:
- 查询执行走的是`orchestrate_query_sync()`, 不关心对话上下文
- LangGraph的checkpointer在router.py中被设为`None`
- session.py自己管理历史, Guard自己管理缓存, QueryCache自己管理缓存 — 三者不共享状态

### 8.3 数据收集(Snapshot)与数据查询(Query)的断裂

- `network-snapshot` Skill定义了SSH数据收集流程
- 收集的数据存入DuckDB的`parsed_outputs`表
- `network-query` Skill需要查询这些数据
- 但`query_orchestrator.py`动态发现schema, 需要`json_metadata.py`额外生成JSON字段引用
- 如果表是空的, 系统会生成一堆"DO NOT QUERY"警告, 而不是优雅地告知用户

### 8.4 Admin Agent的半成品状态

`admin_agent.py`:
- `handle_system_status` → `raise AdminException("System status not yet implemented")`
- `handle_cleanup_logs` → `raise AdminException("Log cleanup not yet implemented")`
- `handle_clear_cache` → `raise AdminException("Cache clearing not yet implemented")`
- `identify_intent()` 完全基于关键字匹配, 零LLM参与

### 8.5 LLM调用链: 生成SQL → 执行 → 再调LLM总结

当前主路径(`query_orchestrator.py`):
1. LLM调用1: 生成SQL (System Prompt + Schema + User Query)
2. 执行SQL获取结果
3. LLM调用2(`result_analyzer.py`): 将结果转为Markdown摘要

**问题**: LLM本身完全有能力在一次调用中同时输出SQL和对结果的预期解读格式。也可以用`structured_output`让LLM直接返回结构化JSON(包含SQL和自然语言回答)。

---

## 9. 配置与依赖问题

### 9.1 版本号不一致

- `pyproject.toml`: `version = "0.9.8"`
- `settings.json`: `"version": "0.8"`
- 文档: v0.11.1 ~ v0.11.5
- SKILL.md版本: v1.0.0 ~ v7.0.0

### 9.2 重复的import

`config/paths.py` 两次 `import os`:
- 第1行区域: `from pathlib import Path`后
- 第~115行: 再次 `import os`

### 9.3 `config/settings.py` 单文件过大 (1,125行)

13个嵌套Settings类全部在同一文件, 应拆分为:
- `config/settings/llm.py` — LLM配置
- `config/settings/agent.py` — Agent设置
- `config/settings/database.py` — 数据库设置
- etc.

### 9.4 无CI/CD配置

没有发现:
- `.github/workflows/`
- `Makefile`
- `tox.ini`
- `.pre-commit-config.yaml`

测试仅能手动运行。

---

## 10. 测试体系问题

### 10.1 测试文件分布

| 目录 | 文件数 | 状态 |
|------|--------|------|
| `tests/unit/` | 39 | 有专属agents/子目录 |
| `tests/e2e/` | 16 | 有.bak文件, 有README |
| `tests/integration/` | 16 | 有agents/子目录 |
| `tests/api/` | 存在 | 未深入读取 |
| `tests/performance/` | 存在 | 未深入读取 |
| `scripts/` | 35 | 大量test_*脚本在scripts/而非tests/ |

### 10.2 死测试与过时测试

- `test_real_scenarios.py.bak` — 备份文件
- `test_v0_12_0_pydantic_models.py` 和 `test_pydantic_models_v0_12_0.py` — 两个同名文件测试同一功能
- `test_database_enhancer.py` — 测试可能死掉的`database_enhancer.py`
- `scripts/` 中35个脚本: `test_guard_e2e.py`, `test_guard_phase2.py`等, 与`tests/`目录重复

### 10.3 conftest.py使用真实数据库

```python
# conftest.py
original_db = Path(".olav/db/olav.duckdb")
backup_db = Path(".olav/db/olav.duckdb.backup")
shutil.copy(original_db, backup_db)  # 备份生产数据库!
```

测试直接操作`.olav/db/olav.duckdb`, 而非使用隔离的临时数据库。`OLAV_DB_PATH`环境变量支持存在但未在conftest中使用。

---

## 11. 分级改进建议

### P0 — 立即修复 (安全 + 阻断性问题)

| # | 任务 | 估计工时 |
|---|------|----------|
| P0.1 | **修复SQL注入**: `api/v1/devices.py` 全部改为参数化查询 | 1h |
| P0.2 | **明确主路径**: 决定Guard+Dispatcher是否为最终架构, 若是则删除router.py中未使用的DeepAgents创建逻辑 | 2h |
| P0.3 | **版本号统一**: pyproject.toml, settings.json, 文档全部对齐 | 0.5h |

### P1 — 短期 (1-2天, 消除tech debt)

| # | 任务 | 估计工时 |
|---|------|----------|
| P1.1 | **删除确认死代码**: query_optimizer.py, database_enhancer.py, commands/base.py, session.py.bak, 8个SKILL_old.md, 空orchestrator/目录 | 1h |
| P1.2 | **统一缓存**: 将3套缓存合并为1套 (推荐基于DuckDB的, 删除文件系统和内存版) | 4h |
| P1.3 | **统一数据库模块**: 合并database.py和unified_database.py, 删除database_enhancer.py和connection_pool.py | 4h |
| P1.4 | **清理scripts/**: 有价值的迁入tests/, 其余删除 | 2h |
| P1.5 | **清理未使用依赖**: 从pyproject.toml移除sqlalchemy, networkx, pyvis, ddgs, duckdb-engine | 0.5h |
| P1.6 | **合并Guard模块**: core/guard.py和agents/guard.py合并或明确职责划分 | 2h |

### P2 — 中期 (1周, 架构对齐)

| # | 任务 | 估计工时 |
|---|------|----------|
| P2.1 | **恢复DeepAgents为主路径**: 解决ainvoke()与OpenRouter兼容问题, 或替换为LangGraph原生图 | 8h |
| P2.2 | **Agent间协作闭环**: 实现Expert→CLI数据请求→收集→返回Expert的完整流程 | 6h |
| P2.3 | **LLM驱动路由**: 用`structured_output`替代Guard的regex分类, 由LLM直接输出RouteCode+confidence | 4h |
| P2.4 | **统一SKILL.md解析**: 一个loader, 一种缓存 | 3h |
| P2.5 | **settings.py拆分**: 13个Settings类拆分到独立文件 | 3h |
| P2.6 | **添加CI/CD**: GitHub Actions基础工作流 (lint + unit test) | 2h |

### P3 — 长期 (1-2周, 平台通用化)

| # | 任务 | 估计工时 |
|---|------|----------|
| P3.1 | **Skill平台抽象层**: 定义Skill接口协议(Protocol), 使.olav/skills可在非DeepAgents平台运行 | 12h |
| P3.2 | **完成Admin Agent**: 实现system_status, cleanup_logs, clear_cache | 4h |
| P3.3 | **完成Command Learner**: 或正式废弃并删除skill目录 | 4h |
| P3.4 | **测试隔离**: conftest.py使用临时数据库, 不操作生产DB | 3h |
| P3.5 | **data_gateway.py连接池化**: 或统一使用core/database.py的连接 | 2h |

---

## 12. 文件级详细问题清单

### src/olav/agents/

| 文件 | 行数 | 问题 |
|------|------|------|
| `orchestrator.py` | 100 | 仅re-export, 本身无逻辑 — 考虑用`__init__.py`代替 |
| `router.py` | 300 | `os.environ`突变×3; `create_planning_orchestrator`和`create_collaborative_orchestrator`是空壳 |
| `query_orchestrator.py` | 511 | 导出检测逻辑与security_classifier重复; 两步LLM调用(生成SQL+总结)应合为一步 |
| `guard.py` | 350 | 与core/guard.py命名冲突; singleton用`Optional`+全局变量, 应用`functools.lru_cache` |
| `execution_dispatcher.py` | 644 | `_extract_devices()`硬编码设备名R1-R4/SW1-SW2; EXPERT路径最终走sync fallback |
| `security_classifier.py` | 301 | 大量regex模式应从配置加载(已部分实现) |
| `cache_manager.py` | 243 | MD5哈希; `INSERT OR REPLACE` DuckDB语法需验证 |
| `llm_router.py` | 210 | 手动解析SKILL.md(不用skill_loader); fallback prompt硬编码 |
| `analyzer.py` | 683 | 独立LangGraph图, 未整合进DeepAgents; 硬编码设备名`"router1"` |
| `inspector.py` | 315 | 同上, Map-Reduce模式正确但游离在主架构外 |
| `dependency_executor.py` | 200 | 协作模式DAG — 可能从未真正执行 |

### src/olav/core/

| 文件 | 行数 | 问题 |
|------|------|------|
| `database.py` | 823 | 与unified_database.py, connection_pool.py有重复view创建 |
| `unified_database.py` | 442 | 与database.py部分重叠 |
| `connection_pool.py` | 318 | DuckDB嵌入式数据库不需要连接池 |
| `database_enhancer.py` | 550 | **死代码** — 导入路径断裂`src.olav.core` |
| `query_cache.py` | 148 | 文件系统缓存, 与cache_manager.py的DuckDB缓存重复 |
| `query_optimizer.py` | 63 | **死代码** — 函数体为空 |
| `skill_loader.py` | 375 | 活跃, 但与skill_config.py有frontmatter解析重复 |
| `skill_config.py` | 207 | 与skill_loader.py重复YAML解析 |
| `guard_rules_loader.py` | 397 | 活跃, 但解析逻辑可复用skill_loader |
| `tool_registry.py` | 230 | `get_tools_by_skill()`是stub(pass); 使用`sys.path`突变 |
| `registry.py` | 456 | 与command_registry.py同名类`CommandRegistry` |
| `command_registry.py` | 360 | 同上 |
| `result_analyzer.py` | 168 | 额外LLM调用生成摘要, 应合入主查询流程 |
| `storage.py` | 215 | 重试import路径4层(backends→storage→报错), 说明对DeepAgents API不确定 |
| `json_metadata.py` | 137 | 动态JSON字段发现 — 设计正确但实现脆弱 |
| `script_engine.py` | 455 | "Skill-as-a-Tool"执行引擎 — 使用率待确认 |
| `schema_cache.py` | 200 | 活跃 |
| `llm.py` | 200 | 活跃, 设计合理 |
| `guard.py` | 200 | 与agents/guard.py命名冲突 |
| `dependency.py` | 364 | DAG依赖图 — 使用率待确认 |
| `subagent_loader.py` | 533 | `os.environ`突变; 活跃 |

### src/olav/cli/

| 文件 | 行数 | 问题 |
|------|------|------|
| `cli_main.py` | 1,319 | **过长** — 混合Guard+Orchestrator+显示逻辑, 函数内import |
| `session.py` | 1,195 | **过长** — 自管理对话历史, 与LangGraph checkpointer不协调 |
| `display.py` | 575 | 活跃, Rich UI |
| `input_parser.py` | 68 | 活跃, 精简 |
| `commands/base.py` | 93 | **死代码** — BaseCommand未被使用 |
| `commands/builtin.py` | 500 | 活跃, 斜杠命令 |
| `session.py.bak` | ? | **删除** |

### src/olav/api/

| 文件 | 行数 | 问题 |
|------|------|------|
| `server.py` | 738 | 引用不存在的`cache`模块; CORS `*` |
| `v1/devices.py` | 405 | **🔴 SQL注入** |
| `v1/data.py` | 252 | ✅ 正确使用参数化查询 |
| `v1/query.py` | 752 | `optimize_query()`异步/同步混用 |
| `v1/schema.py` | 195 | 活跃 |
| `v1/system.py` | 259 | CPU/内存指标硬编码为0.0 |

### .olav/skills/

| 技能目录 | 问题 |
|----------|------|
| `orchestrator/` | **空目录** — 删除 |
| `command_learner/` | Tools标记为"non-existent" — 废弃或补全 |
| `network-analysis/` | 引用不存在的表(`system_metrics`, `protocol_events`); 与network-expert重叠 |
| 8个目录有`SKILL_old.md` | 遗留文件, 删除 |
| `shared/` | 共享工具实现 — 活跃 |

### config/

| 文件 | 问题 |
|------|------|
| `settings.py` | 1,125行, 应拆分 |
| `paths.py` | `import os`重复; `GUARD_RULES_PATH`重复定义 |

---

## 附录: 代码行数统计

| 模块 | 文件数 | 估计行数 | 可消除行数 |
|------|--------|----------|------------|
| config/ | 6 | ~2,400 | ~200 (重复import, 可拆分但不减少) |
| core/ | 22 | ~5,900 | ~1,800 (dead: enhancer, optimizer, pool; dup: skill_config, registry) |
| agents/ | 12 | ~3,900 | ~600 (dead: dep_executor部分, planning/collab orch) |
| cli/ | 6 | ~3,750 | ~100 (dead: base.py, .bak) |
| lib/ | 2 | ~1,050 | ~200 (data_gateway连接逻辑可合并) |
| admin/ | 6 | ~1,650 | ~100 (断裂import) |
| api/ | 8 | ~2,600 | ~50 (修复, 非删除) |
| testing/ | 2 | ~1,320 | 0 |
| utils/ | 1 | ~155 | 0 |
| **总计** | **67** | **~22,750** | **~3,050 (~13%)** |

---

**审计人**: GitHub Copilot (Claude Opus 4.6)  
**审计日期**: 2026-02-14  
**下次审计建议**: P0修复后, P1完成后各做一次增量审计
