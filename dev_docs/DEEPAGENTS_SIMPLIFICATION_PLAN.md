# DeepAgents 原生架构精简方案

**版本**: v2.0 — 单 Agent + Skills 极简架构  
**日期**: 2026-02-14  
**状态**: 设计完成，等待审批  
**参考**: `dev_docs/CODE_AUDIT_2026_02_14.md`（代码审计报告）  
**变更**: v1.0 5-SubAgent → v2.0 单 Agent（基于架构讨论 2/14）

---

## 目录

1. [核心理念](#1-核心理念)
2. [现状问题总结](#2-现状问题总结)
3. [目标架构设计](#3-目标架构设计)
4. [数据库架构设计](#4-数据库架构设计)
5. [Skill 热插拔机制详解](#5-skill-热插拔机制详解)
6. [文件级精简计划](#6-文件级精简计划)
7. [目录结构设计](#7-目录结构设计)
8. [配置文件设计](#8-配置文件设计)
9. [测试策略与 TDD 实践](#9-测试策略与-tdd-实践)
10. [分阶段实施路线图](#10-分阶段实施路线图)
11. [代码示例](#11-代码示例)
12. [关键架构问题](#12-关键架构问题)
13. [风险与缓解](#13-风险与缓解)
14. [验收标准](#14-验收标准)

---

## 1. 核心理念

### 从 v1.0 到 v2.0 的架构演进

```
v1.0 方案：5 个 SubAgent (query, cli, expert, inspector, admin)
  问题：还是在做路由 — LLM 判断"该给哪个 SubAgent"
  问题：query/cli/expert/inspector 都在同一领域（网络），tools 只有 3 个
  问题：admin 不需要 LLM 做文件操作

v2.0 方案：1 个主 Agent + Skills 热加载
  核心：OLAV 是网络分析工具，一个 Agent + 3 个 Tools + N 个 Skills
  路由：零 — Agent 只有 3 个 tools，直接用
  知识：Skills progressive disclosure — 按用户问题热加载领域知识
  工具：admin/command-learner 是 /COMMAND，不需要 LLM

v2.1 关键洞察：DuckDB 作为统一数据层（2026-02-14）
  发现：smart_sql_query 是 schema-aware 的
  推论：新数据源（NetBox、Zabbix、OpenSearch）→ 导入 DuckDB + 加 Skill
  结论：90% 场景不需要新 tools，SubAgent 是过度设计
  架构：1 Agent + 3 Tools + N Skills + 1 Database (统一数据层)
```

### 设计哲学

```
1 Agent, 3 Tools, N Skills, 1 Database
Agent 做推理 — Tools 做执行 — Skills 做知识 — DuckDB 做统一数据层
不需要路由的架构 就是最好的架构

Schema-Aware 机制 = 零集成成本
新系统？导入数据 → 刷新 schema → 加 Skill → 完成
```

### 为什么不需要 SubAgent？

| 条件 | OLAV 情况 | 结论 |
|------|----------|------|
| Tools 数量 > 10？ | ❌ 只有 3 个 | 不需要拆分 |
| 不同领域？ | ❌ 全是网络 | 不需要隔离 |
| 需要不同模型？ | ❌ 用户选一个 provider | 不需要 per-agent 模型 |
| 会话超长？ | SummarizationMiddleware 处理 | 不需要 SubAgent 隔离 |
| 复杂多步任务？ | TodoListMiddleware + general-purpose | 不需要自定义 SubAgent |
| 新数据源（只读）？ | 导入 DuckDB + Skill | **零 tools，零 SubAgent** |

**关键洞察**：DuckDB + schema-aware = 统一数据层  
**集成新系统**：数据导入 → Skill（零代码）  
**SubAgent？**：Tools > 15 或需要不同执行环境时才考虑

---

## 2. 现状问题总结

> 详见 `dev_docs/CODE_AUDIT_2026_02_14.md`

| 问题 | 涉及文件 | 行数 | 核心矛盾 |
|------|----------|------|----------|
| DeepAgents 被完全绕过 | `query_orchestrator.py` | 511 | sync fallback 是实际路径 |
| Guard 4阶段管道 | `guard.py` + 3 个辅助 | ~1,077 | 1000行代码分类3个tools |
| ExecutionDispatcher | `execution_dispatcher.py` | 644 | if/elif 做 3 个tools 的工作 |
| 自定义 skill/subagent 加载 | 4个 loader 文件 | ~1,365 | DeepAgents 原生就能做 |
| 自定义会话管理 | `session.py` + `cli_main.py` | ~2,500 | Checkpointer 原生就能做 |
| 3 个缓存、5 个 DB 模块 | 8 个文件 | ~2,700 | 该删的就删 |

---

## 3. 目标架构设计

### 3.1 整体架构

```
数据层（统一）:
  DuckDB (.olav/db/main.duckdb)
    ├── devices, interfaces           (核心网络数据)
    ├── netbox_*                      (未来：DCIM/IPAM)
    ├── logs_*                        (未来：OpenSearch)
    └── metrics_*                     (未来：Zabbix)

用户输入
  │
  ├── /admin backup     → admin_backup()        # 直接函数调用，无 LLM
  ├── /admin create-skill → admin_create_skill()
  ├── /admin import-data → import_external_data()  # 新增：导入外部系统数据
  ├── /learn <cmd>      → command_learner()      # 独立 HITL 工作流
  │
  └── 自然语言查询      → OLAV Deep Agent
                           │
                           ├── Tools: smart_sql_query, nornir_execute, list_devices
                           │
                           ├── Skills (按需热加载):
                           │    ├── network-query     → 教 agent 写 SQL
                           │    ├── network-cli       → 教 agent 执行 CLI + 安全规则
                           │    ├── network-expert    → 教 agent 做 RCA
                           │    ├── network-inspection → 教 agent 做批量巡检
                           │    └── network-snapshot  → 教 agent 做快照对比
                           │
                           ├── Middleware:
                           │    ├── SummarizationMiddleware  (上下文压缩)
                           │    ├── TodoListMiddleware       (复杂任务规划)
                           │    ├── ToolRetryMiddleware      (工具失败重试)
                           │    └── SkillsMiddleware         (自动，Skills 热加载)
                           │
                           └── Backend:
                                ├── / (default) → StateBackend (临时)
                                └── /memories/  → StoreBackend (持久化)
```

### 3.2 核心入口：`src/olav/agents/agent.py`（~50 行）

```python
"""
OLAV Deep Agent — 唯一的 agent 创建入口
替代: router.py, guard.py, execution_dispatcher.py, query_orchestrator.py,
      subagent_loader.py, skill_loader.py, tool_registry.py, session.py
"""
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain.agents.middleware import (
    SummarizationMiddleware,
    TodoListMiddleware,
    ToolRetryMiddleware,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from olav.tools.database import smart_sql_query
from olav.tools.network import nornir_execute, list_devices
from olav.core.llm import LLMFactory


def create_olav_agent(checkpointer=None, store=None):
    """Create the single OLAV deep agent."""
    model = LLMFactory.get_chat_model()
    
    return create_deep_agent(
        model=model,
        name="olav",
        tools=[smart_sql_query, nornir_execute, list_devices],
        skills=[".olav/skills/"],
        memory=[".olav/AGENTS.md"],
        checkpointer=checkpointer or MemorySaver(),
        store=store or InMemoryStore(),
        backend=lambda rt: CompositeBackend(
            default=StateBackend(rt),
            routes={"/memories/": StoreBackend(rt)},
        ),
        middleware=[
            SummarizationMiddleware(
                model=model,
                trigger=("tokens", 100_000),
                keep=("messages", 20),
            ),
            TodoListMiddleware(),
            ToolRetryMiddleware(max_retries=2, backoff_factor=1.5),
        ],
        system_prompt=(
            "You are OLAV, a CCIE-level network operations AI assistant.\n\n"
            "You help network engineers by:\n"
            "- Querying device data (smart_sql_query)\n"
            "- Executing CLI commands on devices (nornir_execute)\n"
            "- Listing device inventory (list_devices)\n\n"
            "WORKFLOW for any question:\n"
            "1. Check if database has the data (smart_sql_query)\n"
            "2. If data insufficient, get live data (nornir_execute)\n"
            "3. Combine and analyze both sources\n"
            "4. NEVER fabricate data\n\n"
            "For complex multi-step tasks, use write_todos to plan.\n"
            "For large tool outputs, save to filesystem and return summary.\n"
            "Respond in the user's language (Chinese or English)."
        ),
    )
```

**~50 行代码替代 ~5,000+ 行**:
- ~~router.py~~ (212)
- ~~guard.py~~ (273) + ~~security_classifier.py~~ (301) + ~~cache_manager.py~~ (243) + ~~llm_router.py~~ (210)
- ~~execution_dispatcher.py~~ (644)
- ~~query_orchestrator.py~~ (511)
- ~~subagent_loader.py~~ (533) + ~~skill_loader.py~~ (375) + ~~skill_config.py~~ (207)
- ~~tool_registry.py~~ (250)
- ~~guard_rules_loader.py~~ (397)
- ~~session.py~~ (1,195)
- ~~orchestrator.py~~ (100)

### 3.3 Admin & Command Learner：/COMMAND 模式

**这些不是自然语言查询，不需要 LLM 路由，直接做。**

```python
# src/olav/cli/commands.py (~100 行)

def handle_slash_command(user_input: str) -> str | None:
    """Handle /commands before sending to agent. Returns None if not a command."""
    if not user_input.startswith("/"):
        return None

    parts = user_input.split(maxsplit=2)
    cmd = parts[0].lower()

    if cmd == "/admin":
        subcmd = parts[1] if len(parts) > 1 else "help"
        return admin_dispatch(subcmd, parts[2] if len(parts) > 2 else "")
    
    if cmd == "/learn":
        command = parts[1] if len(parts) > 1 else ""
        return command_learner_workflow(command)
    
    if cmd == "/help":
        return HELP_TEXT
    
    return f"Unknown command: {cmd}. Type /help for available commands."


def admin_dispatch(subcmd: str, args: str) -> str:
    """Direct function calls — no LLM needed."""
    match subcmd:
        case "backup":
            return admin_backup()
        case "restore":
            return admin_restore(args)
        case "create-skill":
            return admin_create_skill_wizard()  # interactive, may use LLM
        case "status":
            return admin_system_status()
        case "help":
            return ADMIN_HELP
        case _:
            return f"Unknown admin command: {subcmd}"


def command_learner_workflow(command: str) -> str:
    """TextFSM template learning — independent HITL workflow."""
    # 1. Execute command on device → get raw output
    # 2. LLM analyzes output fields  
    # 3. User approves field selection (HITL)
    # 4. LLM generates TextFSM template
    # 5. User approves template (HITL)
    # 6. Save to .olav/templates/
    ...
```

**为什么 /COMMAND 比 SubAgent 更好？**

| | Admin SubAgent | /admin 命令 |
|---|---|---|
| 备份配置 | LLM 理解请求 → 调 backup_tool → 返回 | **直接调 backup()** |
| 延迟 | 2-5 秒（LLM 推理） | **<100ms** |
| 可靠性 | LLM 可能误解 | **100% 确定性** |
| 实现 | SubAgent config + tools | **~20 行 match/case** |
| 安全 | LLM 可能写错文件 | **硬编码路径** |

### 3.4 CLI 主循环

```python
# src/olav/cli/cli_main.py (~150 行)

def main():
    agent = create_olav_agent()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    while True:
        user_input = console.input("> ").strip()
        if not user_input or user_input in ("exit", "quit"):
            break
        
        # 1. /commands 直接处理
        cmd_result = handle_slash_command(user_input)
        if cmd_result is not None:
            console.print(Markdown(cmd_result))
            continue
        
        # 2. 自然语言 → Agent
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
        )
        console.print(Markdown(result["messages"][-1].content))
```

---

## 4. 数据库架构设计

### 4.1 设计原则：多数据库分层架构

> **🔑 核心决策**：不同数据用途 → 不同数据库技术  
> **原则 1**：只读数据统一到 DuckDB（便于 SQL JOIN）  
> **原则 2**：写操作直接调外部 API（保持一致性）  
> **原则 3**：Agent 运行时数据与业务数据分离  
> **原则 4**：Schema 缓存只用内存（DuckDB DESCRIBE 足够快）

```
架构层次：
┌─────────────────────────────────────────────────────────┐
│  4. 外部系统 API 层（写操作，实时数据）                    │
│     NetBox API, Zabbix API, OpenSearch API...          │
│     特点：写操作、实时状态、保持数据源一致性                │
└─────────────────────────────────────────────────────────┘
                          ↓ 定期同步（read-only
┌─────────────────────────────────────────────────────────┐
│  3. OLAP 数据层（DuckDB: .olav/db/main.duckdb）          │
│     - devices, interfaces (核心网络数据)                 │
│     - netbox_* (从 NetBox 导入的快照)                    │
│     - logs_* (从 OpenSearch 导入的日志)                  │
│     - metrics_* (从 Zabbix 导入的指标)                   │
│     特点：分析型查询、关联查询、历史数据、快速聚合           │
└─────────────────────────────────────────────────────────┘
                          ↑ smart_sql_query
┌─────────────────────────────────────────────────────────┐
│  2. Agent 运行时层                                        │
│     - Checkpoint (DuckDB: .olav/db/agent.duckdb)        │
│       会话状态、消息历史（LangGraph DuckDBSaver）          │
│     - Store (DuckDB: 同上)                              │
│       跨会话记忆、用户偏好（LangGraph DuckDBStore）         │
│     - LLM Cache (SQLite: .olav/db/llm_cache.db)        │
│       LLM 响应缓存、减少 API 调用                          │
└─────────────────────────────────────────────────────────┘
                          ↑ Agent invoke
┌─────────────────────────────────────────────────────────┐
│  1. 元数据层（文件系统 + 内存）                         │
│     - Skills (.olav/skills/*/SKILL.md)                 │
│     - 配置 (.env, .olav/settings.json)                  │
│     - Schema 缓存（进程内存，DuckDB 回源）              │
└─────────────────────────────────────────────────────────┘
```

### 4.2 数据库技术选型

| 数据类型 | 数据库 | 文件路径 | 原因 |
|---------|--------|---------|------|
| **业务数据** | **DuckDB** | `.olav/db/main.duckdb` | OLAP 极快、支持复杂 JOIN、嵌入式零配置 |
| 外部系统快照 | **DuckDB** | 同上（统一） | 便于跨系统关联查询（设备 JOIN NetBox） |
| Agent Checkpoint | **DuckDB** | `.olav/db/agent.duckdb` | LangGraph 原生支持 DuckDBSaver |
| Agent Store | **DuckDB** | 同上 | LangGraph DuckDBStore |
| LLM 缓存 | **SQLite** | `.olav/db/llm_cache.db` | 简单 KV 存储、极快读取 |
| Schema 缓存 | **内存** | 进程内 | DuckDB DESCRIBE 很快（~1ms），无需持久化 |
| 配置文件 | **文件系统** | `.env`, `settings.json` | 人工可编辑 |
| Skills | **文件系统** | `.olav/skills/` | Git 版本控制 |

### 4.3 为什么用 DuckDB 而不是 PostgreSQL？

| 维度 | DuckDB | PostgreSQL |
|------|--------|------------|
| **部署** | ✅ 嵌入式，零配置 | ❌ 需要服务器 |
| **OLAP 性能** | ✅ 列存储，极快聚合 | ⚠️ 行存储，聚合较慢 |
| **分析型查询** | ✅ 专为此设计 | ⚠️ OLTP 优先 |
| **高并发写** | ⚠️ 单写入（够用） | ✅ 多客户端写入 |
| **适用场景** | ✅ 单用户/小团队 | ✅ 多用户 SaaS |
| **SQL 兼容** | ✅ PostgreSQL 方言 | ✅ 标准 SQL |
| **文件大小** | ✅ 几 MB（小数据集） | ❌ 需磁盘空间规划 |

**OLAV 选择 DuckDB 的原因**：
- 单用户/小团队场景
- 分析型查询为主（设备统计、趋势分析）
- 零运维成本
- LangGraph 原生支持

**何时切换到 PostgreSQL**：
- 多租户 SaaS 部署
- > 100 并发用户
- 需要严格的事务 ACID

### 4.4 API 隔离策略：混合模式

> **问题**：是否应该保持各系统 API 隔离？  
> **答案**：混合策略 — 根据操作类型选择

#### 策略 A：只读数据 → 统一到 DuckDB（推荐）

```python
# 场景：查询 NetBox 中设备的机架位置
# 方案：定期同步到 DuckDB，用 SQL 关联查询

# 1. 数据导入 (每天 1 次)
/admin import-data --source netbox --schedule daily
# → 创建 netbox_racks, netbox_devices

# 2. 用户查询
"哪些设备在机架 R01？"
# → smart_sql_query 自动生成：
SELECT d.hostname, n.rack_name, n.rack_unit
FROM devices d
JOIN netbox_devices n ON d.hostname = n.name
WHERE n.rack_name = 'R01'

# 优点：
# ✅ 跨系统 JOIN（设备表 + NetBox 表）
# ✅ 查询极快（本地 DuckDB）
# ✅ 无 API 频率限制
# ✅ 离线可用

# 缺点：
# ⚠️ 数据有延迟（最多 1 天）
# → 但对于规划类查询（机架容量、IP 分配）完全够用
```

#### 策略 B：写操作 → 直接调用外部 API

```python
# 场景：在 NetBox 中分配新 IP
# 方案：直接调用 NetBox API（不经过 DuckDB）

# 用户请求："给 router1 分配 IP 10.1.1.100"
# → Agent 调用 netbox_api_call tool:
netbox_api_call(
    endpoint="/api/ipam/ip-addresses/",
    method="POST",
    data={"address": "10.1.1.100", "device": "router1"}
)

# 优点：
# ✅ 数据实时写入源系统
# ✅ 避免数据不一致
# ✅ 审计日志在 NetBox 侧

# 注意：
# 写入后，下次同步会更新 DuckDB 快照
```

#### 策略 C：实时数据 → API 查询 + 缓存

```python
# 场景：查询设备当前 CPU 使用率
# 方案：调用 Zabbix API，缓存 1 分钟

# 用户："router1 的 CPU 使用率？"
# → Agent 调用 zabbix_get_metrics tool:
zabbix_get_metrics(
    host="router1",
    metrics=["system.cpu.util"],
    cache_ttl=60  # 缓存 1 分钟
)

# 优点：
# ✅ 实时数据
# ✅ 缓存避免频繁 API 调用

# 历史趋势分析：
# → 定期同步到 DuckDB metrics_cpu 表
# → 用 SQL 做聚合：SELECT AVG(cpu) ... GROUP BY DATE_TRUNC('hour', ts)
```

### 4.5 Schema 缓存策略：内存 + DuckDB（极简）

```python
# 问题：每次查询都调 DESCRIBE 会很慢？
# 实测：DuckDB DESCRIBE 只需 ~1ms，足够快
# 方案：只用内存缓存（两层），去掉 SQLite 中间层

class SchemaCache:
    """极简 Schema 缓存 — 只用内存"""
    
    def __init__(self, conn):
        self.conn = conn
        self.memory = {}  # 单层内存缓存
    
    def get_schema(self, table: str) -> dict:
        """获取表 schema"""
        # 检查内存缓存
        if table in self.memory:
            return self.memory[table]
        
        # 直接查询 DuckDB（1-2ms，足够快）
        schema = self._query_duckdb(table)
        self.memory[table] = schema
        return schema
    
    def _query_duckdb(self, table: str) -> dict:
        """查询实际 schema"""
        result = self.conn.execute(f"DESCRIBE {table}").fetchall()
        return {
            "columns": [row[0] for row in result],
            "types": dict(zip([row[0] for row in result], [row[1] for row in result])),
        }
    
    def invalidate(self, table: str = None):
        """数据导入后，清除缓存"""
        if table:
            self.memory.pop(table, None)
        else:
            self.memory.clear()

# 使用：
# Agent 启动时
schema_cache = SchemaCache(duck_conn)

# smart_sql_query 调用时
schema = schema_cache.get_schema("devices")  # 首次 1ms，后续 0.001ms

# import-data 完成后
schema_cache.invalidate()  # 清空内存，下次重新查询
```

**为什么不需要 SQLite 持久化？**

| 场景 | 三层方案 | **两层方案（推荐）** |
|------|---------|-----------------|
| 首次查询 | DuckDB 1ms → SQLite 写入 | **DuckDB 1ms → 内存** |
| 后续查询 | 内存 0.001ms | **内存 0.001ms** |
| 进程重启 | SQLite 读取 0.1ms | **DuckDB 1ms**（可接受） |
| import-data 后 | 清除 L1+L2 | **清除内存**（更简单） |
| 代码复杂度 | +50 行（SQLite 逻辑） | **+15 行** |
| 依赖 | DuckDB + SQLite | **只需 DuckDB** |

**结论**：
- ✅ DuckDB DESCRIBE 已经很快（1-2ms）
- ✅ 进程重启不频繁（每天 < 10 次）
- ✅ 内存缓存足够覆盖 99.9% 查询
- ❌ SQLite 持久化增加复杂度，收益微小

### 4.6 数据库文件组织

```
.olav/db/
├── main.duckdb              # 业务数据（网络 + 外部系统快照）
│   ├── devices              # 核心网络设备
│   ├── interfaces           # 接口数据
│   ├── netbox_*             # NetBox 快照（机架、IP、电路）
│   ├── logs_*               # OpenSearch 日志快照
│   └── metrics_*            # Zabbix 指标快照
│
├── agent.duckdb             # Agent 运行时（分离避免锁冲突）
│   ├── checkpoints          # LangGraph 会话状态
│   └── store                # LangGraph 跨会话存储
│
└── llm_cache.db             # LLM 响应缓存（SQLite）

# Schema 缓存？进程内存即可，无需持久化文件
```

**为什么分离 main.duckdb 和 agent.duckdb？**
- **避免锁冲突**：业务查询 vs Agent 写 checkpoint
- **备份策略不同**：main.duckdb 每天备份，agent.duckdb 可丢弃
- **性能隔离**：Agent 高频写不影响业务查询

### 4.7 数据同步策略

```python
# src/olav/lib/data_sync.py

class DataSyncManager:
    """外部系统数据同步到 DuckDB"""
    
    SYNC_STRATEGIES = {
        "netbox": {
            "schedule": "daily",      # 设备清单变化慢
            "tables": ["sites", "racks", "devices", "ips"],
            "method": "full_replace",  # 全量替换
        },
        "zabbix": {
            "schedule": "hourly",     # 指标数据更新快
            "tables": ["metrics_cpu", "metrics_memory"],
            "method": "incremental",   # 增量插入
            "retention": "30 days",    # 只保留 30 天
        },
        "opensearch": {
            "schedule": "hourly",
            "tables": ["logs_syslog", "logs_snmp"],
            "method": "incremental",
            "retention": "7 days",
        },
    }
    
    def sync(self, source: str):
        strategy = self.SYNC_STRATEGIES[source]
        
        if strategy["method"] == "full_replace":
            # 1. 从 API 拉取全量数据
            data = self.fetch_from_api(source)
            # 2. 替换 DuckDB 表
            conn.execute(f"DROP TABLE IF EXISTS {source}_*")
            conn.execute(f"CREATE TABLE ... AS SELECT * FROM data")
        
        elif strategy["method"] == "incremental":
            # 1. 查询最新时间戳
            last_ts = conn.execute(f"SELECT MAX(ts) FROM {source}_*").fetchone()[0]
            # 2. 拉取增量数据
            data = self.fetch_from_api(source, since=last_ts)
            # 3. 插入新数据
            conn.execute(f"INSERT INTO ... VALUES ...")
            # 4. 清理过期数据
            conn.execute(f"DELETE FROM ... WHERE ts < NOW() - INTERVAL '{strategy['retention']}'")
        
        # 5. 清除 Schema 缓存
        schema_cache.invalidate()

# 定时任务（cron 或 APScheduler）
scheduler.add_job(sync_manager.sync, args=["netbox"], trigger="cron", hour=3)
scheduler.add_job(sync_manager.sync, args=["zabbix"], trigger="interval", hours=1)
```

---

## 5. Skill 热插拔机制详解

### 4.1 Skills 如何替代 SubAgent 路由

**SubAgent 路由**: LLM 读 description → 选 SubAgent → SubAgent 有自己的 tools + prompt  
**Skills 路由**: LLM 读 SKILL.md description → 按需加载 Skill 内容 → Agent 用同一套 tools 执行

```
用户: "有多少个设备?"
  Agent 启动时已加载所有 Skills 的 description（frontmatter）
  → 匹配 network-query skill
  → 加载 SKILL.md 完整内容（progressive disclosure）
  → 按 Skill 指令调用 smart_sql_query
  → 返回结果

用户: "为什么 BGP 不稳定?"
  → 匹配 network-expert skill
  → 加载 SKILL.md: "先查 DB，数据不足则 CLI 补充"
  → smart_sql_query 查 BGP 配置
  → nornir_execute 查 live BGP 状态
  → 综合分析返回
```

### 4.2 SKILL.md 格式标准化

**当前格式**（自定义字段太多）:
```yaml
---
name: network-query
version: 7.0.0
intent: quick_query          # ← 删除（Guard 专用）
tools:                       # ← 改为 allowed-tools
  - smart_sql_query
prompts:                     # ← 删除（内联到 body）
  system: $ref:./prompts/system.md
---
```

**目标格式**（Agent Skills 标准）:
```yaml
---
name: network-query
description: >
  Use for device inventory queries, SQL against DuckDB, schema inspection,
  data export to CSV/JSON. Handles: device counts, filtering, IP ranges, roles.
version: 7.0.0
allowed-tools: smart_sql_query
metadata:
  author: Network AI Team
  category: network-operations
---

# network-query

## Overview
Query network device inventory and interface data using DuckDB SQL.

## Instructions
1. Use smart_sql_query(query="natural language") for schema discovery
2. Use smart_sql_query(sql="SELECT ...") for SQL execution
3. Return results as markdown tables
4. For export: smart_sql_query(sql=..., export_format="csv")

## Escalation
- If database lacks data → use nornir_execute for live CLI data
- If complex analysis needed → use write_todos to plan multi-step approach

## DuckDB Tips
- DATE/TIME: Use INTERVAL syntax
- Complex queries: Use CTEs
- NULL handling: Use COALESCE()
```

### 4.3 Skill 与 Tool 的关系

```
Skill = 知识（WHEN + HOW）
Tool = 能力（DO）

network-query skill 告诉 Agent:
  WHEN: 用户问设备清单、数据查询、导出时
  HOW:  先 smart_sql_query(query=...) 获取 schema，再 smart_sql_query(sql=...) 执行

network-cli skill 告诉 Agent:
  WHEN: 用户要执行 show 命令、查看设备状态时
  HOW:  先 list_devices() 确认设备，再 nornir_execute(command=..., devices=[...])
  安全: NEVER execute reload/erase/format

network-expert skill 告诉 Agent:
  WHEN: 用户要做 RCA、troubleshooting、设计审查时
  HOW:  1. smart_sql_query 查历史数据
        2. nornir_execute 查 live 数据
        3. 综合分析，生成诊断报告

所有 Skill 共享同一套 tools — 区别在于"用什么知识指导工具使用"
```

### 4.4 未来 Skills 扩展：数据导入模式（零 SubAgent）

> **🔑 关键架构决策**（2026-02-14）  
> **问题**：如何集成 NetBox、Zabbix、OpenSearch 等外部系统？  
> **传统方案**：为每个系统写 API tool + 创建 SubAgent（复杂）  
> **OLAV 方案**：利用 schema-aware 机制 + DuckDB 统一数据层  
> **结论**：90% 场景只需数据导入 + Skill，零新 tools，零 SubAgent

**核心机制**：smart_sql_query 是 schema-aware 的
- 用户问题 → Agent 调 smart_sql_query(query="自然语言")
- Tool 查询 DuckDB schema → 返回所有表结构
- LLM 根据 schema 生成 SQL → 执行

**集成新系统的三种模式**：

#### 模式 1：只读数据源（推荐，零代码）
```bash
# 步骤 1: 导入数据到 DuckDB
/admin import-data --source netbox --url https://netbox.local --token xxx
# 自动创建: netbox_sites, netbox_racks, netbox_devices, netbox_ips...

# 步骤 2: 创建 Skill
mkdir -p .olav/skills/netbox/
cat > .olav/skills/netbox/SKILL.md << 'EOF'
---
name: netbox
description: >
  Use for DCIM/IPAM queries: site info, rack layouts, IP allocations,
  circuit data. Query NetBox data imported from API.
allowed-tools: smart_sql_query
---
# netbox

## Instructions
1. Use smart_sql_query(query="NetBox sites") to discover schema
2. Query netbox_* tables: netbox_sites, netbox_racks, netbox_devices, netbox_ips
3. Join with network devices table for correlation

## Table Descriptions
- netbox_sites: Data center locations
- netbox_racks: Rack inventory and space
- netbox_devices: Device DCIM records
- netbox_ips: IP address management
EOF

# 步骤 3: 完成 ✅
# 零新 tools，零 SubAgent，只加了一个 Skill
```

#### 模式 2：需要写操作的外部系统
```bash
# 如果需要 NetBox API 写操作（创建设备、分配 IP）
# 1. 写 tool: src/olav/tools/netbox.py
def netbox_api_call(endpoint: str, method: str, data: dict) -> dict:
    """Call NetBox API for write operations."""
    ...

# 2. 注册到 agent.py
tools=[smart_sql_query, nornir_execute, list_devices, netbox_api_call]

# 3. 更新 Skill
allowed-tools: smart_sql_query, netbox_api_call

# 仍然是一个 Agent，只是多了一个 tool
```

#### 模式 3：Tools > 15 时才考虑 SubAgent
```python
# 极端情况：集成了 10+ 外部系统，每个 3-5 个 tools
# 此时 tools 总数 > 30，LLM 可能选错
# 这时才用 SubAgent 拆分

subagents=[
    {"name": "netbox", "tools": [netbox_*], "skills": [".olav/skills/netbox/"]},
    {"name": "zabbix", "tools": [zabbix_*], "skills": [".olav/skills/zabbix/"]},
]

# 但这是遥远的未来，不是现在
```

**结论**：
- **90% 场景**：数据导入 + Skill（模式 1）
- **9% 场景**：加 1-2 个 tools（模式 2）
- **1% 场景**：SubAgent（模式 3）

---

## 5. 文件级精简计划

### 5.1 删除的文件（~7,500 行）

| 文件 | 行数 | 删除原因 |
|------|------|----------|
| `agents/guard.py` | 273 | 不需要分类 — Agent 直接用 tools |
| `agents/security_classifier.py` | 301 | 安全规则写入 Skill |
| `agents/cache_manager.py` | 243 | Guard 缓存不需要 |
| `agents/llm_router.py` | 210 | 无路由 |
| `agents/execution_dispatcher.py` | 644 | Agent 直接调 tools |
| `agents/query_orchestrator.py` | 511 | Agent 替代 sync fallback |
| `agents/analyzer.py` | 683 | network-expert Skill 替代 |
| `agents/inspector.py` | 315 | network-inspection Skill 替代 |
| `agents/router.py` | 212 | 新 agent.py 替代 |
| `agents/orchestrator.py` | 100 | 新 agent.py 替代 |
| `core/subagent_loader.py` | 533 | 无 SubAgent |
| `core/skill_loader.py` | 375 | SkillsMiddleware 原生加载 |
| `core/skill_config.py` | 207 | 同上 |
| `core/guard_rules_loader.py` | 397 | Guard 删除 |
| `core/tool_registry.py` | 250 | tools 直接 inline |
| `core/database_enhancer.py` | 550 | 死代码 |
| `core/query_optimizer.py` | 63 | 死代码 |
| `core/connection_pool.py` | 318 | DuckDB 不需要连接池 |
| `core/result_analyzer.py` | 168 | Agent prompt 替代 |
| `cli/session.py` | 1,195 | Checkpointer 替代 |

**小计**: ~7,548 行删除（20 个文件）

### 5.2 大幅简化的文件

| 文件 | 当前行数 | 目标行数 | 简化方式 |
|------|---------|---------|----------|
| `cli/cli_main.py` | 1,319 | ~150 | 只做 I/O + /cmd + agent.invoke |
| `core/storage.py` | 218 | 删除 | backend 配置内联在 agent.py |
| `core/unified_database.py` | 442 | 合入 database.py | 一个 DB 模块 |
| `core/query_cache.py` | 148 | 保留 | LLM 缓存仍有价值 |

### 5.3 保留不变的文件

| 文件 | 行数 | 保留原因 |
|------|------|----------|
| `core/llm.py` | 184 | 多 provider LLM 工厂 |
| `core/database.py` | 823 | 核心 DuckDB 管理 |
| `config/settings.py` | 1,125 | 配置验证 |
| `config/paths.py` | 268 | 路径常量 |
| `lib/` | ~300 | 数据导入 |
| `api/` | ~2,600 | REST API |

### 5.4 新建的文件

| 文件 | 行数 | 用途 |
|------|------|------|
| `agents/agent.py` | ~50 | 唯一 agent 入口 |
| `tools/__init__.py` | ~5 | tools 包 |
| `tools/database.py` | ~100 | smart_sql_query |
| `tools/network.py` | ~80 | nornir_execute + list_devices |
| `cli/commands.py` | ~100 | /admin + /learn 命令 |
| `.olav/AGENTS.md` | ~30 | 持久化记忆 |

### 5.5 精简效果

```
当前:     ~22,750 行 (67 文件)
删除:     ~7,548 行 (20 文件删除)
简化:     ~1,980 → ~150 行 (cli_main + storage + unified_db)
新增:     ~365 行 (6 新文件)

目标:     ~13,737 行 (~53 文件)
净减少:   ~9,013 行 (40% 减少)
Agent 层: ~5,000+ 行 → ~50 行 (99% 减少)
```

---

## 7. 目录结构设计

### 7.1 新 .olav/ 目录结构

```
.olav/
├── AGENTS.md                    # Agent 持久化记忆（替代 OLAV.md）
│                                # - 用户偏好
│                                # - 常用别名
│                                # - 历史见解
│
├── skills/                      # Skills 目录（保持现有结构）
│   ├── network-query/
│   │   └── SKILL.md            # Agent Skills 标准格式
│   ├── network-cli/
│   │   └── SKILL.md
│   ├── network-expert/
│   │   └── SKILL.md
│   ├── network-inspection/
│   │   └── SKILL.md
│   ├── network-snapshot/
│   │   └── SKILL.md
│   └── shared/                 # 共享资源（可选）
│       ├── prompts/
│       └── examples/
│
├── tools/                       # Tool 实现（保持现有位置，支持跨平台迁移）
│   ├── __init__.py
│   ├── database.py             # smart_sql_query (~100 行)
│   └── network.py              # nornir_execute, list_devices (~80 行)
│                                # 符合 MCP 标准，用户可复制整个 .olav/ 迁移
│
├── db/                          # 数据库文件（新增分层）
│   ├── main.duckdb             # 业务数据（设备 + 外部系统快照）
│   ├── agent.duckdb            # Agent 运行时（checkpoint + store）
│   └── llm_cache.db            # LLM 响应缓存
│
├── backups/                     # 备份目录
│   └── YYYY-MM-DD_HHMMSS.tar.gz
│
├── logs/                        # 日志目录
│   ├── agent.log               # Agent 运行日志
│   ├── netbox_sync.log         # 数据同步日志
│   └── cli_batch_TIMESTAMP/    # CLI 批量执行日志
│
├── settings.json                # 用户配置（可选覆盖）
│                                # 格式：{"llm": {"model": "grok-4.1-fast"}}
│
└── templates/                   # TextFSM 模板（保留）
    ├── ntc_templates/          # 官方模板
    └── custom/                 # 用户自定义

删除：
❌ OLAV.md                      # 迁移到 AGENTS.md
❌ skills/*/prompts/            # 内联到 SKILL.md
❌ cache/                       # 不需要文件缓存
❌ drafts/                      # 不需要草稿流程
```

**关键设计决策：Tools 位置**

✅ **为什么 tools 放在 `.olav/` 而不是 `src/olav/tools/`？**

1. **跨平台迁移**：用户可以复制整个 `.olav/` 目录到新项目，包括：
   - Skills（业务知识）
   - Tools（执行逻辑）
   - AGENTS.md（持久化记忆）
   - 数据库文件（业务数据）
   - 完整的用户配置

2. **符合 MCP 标准**：Claude Code 和 Model Context Protocol 推荐 tools 位于工作区配置目录

3. **业务逻辑与框架代码分离**：
   - `.olav/` = 用户数据层（Tools, Skills, DB, Config）
   - `src/olav/` = 框架代码层（Agent 创建、CLI、API）

4. **动态加载机制**：
   ```python
   # src/olav/agents/agent.py
   import sys
   from pathlib import Path
   
   # 将 .olav/tools 添加到 Python path
   tools_path = Path.cwd() / ".olav" / "tools"
   sys.path.insert(0, str(tools_path))
   
   # 现在可以直接导入
   from database import smart_sql_query
   from network import nornir_execute
   ```

5. **热插拔能力**：用户可以不修改源代码，直接编辑 `.olav/tools/` 中的 tool 实现



### 7.2 新 src/ 目录结构

```
src/olav/
├── __init__.py
├── __main__.py                 # CLI 入口: python -m olav
│
├── agents/
│   ├── __init__.py
│   └── agent.py                # 唯一 agent 创建入口 (~50 行)
│                               # create_olav_agent()
│                               # 动态加载 .olav/tools/
│
├── cli/
│   ├── __init__.py
│   ├── cli_main.py             # CLI 主循环 (~150 行)
│   ├── commands.py             # /admin, /learn 命令 (~100 行)
│   └── output.py               # Rich/Markdown 输出格式化
│
├── api/                        # REST API（保留）
│   ├── __init__.py
│   ├── app.py                  # FastAPI 应用
│   ├── v1/
│   │   ├── devices.py         # 修复 SQL 注入
│   │   ├── query.py
│   │   └── admin.py
│   └── middleware/
│
├── core/
│   ├── __init__.py
│   ├── llm.py                  # LLMFactory（保留，184 行）
│   ├── database.py             # DuckDB 管理（合并 unified_database.py）
│   ├── query_cache.py          # LLM 缓存（保留，148 行）
│   └── schema_cache.py         # Schema 内存缓存（新增，~15 行）
│
├── lib/                        # 数据导入（保留）
│   ├── __init__.py
│   ├── data_sync.py            # 外部系统同步管理器（新增）
│   ├── inventory.py            # 网络设备发现
│   └── parsers/                # TextFSM 解析器
│
├── config/                     # 配置管理（保留）
│   ├── __init__.py
│   ├── paths.py                # 路径常量（保留，268 行）
│   ├── settings.py             # 配置验证（简化，~300 行）
│   ├── logging.py              # 日志配置
│   └── banners.py              # CLI banners
│
└── utils/                      # 工具函数（可选）
    ├── __init__.py
    └── validators.py

删除的文件（~7,500 行）：
❌ agents/guard.py (273)
❌ agents/security_classifier.py (301)
❌ agents/cache_manager.py (243)
❌ agents/llm_router.py (210)
❌ agents/execution_dispatcher.py (644)
❌ agents/query_orchestrator.py (511)
❌ agents/analyzer.py (683)
❌ agents/inspector.py (315)
❌ agents/router.py (212)
❌ agents/orchestrator.py (100)
❌ core/subagent_loader.py (533)
❌ core/skill_loader.py (375)
❌ core/skill_config.py (207)
❌ core/guard_rules_loader.py (397)
❌ core/tool_registry.py (250)
❌ core/database_enhancer.py (550)
❌ core/query_optimizer.py (63)
❌ core/connection_pool.py (318)
❌ core/result_analyzer.py (168)
❌ core/storage.py (218)
❌ core/unified_database.py (442) → 合并到 database.py
❌ cli/session.py (1,195)
```

### 7.3 目录结构变化对比

| 类别 | 之前 | 之后 | 变化 |
|------|------|------|------|
| **Agent 层** | 10 个文件，~5,000 行 | **1 个文件，~50 行** | **-99%** |
| **CLI 层** | 2 个文件，~2,500 行 | **2 个文件，~250 行** | -90% |
| **Core 层** | 15 个文件，~5,900 行 | **5 个文件，~1,200 行** | -80% |
| **Tools** | 分散在多个模块 | **2 个文件，~180 行（.olav/）** | 集中管理，可迁移 |
| **.olav/** | 多级目录，cache/drafts | **扁平结构 + tools/** | 简化 + MCP 标准 |
| **总计** | 67 个文件，~22,750 行 | **~53 个文件，~13,700 行** | **-40%** |

---

## 8. 配置文件设计

### 8.1 环境变量 (.env)

```bash
# .env - 敏感信息和基础配置

# ============================================================================
# LLM 配置（必需）
# ============================================================================
LLM_API_KEY=sk-or-v1-xxx...                    # API 密钥
LLM_BASE_URL=https://openrouter.ai/api/v1     # API 端点
LLM_MODEL_NAME=x-ai/grok-4.1-fast              # 模型名称

# OpenAI 兼容配置（可选 - 用于其他 provider）
# LLM_API_KEY=sk-xxx...                        # OpenAI
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_MODEL_NAME=gpt-4-turbo

# Ollama 本地配置（可选）
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434
# LLM_MODEL_NAME=mistral:latest

# ============================================================================
# 网络设备凭证（必需）
# ============================================================================
NETWORK_USERNAME=admin                         # SSH 用户名
NETWORK_PASSWORD=xxx                           # SSH 密码（建议用 vault）
# NETWORK_SSH_KEY_PATH=/path/to/key           # SSH 密钥（可选）

# ============================================================================
# 外部系统集成（可选）
# ============================================================================
# NetBox
# NETBOX_URL=https://netbox.local
# NETBOX_TOKEN=xxx

# Zabbix
# ZABBIX_URL=https://zabbix.local
# ZABBIX_USER=api_user
# ZABBIX_PASSWORD=xxx

# OpenSearch
# OPENSEARCH_URL=https://opensearch.local
# OPENSEARCH_USER=admin
# OPENSEARCH_PASSWORD=xxx

# ============================================================================
# 系统配置（可选）
# ============================================================================
OLAV_LOG_LEVEL=INFO                            # DEBUG, INFO, WARNING, ERROR
OLAV_LOG_FILE=.olav/logs/agent.log             # 日志文件路径
OLAV_DB_PATH=.olav/db/main.duckdb              # 数据库路径

# 并发控制
# MAX_CONCURRENT_DEVICES=10                    # CLI 执行并发数
# QUERY_TIMEOUT=30                             # SQL 查询超时（秒）

# LLM 缓存
# LLM_CACHE_TTL=3600                           # 缓存 1 小时
# LLM_CACHE_ENABLED=true
```

### 8.2 用户配置 (.olav/settings.json)

```json
{
  "$schema": "https://olav.dev/schema/settings-v1.json",
  "version": "1.0.0",
  
  "llm": {
    "model": "x-ai/grok-4.1-fast",
    "temperature": 0.1,
    "max_tokens": 4096,
    "fallback_models": [
      "anthropic/claude-opus-4-1",
      "ollama/mistral:latest"
    ]
  },
  
  "agent": {
    "name": "olav",
    "language": "zh",
    "summarization_trigger": {
      "type": "tokens",
      "threshold": 100000
    },
    "keep_messages": 20
  },
  
  "tools": {
    "smart_sql_query": {
      "timeout": 30,
      "max_result_rows": 1000,
      "cache_schema": true
    },
    "nornir_execute": {
      "timeout": 60,
      "max_concurrent": 10,
      "retry_count": 2,
      "connection_timeout": 10
    }
  },
  
  "data_sync": {
    "netbox": {
      "enabled": false,
      "schedule": "daily",
      "time": "03:00"
    },
    "zabbix": {
      "enabled": false,
      "schedule": "hourly",
      "retention_days": 30
    }
  },
  
  "preferences": {
    "cli_output_format": "markdown",
    "export_default_format": "csv",
    "timezone": "Asia/Shanghai"
  }
}
```

### 8.3 配置加载优先级

```python
# config/settings.py - 配置加载逻辑

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import json
from pathlib import Path

class LLMConfig(BaseModel):
    """LLM 配置"""
    api_key: str = Field(..., description="LLM API 密钥")
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    model_name: str = Field(default="x-ai/grok-4.1-fast")
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)

class NetworkConfig(BaseModel):
    """网络设备配置"""
    username: str = Field(..., description="SSH 用户名")
    password: str = Field(..., description="SSH 密码")
    ssh_key_path: Path | None = None
    timeout: int = Field(default=60, gt=0)

class Settings(BaseSettings):
    """OLAV 全局配置"""
    model_config = SettingsConfigDict(
        env_prefix="OLAV_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # 核心配置
    llm: LLMConfig
    network: NetworkConfig
    
    # 系统配置
    log_level: str = Field(default="INFO")
    log_file: Path = Field(default=Path(".olav/logs/agent.log"))
    db_path: Path = Field(default=Path(".olav/db/main.duckdb"))
    
    @classmethod
    def load(cls) -> "Settings":
        """加载配置 - 三层优先级
        
        优先级（高 → 低）：
        1. 环境变量 (OLAV_*)
        2. .olav/settings.json
        3. .env 文件
        4. 默认值
        """
        # 1. 基础加载（.env + 环境变量）
        settings = cls()
        
        # 2. 覆盖 .olav/settings.json
        user_config_path = Path(".olav/settings.json")
        if user_config_path.exists():
            with open(user_config_path) as f:
                user_config = json.load(f)
                # 合并用户配置（递归更新）
                settings = cls.model_validate({
                    **settings.model_dump(),
                    **user_config,
                })
        
        return settings

# 全局单例
_settings: Settings | None = None

def get_settings() -> Settings:
    """获取全局配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings
```

### 8.4 配置验证示例

```python
# 使用示例
from olav.config.settings import get_settings

settings = get_settings()

# 访问配置
print(f"Using LLM: {settings.llm.model_name}")
print(f"Database: {settings.db_path}")
print(f"Network user: {settings.network.username}")

# 配置验证会自动检查：
# ✅ 必需字段存在
# ✅ 类型正确
# ✅ 值在合法范围内
# ✅ 文件路径存在（如果指定）
```

---

## 9. 测试策略与 TDD 实践

### 9.1 测试理念：真实场景，零 Mock

> **核心原则**：测试用户真实输入，验证完整数据流，避免 Mock 业务逻辑

**反模式（❌ 不要这样）**：
```python
# ❌ 测试组件存在
def test_agent_exists():
    agent = create_query_agent()
    assert agent is not None  # 无意义

# ❌ Mock 核心逻辑
@patch('olav.tools.database.execute_sql')
def test_query(mock_sql):
    mock_sql.return_value = {"count": 6}
    # 测试的是 mock，不是真实代码
```

**正确模式（✅ 这样做）**：
```python
# ✅ 测试真实用户场景
@pytest.mark.e2e
async def test_user_query_device_count():
    """用户故事：查询设备数量"""
    # 真实 Agent + 真实 DB + 真实 LLM
    result = await orchestrate_query("有多少个设备?")
    
    # 验证结果正确性
    assert result["answer"] == "6 个设备"
    assert result["source"] == "database"
```

### 9.2 新测试目录结构

```
tests/
├── __init__.py
├── conftest.py                 # pytest 配置 + fixtures
│
├── unit/                       # 单元测试（独立函数）
│   ├── __init__.py
│   ├── test_schema_cache.py    # Schema 缓存逻辑
│   ├── test_sql_parser.py      # SQL 生成逻辑
│   ├── test_validators.py      # 输入验证
│   └── test_config.py          # 配置加载
│
├── integration/                # 集成测试（组件协作）
│   ├── __init__.py
│   ├── test_agent_tools.py     # Agent + Tools 集成
│   ├── test_database.py        # DuckDB 操作
│   └── test_network.py         # Nornir 连接（可选 mock 硬件）
│
├── e2e/                        # E2E 测试（真实用户场景）
│   ├── __init__.py
│   ├── test_real_scenarios.py  # 核心场景（无 mock）
│   ├── test_cli_commands.py    # CLI 端到端
│   └── test_api_endpoints.py   # API 端到端
│
├── fixtures/                   # 测试数据
│   ├── sample_devices.sql      # 测试设备数据
│   ├── sample_cli_output.txt   # CLI 输出示例
│   └── sample_skills/          # 测试用 Skills
│
└── helpers/                    # 测试辅助工具
    ├── __init__.py
    ├── cli_tracker.py          # CLI 命令追踪器
    ├── db_helper.py            # 测试数据库管理
    └── assertions.py           # 自定义断言

删除：
❌ tests/ 中所有 mock-heavy 测试
❌ 测试组件存在的无意义测试
❌ 过度隔离的单元测试
```

### 9.3 TDD 工作流

```
需求 → 写测试（Red）→ 实现功能（Green）→ 重构（Refactor）→ 提交
```

#### 示例：TDD 开发 "导出设备到 CSV" 功能

**Step 1: 写失败测试（Red）**
```python
# tests/e2e/test_real_scenarios.py

import pytest
from pathlib import Path
from olav.agents.agent import create_olav_agent

@pytest.mark.e2e
class TestExportFeatures:
    """用户故事：数据导出功能"""
    
    @pytest.mark.asyncio
    async def test_export_devices_to_csv(self):
        """用户需求：把所有设备信息导出到 CSV
        
        验收标准：
        1. 查询成功
        2. CSV 文件创建
        3. 包含所有设备数据
        4. 零 CLI 执行（纯 DB 查询）
        """
        agent = create_olav_agent()
        config = {"configurable": {"thread_id": "test-export"}}
        
        # 用户输入
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "把所有设备信息导出到 CSV"}]},
            config=config,
        )
        
        # 验证 1: 查询成功
        assert result is not None
        assert "messages" in result
        
        # 验证 2: CSV 文件存在
        export_dir = Path("exports")
        csv_files = list(export_dir.glob("devices_*.csv"))
        assert len(csv_files) > 0, "CSV 文件未创建"
        
        # 验证 3: 数据正确
        import csv
        with open(csv_files[0]) as f:
            reader = csv.DictReader(f)
            devices = list(reader)
            assert len(devices) == 6, "设备数量不对"
            assert "hostname" in devices[0], "缺少 hostname 字段"
        
        # 验证 4: 零 CLI 执行（通过日志或追踪器验证）
        # 这可以通过 CLI 命令追踪器实现（见下文）
```

**运行测试**：
```bash
$ uv run pytest tests/e2e/test_real_scenarios.py::TestExportFeatures::test_export_devices_to_csv -v

FAILED - FileNotFoundError: CSV not created
```

**Step 2: 实现功能（Green）**
```python
# .olav/tools/database.py

from langchain_core.tools import tool
import duckdb
from pathlib import Path
from datetime import datetime

@tool
def smart_sql_query(
    query: str | None = None,
    sql: str | None = None,
    export_format: str | None = None,
) -> dict:
    """Execute a DuckDB SQL query with optional export.
    
    Args:
        query: Natural language query (for schema discovery)
        sql: Direct SQL statement
        export_format: Export format (csv, json), creates file in exports/
    
    Returns:
        Query results or export confirmation
    """
    conn = duckdb.connect(".olav/db/main.duckdb")
    
    # 执行查询
    result = conn.execute(sql or "SELECT * FROM devices").fetchall()
    
    # 导出逻辑
    if export_format:
        export_dir = Path("exports")
        export_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"devices_{timestamp}.{export_format}"
        filepath = export_dir / filename
        
        if export_format == "csv":
            conn.execute(f"COPY ({sql}) TO '{filepath}' (HEADER, DELIMITER ',')")
        elif export_format == "json":
            conn.execute(f"COPY ({sql}) TO '{filepath}' (FORMAT JSON, ARRAY true)")
        
        return {
            "status": "success",
            "message": f"Exported {len(result)} rows to {filepath}",
            "file": str(filepath),
        }
    
    return {"rows": result}
```

**运行测试**：
```bash
$ uv run pytest tests/e2e/test_real_scenarios.py::TestExportFeatures::test_export_devices_to_csv -v

PASSED ✅
```

**Step 3: 重构（Refactor）**
```python
# 重构：提取导出逻辑到独立函数
def _export_results(conn, sql: str, format: str) -> Path:
    """导出查询结果到文件"""
    # ... 导出逻辑 ...
    return filepath

# 测试仍然通过
```

### 9.4 CLI 命令追踪器（监控副作用）

```python
# tests/helpers/cli_tracker.py

import subprocess
from unittest.mock import patch
from typing import List

class CLICommandTracker:
    """追踪 CLI 命令执行（监控副作用）
    
    用途：验证某些操作不应该执行 CLI
    """
    
    def __init__(self):
        self.commands: List[str] = []
    
    def __enter__(self):
        # Mock subprocess.run 来追踪 CLI 调用
        self._original_run = subprocess.run
        
        def tracked_run(*args, **kwargs):
            # 记录命令
            if args:
                self.commands.append(str(args[0]))
            # 实际执行（或不执行，取决于测试需求）
            return self._original_run(*args, **kwargs)
        
        subprocess.run = tracked_run
        return self
    
    def __exit__(self, *args):
        subprocess.run = self._original_run
    
    def assert_no_commands(self):
        """断言没有 CLI 命令被执行"""
        assert len(self.commands) == 0, f"Unexpected CLI commands: {self.commands}"
    
    def assert_command_executed(self, pattern: str):
        """断言某命令被执行"""
        assert any(pattern in cmd for cmd in self.commands), \
            f"Command '{pattern}' not found in: {self.commands}"

# 使用示例
@pytest.mark.e2e
async def test_export_devices_no_cli():
    """验收：导出设备不应该执行 CLI"""
    tracker = CLICommandTracker()
    
    with tracker:
        result = await orchestrate_query("导出所有设备到 CSV")
        assert result is not None
    
    # 关键验证：零 CLI 执行
    tracker.assert_no_commands()
```

### 9.5 测试配置（conftest.py）

```python
# tests/conftest.py

import pytest
import duckdb
from pathlib import Path
import shutil

@pytest.fixture(scope="session")
def test_db():
    """测试数据库 - session 级别"""
    db_path = Path(".test_olav/db/test.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = duckdb.connect(str(db_path))
    
    # 加载测试数据
    conn.execute("""
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY,
            hostname VARCHAR,
            ip VARCHAR,
            vendor VARCHAR,
            model VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO devices VALUES
        (1, 'router1', '10.1.1.1', 'Cisco', 'ISR4451'),
        (2, 'router2', '10.1.2.1', 'Cisco', 'ASR1001'),
        (3, 'switch1', '10.1.3.1', 'Arista', '7050SX'),
        (4, 'switch2', '10.1.4.1', 'Juniper', 'EX4300'),
        (5, 'fw1', '10.1.5.1', 'Palo Alto', 'PA-3220'),
        (6, 'fw2', '10.1.6.1', 'Fortinet', 'FortiGate-600E')
    """)
    
    yield conn
    
    # 清理
    conn.close()
    shutil.rmtree(".test_olav", ignore_errors=True)

@pytest.fixture
def clean_exports():
    """清理导出目录"""
    export_dir = Path("exports")
    if export_dir.exists():
        for f in export_dir.glob("*.csv"):
            f.unlink()
    yield

@pytest.fixture
def mock_llm_for_unit_test():
    """单元测试可以 mock LLM（但不 mock 业务逻辑）"""
    # 只在单元测试中使用，E2E 测试用真实 LLM
    pass
```

### 9.6 测试分类与运行策略

```bash
# pytest.ini
[tool.pytest.ini_options]
markers = [
    "unit: 单元测试（快速，独立函数）",
    "integration: 集成测试（组件协作）",
    "e2e: 端到端测试（真实场景，需要 LLM）",
    "slow: 慢速测试（> 5 秒）",
]

# 运行策略

# 1. 开发时：只跑单元测试（快速反馈）
uv run pytest tests/unit/ -v

# 2. 提交前：跑单元 + 集成测试
uv run pytest tests/unit/ tests/integration/ -v

# 3. CI/CD：跑所有测试（包括 E2E）
uv run pytest tests/ -v

# 4. 只跑 E2E 测试
uv run pytest -m e2e -v

# 5. 排除慢速测试
uv run pytest -m "not slow" -v
```

### 9.7 测试覆盖率目标

```bash
# 生成覆盖率报告
uv run pytest tests/ --cov=src/olav --cov-report=html --cov-report=term

# 目标覆盖率
- 核心代码（agents, tools, core）：> 80%
- CLI/API：> 60%
- 配置加载：> 90%

# 忽略覆盖率检查的文件
# .coveragerc
[run]
omit =
    */tests/*
    */config/banners.py
    */__main__.py
```

### 9.8 TDD 示例：跨系统 IP 同步

```python
# tests/e2e/test_cross_system_operations.py

@pytest.mark.e2e
class TestCrossSystemOperations:
    """用户故事：跨系统数据同步"""
    
    @pytest.mark.asyncio
    async def test_sync_network_ips_to_netbox(self):
        """需求：把网络设备 IP 同步到 NetBox
        
        工作流：
        1. 从网络设备采集 IP（nornir_execute）
        2. 解析 CLI 输出
        3. 查询 NetBox 现有 IP（smart_sql_query）
        4. 对比差异
        5. 调用 NetBox API 创建新 IP（netbox_api_call）
        
        验收标准：
        1. TodoList 正确规划
        2. 所有步骤执行
        3. NetBox API 被调用
        4. 返回同步摘要
        """
        agent = create_olav_agent()
        
        # 用户输入
        result = agent.invoke({
            "messages": [{"role": "user", "content": "把网络设备 IP 同步到 NetBox"}]
        })
        
        # 验证 TodoList 创建
        # （通过 Agent 状态或日志验证）
        
        # 验证 API 调用
        # （通过 API mock 或实际调用验证）
        
        # 验证结果
        assert "同步完成" in result["messages"][-1].content
        assert "新增" in result["messages"][-1].content
```

---

## 10. 分阶段实施路线图

### Phase 0: 安全灭火（1 天）

- [ ] **修复 SQL 注入** — `api/v1/devices.py` f-string SQL → 参数化查询
- [ ] **删除死代码** — `database_enhancer.py`, `query_optimizer.py`
- [ ] **version 对齐** — pyproject.toml vs docs

### Phase 1: 建立新 Agent + 新目录结构（3-5 天）

1. **更新 `.olav/tools/`**（保持现有位置，符合 MCP 标准）
   - 从 `query_orchestrator.py` 提取 SQL 逻辑 → `.olav/tools/database.py`
   - 从 `execution_dispatcher.py` 提取 Nornir 调用 → `.olav/tools/network.py`
   - 支持跨平台迁移：用户可复制整个 `.olav/` 到新项目

2. **新建 `src/olav/agents/agent.py`** — `create_olav_agent()`
   - 单 Agent + 3 Tools（从 .olav/tools/ 动态加载）+ Skills + Middleware
   
3. **新建 `src/olav/cli/commands.py`** — /admin + /learn
   - 从 admin agent 提取 backup/restore 为直接函数
   - command_learner 保留为 placeholder（原实现未完成）

4. **新建 CLI 入口** — `olav chat` 命令
   - 调用新 agent，与旧 `olav ask` 并存

5. **验证**: 相同查询，比较新旧输出

### Phase 2: 迁移 SKILL.md（2-3 天）

1. **改写 SKILL.md** — Agent Skills 标准
   - 删除 `intent` / 改 `tools` → `allowed-tools` / 内联 prompts
   
2. **创建 `.olav/AGENTS.md`** — 从 OLAV.md 迁移偏好和别名

3. **验证**: Skills progressive disclosure 正确触发

### Phase 3: 切换 + 删除旧代码（3-5 天）

1. **CLI 切换** — `olav ask` → 新 agent 路径
2. **删除 20 个旧文件**（见 5.1）
3. **合并 DB 模块** — `unified_database.py` → `database.py`
4. **验证**: E2E 全量测试

### Phase 4: 高级能力（可选，2-3 天）

- [ ] **Long-term Memory** — `/memories/` 持久化
- [ ] **HITL** — `interrupt_on={"nornir_execute": True}`
- [ ] **Structured Output** — `response_format=QueryResult`
- [ ] **ModelFallbackMiddleware** — OpenRouter → Ollama
- [ ] **Data Import Framework** — `/admin import-data` 命令
  - 支持 NetBox、Zabbix、OpenSearch、Prometheus
  - 自动 schema mapping 到 DuckDB
  - 增量更新 + 定时同步

### 总时间: ~2 周

---

## 11. 代码示例

### 7.1 数据不足时的自然 fallback

```
用户: "OSPF邻居状态是什么?"

Agent 思考:
  → Skills 匹配: network-expert (需要 live + DB 数据)
  → 加载 network-expert Skill 指令
  
  Step 1: smart_sql_query(query="OSPF neighbor data")
  → "Database has no OSPF neighbor table. Available: devices, interfaces."
  
  Step 2: list_devices() 
  → "6 devices: router1(10.1.1.1), router2(10.1.2.1)..."
  
  Step 3: nornir_execute(command="show ip ospf neighbor", devices=["router1", "router2"...])
  → "router1: Neighbor 10.1.1.2, State FULL/BDR, router2: Neighbor 10.1.2.2, State FULL/DR"
  
Agent 输出:
  "## OSPF 邻居状态
  | 设备 | 邻居 | 状态 | 角色 |
  | router1 | 10.1.1.2 | FULL | BDR |
  | router2 | 10.1.2.2 | FULL | DR |
  
  所有 OSPF 邻居关系正常。"
```

**零代码实现 fallback** — Agent 自然判断"数据库没有 → 用 CLI 补充"，因为 network-expert Skill 指令写了这个 workflow。

### 7.2 复杂任务的 TodoList 规划

```
用户: "检查所有设备健康状态，生成报告"

Agent 激活 network-inspection Skill + TodoListMiddleware:

  write_todos([
    {"task": "Get device inventory", "status": "pending"},
    {"task": "Check interface errors on each device", "status": "pending"},
    {"task": "Check BGP peer status", "status": "pending"},
    {"task": "Check CPU/Memory utilization", "status": "pending"},
    {"task": "Generate health report", "status": "pending"},
  ])
  
  → smart_sql_query(sql="SELECT hostname, ip, vendor FROM devices")
  → nornir_execute(command="show interfaces brief", devices=[...])  
  → nornir_execute(command="show bgp summary", devices=[...])
  → nornir_execute(command="show processes cpu", devices=[...])
  → 综合所有数据，生成报告
```

### 7.3 /admin 命令

```
> /admin backup
✅ Configuration backed up to .olav/backups/2026-02-14_143022.tar.gz

> /admin status
OLAV v0.12.0
Database: .olav/db/main.duckdb (6 devices, 24 interfaces)
Skills: 8 loaded (network-query, network-cli, network-expert...)
LLM: grok-4.1-fast via OpenRouter

> /admin create-skill
Interactive wizard:
  Skill name: netbox
  Description: Query NetBox DCIM/IPAM for planning data
  Tools: netbox_query
  ...
  Created: .olav/skills/netbox/SKILL.md ✅

> /learn "show ip ospf neighbor"
Executing on router1...
Output fields detected: Neighbor ID, Priority, State, Dead Time, Address, Interface
Approve fields? [Y/n] y
Generating TextFSM template...
Template saved to .olav/templates/custom/show_ip_ospf_neighbor.textfsm ✅
```

### 7.4 API 使用

```python
from olav.agents.agent import create_olav_agent

agent = create_olav_agent()
config = {"configurable": {"thread_id": "api-session-1"}}

# 简单查询 — Agent 直接调 smart_sql_query
result = agent.invoke(
    {"messages": [{"role": "user", "content": "有多少个设备?"}]},
    config=config,
)

# CLI 命令 — Agent 直接调 nornir_execute
result = agent.invoke(
    {"messages": [{"role": "user", "content": "show version on router1"}]},
    config=config,
)

# 复杂分析 — Agent 使用 TodoList + 多 tools
result = agent.invoke(
    {"messages": [{"role": "user", "content": "为什么BGP邻居不稳定?"}]},
    config=config,
)
```

### 11.3 Admin 管理（两种方式）

**方式 A: CLI 快速命令**（推荐日常使用）

```bash
# 直接函数调用，不经过 LLM（< 1s）
olav admin backup
# ✅ Backup created: .olav/backups/2026-02-14_143022.tar.gz
#    Size: 47.2 MB
#    Files: 156

olav admin status
# 📊 OLAV System Status
#    Version: v0.12.0
#    Database: .olav/db/main.duckdb (47.1 MB, 6 devices, 24 interfaces)
#    Skills: 7 loaded (network-query, network-cli, network-expert...)
#    LLM: grok-4.1-fast via OpenRouter

olav admin restore 2026-02-14_143022.tar.gz
# ✅ Restored successfully
#    Files restored: 156
```

**方式 B: 对话式管理**（推荐复杂操作）

```bash
# 通过 olav-admin skill（经过 LLM，3-5s，但更智能）
olav ask "帮我创建一个查询 NetBox IP 分配的 skill"
# Agent 读取参考文档 → 生成 SKILL.md → 询问确认 → 创建文件

olav ask "为什么我的 BGP 查询很慢？查看优化建议"
# Agent 搜索 DATABASE_GUIDE.md → 分析查询 → 给出优化方案

olav ask "备份配置，但排除日志文件"
# Agent 智能理解需求 → 调用 backup_config(exclude=['logs/'])
```

**两者对比**:

| 方式 | 速度 | 灵活性 | 适用场景 |
|------|------|--------|----------|
| CLI 命令 | 快（< 1s） | 低 | 日常备份、状态查询 |
| 对话式 | 慢（3-5s） | 高 | Skill 创建、架构查询、复杂操作 |

**实现**:

```python
# src/olav/cli/admin.py

@click.group()
def admin():
    """OLAV system administration commands"""
    pass

@admin.command()
def backup():
    """Backup OLAV configuration"""
    from olav.lib.admin import backup_config
    
    result = backup_config()
    if result["status"] == "success":
        print(f"✅ Backup created: {result['file']}")
    else:
        print(f"❌ Backup failed: {result['error']}")

@admin.command()
def status():
    """Show OLAV system status"""
    from olav.lib.admin import get_system_status
    
    status = get_system_status()
    print(f"📊 OLAV System Status")
    print(f"   Version: {status['version']}")
    print(f"   Database: {status['database']['path']} ({status['database']['size']})")
    # ... more info
```

### 11.4 Cron 定时任务（python-crontab Tool）

**架构演进**: Bash 脚本 → python-crontab Tool

```
用户输入（三种方式）
 ├── 对话式: "设置每天6点执行检查" → Agent → manage_inspection_schedule tool
 ├── CLI: olav admin schedule ... → 直接调用 tool
 └── 调试: echo '{...}' | python3 .olav/tools/inspection.py
                           ↓
         Tool: manage_inspection_schedule (.olav/tools/inspection.py)
         - python-crontab 编程式管理系统 cron
         - Actions: schedule, unschedule, list, run, status, logs
                           ↓
                   System Crontab
         OLAV-daily-inspection: 0 6 * * *
         Command: cd ... && uv run olav inspect daily-inspection
                           ↓
                 Agent + TodoListMiddleware
                           ↓
                执行 Tools (nornir, sql)
                           ↓
               生成报告 + 日志
```

**核心优势**: python-crontab vs Bash 脚本 vs APScheduler

| 特性 | python-crontab Tool | Bash 脚本 | APScheduler |
|------|-------------------|-----------|-------------|
| **编程式管理** | ✅ Python API | ❌ 手动编辑 | ✅ Python API |
| **Agent 可控** | ✅ LLM调用tool | ❌ subprocess | ✅ 但复杂 |
| **架构统一** | ✅ Tool 模式 | ❌ 外部脚本 | ⚠️ 常驻进程 |
| **资源占用** | 无（按需）| 无 | 常驻进程 |
| **依赖** | 1 个包 | 零 | 多个包 |
| **监控** | Python API | crontab -l | 自定义 |

**实现**: Tool 创建

```python
# .olav/tools/inspection.py（已创建）
from crontab import CronTab
from langchain_core.tools import tool

@tool
def manage_inspection_schedule(
    action: str,
    workflow: str = "daily-inspection",
    schedule: str | None = None,
    enabled: bool = True,
    days: int = 7
) -> dict:
    """Manage network inspection schedules.
    
    Actions:
        - schedule: Create/update schedule
        - unschedule: Remove schedule
        - list: List all schedules
        - run: Execute immediately
        - status: Check history
        - logs: View logs
    """
    cron = CronTab(user=True)
    
    if action == "schedule":
        job = cron.new(
            command=f"cd {PROJECT_ROOT} && uv run olav inspect {workflow}",
            comment=f"OLAV-{workflow}"
        )
        job.setall(schedule)
        job.enable(enabled)
        cron.write()
        return {"status": "success", "next_run": str(job.schedule().get_next())}
    # ... other actions
```

**使用方式**:

```bash
# 1. 对话式（Agent 调用）
uv run olav ask "设置每天早上6点执行网络检查"

# 2. CLI 快捷命令
olav admin schedule daily-inspection "0 6 * * *"
olav admin inspect run       # 立即执行
olav admin inspect status    # 查看历史
olav admin inspect list      # 列出所有任务

# 3. 直接调用 Tool（调试）
echo '{"action":"schedule","schedule":"0 6 * * *"}' | python3 .olav/tools/inspection.py
echo '{"action":"list"}' | python3 .olav/tools/inspection.py
echo '{"action":"run"}' | python3 .olav/tools/inspection.py

# 4. 验证 crontab
crontab -l | grep OLAV
# 输出: OLAV-daily-inspection: 0 6 * * * cd /home/yhvh/Olav && uv run olav inspect daily-inspection
```

**特性**:
- ✅ **编程式管理**: 无需手动 `crontab -e`，通过 Python API 管理
- ✅ **Agent 可控**: LLM 可自然语言调用 "设置定时任务"
- ✅ **架构统一**: Tool 与 smart_sql_query、nornir_execute 一致
- ✅ **零运行开销**: 按需调用，无常驻进程
- ✅ **日志追踪**: 自动记录到 `.olav/logs/inspection_YYYYMMDD.log`
- ✅ **报告生成**: 输出到 `exports/reports/snapshots/YYYYMMDD.md`
- ✅ **并发控制**: Lock file 防止重复执行
- ✅ **超时保护**: 30 分钟 timeout

**为什么不用 Bash 脚本？**
- ❌ 无法被 Agent 直接调用（需 subprocess）
- ❌ 状态查询复杂（需解析 crontab 输出）
- ❌ 与 OLAV 架构不统一（外部脚本 vs Tool）

**为什么不用 APScheduler？**
- ❌ 需要常驻进程（资源占用）
- ❌ 需要监控进程健康
- ❌ 复杂度高（日志轮转、进程管理）
- ❌ OLAV 只需固定时间任务（系统 cron 足够）

**部署流程**:

```bash
# 1. 安装依赖
uv sync  # python-crontab 已加入 pyproject.toml

# 2. 设置定时任务
olav admin schedule daily-inspection "0 6 * * *"

# 3. 验证
crontab -l | grep OLAV

# 4. 测试执行
olav admin inspect run

# 5. 查看日志
tail -f .olav/logs/cron.log
tail -f .olav/logs/inspection_$(date +%Y%m%d).log

# 6. 查看报告
cat exports/reports/snapshots/$(date +%Y%m%d).md
```

**监控 & 通知**（可选）:

```python
# Tool 内置 Webhook 通知（配置后自动发送）
# 在 .olav/settings.json 配置:
{
  "notifications": {
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "enabled": true
  }
}

# 通知格式（自动发送）
🤖 OLAV Inspection [SUCCESS]: 
✅ Healthy: 5 devices
⚠️  Warning: 1 device (R1 - CPU 62%)
📊 Report: exports/reports/snapshots/20260214.md
```

**详细文档**: `dev_docs/ADMIN_AND_CRON_DESIGN_v2.md`

---

## 12. 关键架构问题

### Q1: 一个 Agent 不会路由错误吗？

**没有路由。** Agent 有 3 个 tools，每个 tool 名称+docstring 就告诉 LLM 它做什么：
- `smart_sql_query` — "Execute a DuckDB query"
- `nornir_execute` — "Execute a CLI command on network devices"
- `list_devices` — "List all network devices in inventory"

LLM 看到用户问"有多少设备"→ 直接调 `smart_sql_query`，不需要先判断"该给 query agent 还是 cli agent"。

**Skills 提供 HOW，不提供路由**。network-query skill 教 Agent "用 smart_sql_query 时先 query schema 再执行 SQL"，这是操作指南，不是路由。

### Q2: 数据不足时如何 fallback？

Agent 持有所有 3 个 tools，完全可以自己决定：
1. `smart_sql_query` 查数据 → 数据不足
2. `nornir_execute` 补充 live 数据
3. 综合分析

Skill 在 Instructions 里写 "If database lacks data → use nornir_execute"，LLM 自然遵循。

**这比 SubAgent fallback 更简单更快** — 没有 SubAgent 间的上下文传递开销。

### Q3: 上下文会膨胀吗？

| 机制 | 处理 |
|------|------|
| 简单查询 | 1-2 tool 调用，上下文极小 |
| 复杂分析 | SummarizationMiddleware 自动压缩 |
| 超大 tool 输出 | DeepAgents 自动 offload 到 filesystem（>20K tokens） |
| 极长对话 | Summarization 触发，保留最近 20 条消息 |
| 一次性大任务 | 委派给 general-purpose SubAgent 隔离上下文 |

DeepAgents 内建的 general-purpose SubAgent 始终可用 — Agent 自己判断"这个子任务很大，委派给 general-purpose 做，只取回摘要"。

### Q4: 未来加新系统怎么办？**数据导入优先策略**

**关键洞察**：smart_sql_query 是 schema-aware 的 → 新数据源 = 导入 DuckDB + 加 Skill

```python
# 场景 1: 只读数据源（NetBox、Zabbix、OpenSearch）
# Step 1: 导入数据
/admin import-data --source netbox
# → 创建 netbox_sites, netbox_racks, netbox_devices 等表

# Step 2: 创建 Skill
cat > .olav/skills/netbox/SKILL.md << 'EOF'
name: netbox
allowed-tools: smart_sql_query  # 复用现有 tool
Instructions: Query netbox_* tables for DCIM/IPAM data
EOF

# Step 3: 完成 ✅
# Agent 自动发现新表 schema，零代码改动

# 场景 2: 需要写操作（创建设备、分配 IP、确认告警）
# → 加 1-2 个 tools（如 netbox_api_call, zabbix_ack）
# → 总 tools 数: 3 + 2 = 5，仍然不需要 SubAgent

# 场景 3: 集成 10+ 系统，tools > 30
# → 这时才考虑 SubAgent 或 LLMToolSelectorMiddleware
# → 但这是遥远的未来（5+ 年后）
```

**为什么数据导入模式更好？**

| 维度 | SubAgent 模式 | 数据导入模式 |
|------|--------------|-------------|
| 集成成本 | 写 tool + SubAgent config | **导入脚本（一次性）** |
| Agent 复杂度 | 路由逻辑 | **零变化** |
| 查询性能 | API 调用延迟 | **本地 DuckDB** |
| 关联查询 | 跨 SubAgent 困难 | **SQL JOIN** |
| Schema 感知 | 手动维护 | **自动发现** |
| 适用范围 | 所有系统 | **只读数据源（90%）** |

### Q5: Admin 和 Command Learner 为什么不用 Agent？

| 任务 | 特征 | 适合 |
|------|------|------|
| 备份配置 | 确定性，一步完成 | **/admin 命令** |
| 查看系统状态 | 确定性，无推理 | **/admin 命令** |
| 创建 Skill | 可能需要 LLM 辅助，但有固定流程 | **/admin 向导** |
| TextFSM 学习 | 有 HITL 审批流程，独立于查询 | **/learn 工作流** |
| "有多少设备" | 需要推理、工具调用 | **Agent** |
| "BGP 为什么不稳定" | 需要多步推理、多工具 | **Agent** |

**原则**: 确定性操作用命令，需要推理的用 Agent。

---

## 13. 风险与缓解

### 13.1 DeepAgents Async 兼容性

| 风险 | `orchestrate_query_sync` 存在因为 DeepAgents async + OpenRouter deadlock |
|------|---|
| 缓解 | 1. 测试最新 DeepAgents/LangChain 版本 |
|      | 2. 使用 `agent.invoke()`（sync）而非 `agent.ainvoke()` |
|      | 3. `ModelFallbackMiddleware` 切换到 Ollama |

### 13.2 Skill 匹配准确性

| 风险 | Agent 可能不激活正确的 Skill |
|------|---|
| 缓解 | 1. Skill description 写清触发条件 |
|      | 2. system_prompt 补充通用指南 |
|      | 3. 测试覆盖 top 20 常见查询场景 |

### 13.3 单 Agent 上下文膨胀

| 风险 | 长对话中 tool 输出堆积 |
|------|---|
| 缓解 | 1. SummarizationMiddleware (100K tokens 触发) |
|      | 2. DeepAgents 自动 offload >20K token 的 tool 输出 |
|      | 3. 复杂子任务委派给 general-purpose SubAgent |

### 13.4 回滚策略

- Phase 1 新旧路径并存
- Phase 3 删除前 E2E 测试全通过
- Git tag `v0.12.0-pre-simplification`

---

## 14. 验收标准

### 功能验收

| # | 测试场景 | 预期行为 |
|---|----------|----------|
| 1 | `"有多少个设备?"` | 直接调 smart_sql_query，返回数量 |
| 2 | `"show version on router1"` | 直接调 nornir_execute，返回版本信息 |
| 3 | `"export all devices to csv"` | smart_sql_query + export_format="csv" |
| 4 | `"为什么BGP邻居不稳定?"` | 先查 DB，不足则 CLI 补充，返回分析 |
| 5 | `"检查所有设备健康状态"` | TodoList 规划 + 多 tool 调用 + 报告 |
| 6 | `"OSPF邻居状态"` | DB 无数据 → 自动 CLI fallback |
| 7 | 连续10轮对话 | 上下文不溢出（Summarization） |
| 8 | `/admin backup` | <100ms，直接函数调用 |
| 9 | `/admin status` | 返回系统状态，无 LLM |
| 10 | `/help` | 显示所有命令 |
| 11 | 导入外部数据（模拟 NetBox） | `/admin import-data` → 创建新表 → Skill 自动发现 schema |
| 12 | 查询导入的数据 | Agent 自动识别新表，无需重启 |

### 代码量验收

| 指标 | 当前 | 目标 | 减少 |
|------|------|------|------|
| Agent 层 | ~5,000+ 行 | ~50 行 | **99%** |
| CLI 层 | ~2,500 行 | ~250 行 | 90% |
| Core 层 | ~5,900 行 | ~2,500 行 | 58% |
| 总计 | ~22,750 行 | ~13,700 行 | **40%** |

### 架构验收

- [ ] **一个** `create_deep_agent()` 调用
- [ ] **三个** tools：smart_sql_query, nornir_execute, list_devices
- [ ] **零** 自定义路由逻辑
- [ ] **零** 自定义会话管理
- [ ] **零** SubAgent（除 general-purpose 内建）
- [ ] Skills 通过 SkillsMiddleware 原生热加载
- [ ] /admin 和 /learn 是直接函数调用

---

## 附录 A：架构演进记录

| 版本 | 架构 | 问题/改进 |
|------|------|---------|
| v0.x | Guard→Dispatcher→多Agent | 路由复杂，Guard 1000行，Agent被绕过 |
| v1.0 方案 | 5 SubAgent (query/cli/expert/inspector/admin) | 还是在做路由，3个tools不需要拆5个agent |
| v1.5 方案 | 2 SubAgent (expert + admin) | 更简单，但 admin 不需要 LLM |
| **v2.0 方案** | **1 Agent + Skills + /CMD** | **极简：零路由，知识热加载，命令确定执行** |
| **v2.1 洞察** | **DuckDB 统一数据层** | **新系统 = 数据导入 + Skill，SubAgent 是过度设计** |

**关键发现**（2026-02-14）：
- smart_sql_query 的 schema-aware 机制 → 新数据源只需导入 DuckDB
- 90% 外部系统集成场景：零新 tools，零 SubAgent
- SubAgent 仅在 tools > 15 或需要隔离执行环境时才考虑

## 附录 B：与审计报告优先级对应

| 审计优先级 | 项目 | 本方案覆盖 |
|-----------|------|-----------|
| P0 | SQL 注入修复 | Phase 0 |
| P0 | 版本对齐 | Phase 0 |
| P1 | 删除死代码 | Phase 0 + Phase 3 |
| P1 | 统一 DB 模块 | Phase 3 |
| P1 | 统一缓存 | Phase 3 |
| P2 | 恢复 DeepAgents 主路径 | **Phase 1（核心）** |
| P2 | 删除 Guard + Dispatcher | Phase 3 |
| P3 | 平台抽象 | Phase 4 |

## 附录 C：DeepAgents API 速查

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain.agents.middleware import (
    SummarizationMiddleware, TodoListMiddleware, ToolRetryMiddleware,
    ModelFallbackMiddleware, HumanInTheLoopMiddleware,
    LLMToolSelectorMiddleware, ModelCallLimitMiddleware,
)

agent = create_deep_agent(
    model="openai:gpt-4.1",           # or LangChain model object
    tools=[func1, func2],              # plain Python functions
    skills=[".olav/skills/"],          # skill directories (progressive disclosure)
    memory=["/AGENTS.md"],             # always-loaded context files
    middleware=[...],                   # middleware instances
    backend=lambda rt: CompositeBackend(...),
    checkpointer=MemorySaver(),        # state persistence
    store=InMemoryStore(),             # cross-thread storage
    system_prompt="...",               # prepended to built-in prompt
    name="olav",                       # agent name for tracing
    interrupt_on={"tool": True},       # HITL config
    response_format=PydanticModel,     # structured output
    # subagents=[...],                 # 未来需要时再添加
)
```

---

**文档结束**  
**下一步**: 审阅 → 批准 → Phase 0  
**预估工期**: ~2 周（Phase 0-3）+ 1 周（Phase 4 可选）
